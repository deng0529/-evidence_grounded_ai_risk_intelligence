"""Additive obligation validation over explicit structured profile and filing evidence.

No legal deadline is inferred. Snapshot observation, obligation period, due date,
filing date and assessment date remain separate. This module calculates no lateness.
"""

from datetime import date
import json
from typing import Literal

from risk_intelligence.domain.common import Contract, Text, UtcTimestamp
from risk_intelligence.domain.enums import (
    AdmissibilityReason, AvailabilityStatus, ConflictLevel, ConflictResolution,
    CriticalTransformation, SourceType, ValidationRole, ValidationStatus,
)
from risk_intelligence.domain.facts import BooleanValue, StructuredFact
from risk_intelligence.domain.reliability import ConflictState, ReliabilityAssessment
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from risk_intelligence.persistence.ingestion_repository import Snapshot
from risk_intelligence.persistence.validated_members import ValidatedMembers
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.policy import assess_reliability

OBLIGATION_RULESET = "obligation-validation-v1"
ObligationKind = Literal["ACCOUNTS", "CONFIRMATION_STATEMENT"]


class ValidatedObligation(Contract):
    """Immutable source-backed obligation and M4 result; unresolved values remain null."""

    validated_obligation_id: Text
    company_id: Text
    company_number: Text
    processing_run_id: Text
    assessment_date: date
    obligation_kind: ObligationKind
    snapshot_observed_at: UtcTimestamp
    profile_snapshot_id: Text
    validated_filing_set_id: Text
    obligation_period: date | None
    due_date: date | None
    filing_date: date | None
    filing_state: Literal["FILED", "OUTSTANDING", "UNRESOLVED"]
    fact_ids: tuple[Text, ...]
    evidence_ids: tuple[Text, ...]
    source_ids: tuple[Text, ...]
    assessment: ReliabilityAssessment


