"""Deterministic M4 governance evidence-set validation over M2 structured handoff."""

from dataclasses import dataclass
from datetime import date

from risk_intelligence.domain.enums import (
    AdmissibilityReason,
    AvailabilityStatus,
    EvidenceUse,
    ValidationRole,
    ValidationStatus,
    ValidationStrength,
)
from risk_intelligence.domain.facts import BooleanValue, CodesValue, DateValue, StructuredFact
from risk_intelligence.domain.validation import (
    AnalyticalInput,
    RuleDefinition,
    RuleOutcome,
    ValidationField,
)
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.persistence.ingestion_repository import Snapshot
from risk_intelligence.validation.engine import RuleRegistry


GOVERNANCE_RULESET_VERSION = "governance-validation-v1"

OFFICER_EVENTS_24M = "OFFICER_EVENTS_24M"
PSC_EVENTS_36M = "PSC_EVENTS_36M"
FILING_EVENTS_36M = "FILING_EVENTS_36M"


def _field(context: AnalyticalInput, name: str):
    return next(item.value.value for item in context.fields if item.name == name)


def _outcome(
    rule,
    result: ValidationStatus,
    reason: str,
    *,
    evidence_ids=(),
    failure=None,
    strength=ValidationStrength.NONE,
    use=EvidenceUse.ADMISSION_ONLY,
    group=None,
) -> RuleOutcome:
    return RuleOutcome(
        rule_id=rule.definition.rule_id,
        rule_version=rule.definition.rule_version,
        result=result,
        role=rule.definition.role,
        validation_strength_candidate=strength,
        evidence_use=use,
        independence_group=group,
        evidence_ids=tuple(evidence_ids),
        reason=reason,
        failure_code=failure,
    )