class ObligationEvidenceRule:
    """Mandatory, admission-only gates in a separate ruleset; no support uplift."""

    def __init__(self, field: str) -> None:
        self.field = field
        self.definition = RuleDefinition(
            rule_id="obligation." + field, rule_version="1", applies_to=("OBLIGATION",),
            required_inputs=(field,), role=ValidationRole.HARD_FAIL,
        )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Withhold unresolved source relationships instead of choosing a candidate."""
        valid = next(item.value.value for item in context.fields if item.name == self.field)
        return RuleOutcome(
            rule_id=self.definition.rule_id, rule_version="1", role=self.definition.role,
            result=ValidationStatus.PASS if valid else ValidationStatus.INCONCLUSIVE,
            evidence_ids=context.evidence_ids,
            reason=f"{self.field}: " + ("established by structured evidence" if valid else "not established"),
            failure_code=None if valid else AdmissibilityReason.MISSING_REQUIRED_EVIDENCE,
        )


def obligation_registry() -> RuleRegistry:
    """Keep historical governance registry membership and versions unchanged."""
    registry = RuleRegistry(OBLIGATION_RULESET)
    for field in ("identity", "observation", "deadline_identity", "filing_match"):
        registry.register(ObligationEvidenceRule(field))
    return registry


def _unique(facts: tuple[StructuredFact, ...], concept: str) -> object:
    matches = [fact.value.value for fact in facts if fact.canonical_concept == concept
               and fact.availability_status == AvailabilityStatus.AVAILABLE]
    return matches[0] if len(matches) == 1 else None


def _filing_period(facts: tuple[StructuredFact, ...]) -> date | None:
    """Only explicit made-up date metadata identifies the filed obligation.

    Filing action_date and receipt date are not substituted for its reporting date.
    Unknown description shapes remain unresolved rather than guessed.
    """
    raw = _unique(facts, "FILINGS_DESCRIPTION_VALUES_JSON")
    if not isinstance(raw, str):
        return None
    try:
        fields = json.loads(raw)
        value = fields.get("made_up_date") if isinstance(fields, dict) else None
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
        return parsed if parsed is not None and parsed.isoformat() == value else None
    except (ValueError, TypeError):
        return None


def validate_obligation(
    *, validated_id: str, kind: ObligationKind, profile: Snapshot,
    profile_facts: tuple[StructuredFact, ...], filings: ValidatedMembers,
    assessment_date: date,
) -> ValidatedObligation:
    """Validate a snapshot's explicitly identified next obligation against exact filings.

    A historical snapshot can ground that same obligation's deadline; it never
    supplies a deadline for a different reporting period. Ambiguous relevant
    filing records prevent both a match and a claim of outstanding status.
    """
    if kind not in ("ACCOUNTS", "CONFIRMATION_STATEMENT"):
        raise ValueError("Unsupported obligation kind")
    prefix = "PROFILE_ACCOUNTS_NEXT_ACCOUNTS_" if kind == "ACCOUNTS" else "PROFILE_CONFIRMATION_STATEMENT_"
    period = _unique(profile_facts, prefix + ("PERIOD_END_ON" if kind == "ACCOUNTS" else "NEXT_MADE_UP_TO"))
    due = _unique(profile_facts, prefix + ("DUE_ON" if kind == "ACCOUNTS" else "NEXT_DUE"))
    period = period if type(period) is date else None
    due = due if type(due) is date else None
    company_number = filings.validated.company_number
    identity = (profile.resource.value == "profile" and profile.company_id == filings.validated.company_id
                and _unique(profile_facts, "PROFILE_COMPANY_NUMBER") == company_number
                and all(f.company_number == company_number and f.company_id == profile.company_id
                        for f in profile_facts))
    observed = (profile.complete and profile.availability_status == AvailabilityStatus.AVAILABLE
                and profile.checked_at.date() <= assessment_date
                and filings.validated.assessment_date == assessment_date)
    groups: dict[str, list[StructuredFact]] = {}
    for fact in filings.facts:
        if fact.subject_identifier is not None:
            groups.setdefault(fact.subject_identifier, []).append(fact)
    matches: list[date] = []
    ambiguous = False
    expected_category = "accounts" if kind == "ACCOUNTS" else "confirmation-statement"
    for items in groups.values():
        event = tuple(items)
        category = _unique(event, "FILINGS_CATEGORY")
        if category is None:
            ambiguous = True
            continue
        if category != expected_category:
            continue
        receipt = _unique(event, "FILINGS_DATE")
        key = _filing_period(event)
        if type(receipt) is not date or key is None:
            ambiguous = True
        elif receipt <= assessment_date and key == period:
            matches.append(receipt)
    population_ok = (filings.validated.evidence_set_type == "FILING_EVENTS_36M"
                     and filings.validated.validation_report.admissible
                     and filings.validated.availability_status == AvailabilityStatus.AVAILABLE
                     and filings.validated.analytical_window_end >= assessment_date)
    # Absence is meaningful only when the coverage includes the observation of
    # this obligation. A stale profile outside the filing horizon cannot prove it.
    absence_covered = filings.validated.analytical_window_start <= profile.checked_at.date()
    match_ok = (population_ok and not ambiguous and len(matches) <= 1
                and (bool(matches) or absence_covered) and period is not None and due is not None)
    fields = {"identity": identity, "observation": observed,
              "deadline_identity": period is not None and due is not None, "filing_match": match_ok}
    all_facts = tuple(sorted((*profile_facts, *filings.facts), key=lambda fact: fact.fact_id))
    evidence = tuple(sorted({e for f in all_facts for e in f.evidence_ids}
                            | set(filings.validated.validation_report.context.evidence_ids)))
    context = AnalyticalInput(
        input_id=validated_id, input_type="OBLIGATION", company_number=company_number,
        assessment_date=assessment_date, evidence_ids=evidence,
        fields=tuple(ValidationField(name=k, value=BooleanValue(value=v)) for k, v in fields.items()),
    )
    report = ValidationEngine(obligation_registry()).validate(context)
    conflict = ConflictState(
        level=ConflictLevel.SERIOUS_UNRESOLVED if len(matches) > 1 else ConflictLevel.NONE,
        resolution=ConflictResolution.UNRESOLVED if len(matches) > 1 else ConflictResolution.NONE,
        reason="Multiple obligation filings" if len(matches) > 1 else "No definite competing match",
        evidence_ids=evidence if len(matches) > 1 else (),
    )
    assessment = assess_reliability(
        report, SourceType.COMPANIES_HOUSE_API, CriticalTransformation.STRUCTURED_DETERMINISTIC,
        conflict, transformation_chain=("M2 structured profile and filings", "obligation matching v1"),
    )
    usable = assessment.calculation.supported_analytical_evidence
    return ValidatedObligation(
        validated_obligation_id=validated_id, company_id=profile.company_id,
        company_number=company_number, processing_run_id=filings.validated.processing_run_id,
        assessment_date=assessment_date, obligation_kind=kind,
        snapshot_observed_at=profile.checked_at, profile_snapshot_id=profile.snapshot_id,
        validated_filing_set_id=filings.validated.validated_evidence_set_id,
        obligation_period=period, due_date=due, filing_date=matches[0] if usable and matches else None,
        filing_state=("FILED" if matches else "OUTSTANDING") if usable else "UNRESOLVED",
        fact_ids=tuple(sorted({f.fact_id for f in all_facts})), evidence_ids=evidence,
        source_ids=tuple(sorted({f.source_id for f in all_facts})), assessment=assessment,
    )