@dataclass(frozen=True)
class GovernanceEvidenceSet:
    """M2 structured coverage plus event facts for one M4 analytical population."""

    input_id: str
    input_type: str
    company_number: str
    assessment_date: date
    window_start: date
    snapshots: tuple[Snapshot, ...]
    facts: tuple[StructuredFact, ...]

    def analytical_input(self) -> AnalyticalInput:
        if self.window_start > self.assessment_date:
            raise ValueError(
                "Governance analytical window cannot start after assessment date"
            )
        if not self.snapshots:
            raise ValueError(
                "Governance evidence set requires resource snapshot metadata"
            )

        if any(
            snapshot.company_id != self.snapshots[0].company_id
            for snapshot in self.snapshots
        ):
            raise ValueError("Governance snapshots must belong to one company")

        if any(fact.company_number != self.company_number for fact in self.facts):
            raise ValueError(
                "Governance facts must match the analytical company"
            )

        expected = {
            OFFICER_EVENTS_24M: {Resource.OFFICERS},
            FILING_EVENTS_36M: {Resource.FILINGS},
            PSC_EVENTS_36M: {Resource.PSC, Resource.STATEMENTS},
        }.get(self.input_type)

        if expected is None:
            raise ValueError("Unsupported governance evidence-set type")

        by_resource = {
            snapshot.resource: snapshot for snapshot in self.snapshots
        }

        required_present = expected <= set(by_resource)

        relevant = tuple(
            by_resource[resource]
            for resource in sorted(expected, key=lambda item: item.value)
            if resource in by_resource
        )

        pagination_complete = (
            required_present and all(item.complete for item in relevant)
        )

        window_complete = (
            required_present
            and all(
                item.coverage_start <= self.window_start
                and item.coverage_end >= self.assessment_date
                for item in relevant
            )
        )

        pairs = [
            (fact.subject_identifier, fact.canonical_concept)
            for fact in self.facts
        ]

        duplicate_free = (
            len(pairs) == len(set(pairs))
            and all(subject is not None for subject, _ in pairs)
        )

        grouped: dict[str, dict[str, StructuredFact]] = {}

        for fact in self.facts:
            if fact.subject_identifier is not None:
                grouped.setdefault(
                    fact.subject_identifier, {}
                )[fact.canonical_concept] = fact

        chronology_valid = True
        anchor_complete = True

        if self.input_type == OFFICER_EVENTS_24M:
            for event in grouped.values():
                appointed = event.get("OFFICERS_APPOINTED_ON")
                appointed_before = event.get("OFFICERS_APPOINTED_BEFORE")
                resigned = event.get("OFFICERS_RESIGNED_ON")

                has_anchor = bool(
                    (
                        appointed is not None
                        and appointed.value.value is not None
                    )
                    or (
                        appointed_before is not None
                        and appointed_before.value.value is not None
                    )
                )
                anchor_complete &= has_anchor

                if (
                    appointed is not None
                    and resigned is not None
                    and appointed.value.value is not None
                    and resigned.value.value is not None
                ):
                    chronology_valid &= (
                        appointed.value.value <= resigned.value.value
                    )

        elif self.input_type == PSC_EVENTS_36M:
            for event in grouped.values():
                notified = (
                    event.get("PSC_NOTIFIED_ON")
                    or event.get("STATEMENTS_NOTIFIED_ON")
                )
                ceased = (
                    event.get("PSC_CEASED_ON")
                    or event.get("STATEMENTS_CEASED_ON")
                )

                if (
                    notified is not None
                    and ceased is not None
                    and notified.value.value is not None
                    and ceased.value.value is not None
                ):
                    chronology_valid &= (
                        notified.value.value <= ceased.value.value
                    )

        # Snapshot identity is retained even for a valid empty population.
        # Therefore zero PSC events does not become "missing evidence".
        evidence_ids = tuple(
            dict.fromkeys(
                [snapshot.snapshot_id for snapshot in relevant]
                + [
                    evidence_id
                    for fact in self.facts
                    for evidence_id in fact.evidence_ids
                ]
            )
        )

        availability = (
            AvailabilityStatus.AVAILABLE
            if required_present
            else AvailabilityStatus.RETRIEVAL_FAILED
        )

        fields = (
            ValidationField(
                name="pagination_complete",
                value=BooleanValue(value=pagination_complete),
            ),
            ValidationField(
                name="window_complete",
                value=BooleanValue(value=window_complete),
            ),
            ValidationField(
                name="duplicate_free",
                value=BooleanValue(value=duplicate_free),
            ),
            ValidationField(
                name="chronology_valid",
                value=BooleanValue(value=chronology_valid),
            ),
            ValidationField(
                name="officer_anchor_complete",
                value=BooleanValue(value=anchor_complete),
            ),
            ValidationField(
                name="psc_resources_complete",
                value=BooleanValue(
                    value=(
                        self.input_type != PSC_EVENTS_36M
                        or (
                            required_present
                            and pagination_complete
                            and window_complete
                        )
                    )
                ),
            ),
            ValidationField(
                name="window_start",
                value=DateValue(value=self.window_start),
            ),
            ValidationField(
                name="resource_names",
                value=CodesValue(
                    value=tuple(
                        sorted(resource.value for resource in by_resource)
                    )
                ),
            ),
        )

        return AnalyticalInput(
            input_id=self.input_id,
            input_type=self.input_type,
            company_number=self.company_number,
            assessment_date=self.assessment_date,
            availability_status=availability,
            fields=fields,
            evidence_ids=evidence_ids,
        )


class PaginationCoverageRule:
    definition = RuleDefinition(
        rule_id="governance.pagination_coverage",
        rule_version="1",
        applies_to=(
            OFFICER_EVENTS_24M,
            PSC_EVENTS_36M,
            FILING_EVENTS_36M,
        ),
        required_inputs=("pagination_complete",),
        role=ValidationRole.HARD_FAIL,
    )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        ok = bool(_field(context, "pagination_complete"))

        return _outcome(
            self,
            ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            (
                "Resource pagination is complete"
                if ok
                else "Resource pagination completeness is not established"
            ),
            evidence_ids=context.evidence_ids,
            failure=(
                None
                if ok
                else AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE
            ),
        )


class WindowCoverageRule:
    definition = RuleDefinition(
        rule_id="governance.window_coverage",
        rule_version="1",
        applies_to=(
            OFFICER_EVENTS_24M,
            PSC_EVENTS_36M,
            FILING_EVENTS_36M,
        ),
        required_inputs=("window_complete", "window_start"),
        role=ValidationRole.HARD_FAIL,
    )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        ok = bool(_field(context, "window_complete"))

        return _outcome(
            self,
            ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            (
                "Snapshot covers the complete analytical window"
                if ok
                else "Snapshot does not cover the complete analytical window"
            ),
            evidence_ids=context.evidence_ids,
            failure=(
                None
                if ok
                else AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE
            ),
        )


class DuplicateEventRule:
    definition = RuleDefinition(
        rule_id="governance.duplicate_event",
        rule_version="1",
        applies_to=(
            OFFICER_EVENTS_24M,
            PSC_EVENTS_36M,
            FILING_EVENTS_36M,
        ),
        required_inputs=("duplicate_free",),
        role=ValidationRole.HARD_FAIL,
    )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        ok = bool(_field(context, "duplicate_free"))

        return _outcome(
            self,
            ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            (
                "No duplicate structured event observations"
                if ok
                else "Duplicate event observations make the population ambiguous"
            ),
            evidence_ids=context.evidence_ids,
            failure=(
                None
                if ok
                else AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE
            ),
        )


class EventChronologyRule:
    definition = RuleDefinition(
        rule_id="governance.event_chronology",
        rule_version="1",
        applies_to=(OFFICER_EVENTS_24M, PSC_EVENTS_36M),
        required_inputs=("chronology_valid",),
        role=ValidationRole.HARD_FAIL,
    )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        ok = bool(_field(context, "chronology_valid"))

        return _outcome(
            self,
            ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            (
                "Event chronology is internally consistent"
                if ok
                else "Event chronology is internally inconsistent"
            ),
            evidence_ids=context.evidence_ids,
            failure=(
                None
                if ok
                else AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE
            ),
        )


class OfficerAnchorCoverageRule:
    definition = RuleDefinition(
        rule_id="governance.officer_anchor_coverage",
        rule_version="1",
        applies_to=(OFFICER_EVENTS_24M,),
        required_inputs=("officer_anchor_complete",),
        role=ValidationRole.HARD_FAIL,
    )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        ok = bool(_field(context, "officer_anchor_complete"))

        return _outcome(
            self,
            ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            (
                "Every officer event has an appointment anchor"
                if ok
                else "At least one officer event lacks an appointment anchor"
            ),
            evidence_ids=context.evidence_ids,
            failure=(
                None
                if ok
                else AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE
            ),
        )


class PscCoverageRule:
    definition = RuleDefinition(
        rule_id="governance.psc_coverage",
        rule_version="1",
        applies_to=(PSC_EVENTS_36M,),
        required_inputs=("psc_resources_complete",),
        role=ValidationRole.HARD_FAIL,
    )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        ok = bool(_field(context, "psc_resources_complete"))

        return _outcome(
            self,
            ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            (
                "PSC and PSC-statement resources jointly establish coverage"
                if ok
                else (
                    "PSC coverage is incomplete because PSC and statement "
                    "resources are not both complete"
                )
            ),
            evidence_ids=context.evidence_ids,
            failure=(
                None
                if ok
                else AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE
            ),
        )


def governance_registry() -> RuleRegistry:
    registry = RuleRegistry(GOVERNANCE_RULESET_VERSION)

    for rule in (
        PaginationCoverageRule(),
        WindowCoverageRule(),
        DuplicateEventRule(),
        EventChronologyRule(),
        OfficerAnchorCoverageRule(),
        PscCoverageRule(),
    ):
        registry.register(rule)

    return registry
