"""Financial period consistency using existing structured M3 records only."""

from typing import Literal

from risk_intelligence.domain.common import Contract
from risk_intelligence.domain.enums import AdmissibilityReason, PeriodType, ValidationRole, ValidationStatus
from risk_intelligence.domain.facts import TextValue
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from .engine import RuleRegistry
from .financial import FinancialGroundingRule, FinancialIdentityRule, _outcome, _provenance


class FinancialPeriodEvidence(Contract):
    """Explicit source observations supporting the canonical period.

    Supply all relevant structured source observations, not a selected matching
    subset. None/empty means insufficient evidence; duplicate source identities
    remain visible as ambiguity. No missing period is filled from another record.
    """

    version: Literal['financial-period-evidence-v1'] = 'financial-period-evidence-v1'
    source_facts: tuple[SourceFinancialFact, ...] | None = None

    def attach(self, context: AnalyticalInput) -> AnalyticalInput:
        """Add typed source records to the existing financial input without replacing fields."""
        fields = context.fields + (ValidationField(name='financial_period_evidence',
                                                   value=TextValue(value=self.model_dump_json())),)
        return AnalyticalInput(**(context.model_dump() | {'fields': fields}))


class FinancialPeriodRule:
    """Compare canonical/source dates and applicable document reporting metadata.

    Document reporting bounds are optional in M3. When supplied, CURRENT must
    agree with the document end; COMPARATIVE must precede it. Duration starts
    are compared only for CURRENT duration observations. Filing/assessment dates
    are not reporting dates. This rule does not assess trends or comparability.
    """

    @property
    def definition(self) -> RuleDefinition:
        """Versioned mandatory period gate, with no independent support strength."""
        return RuleDefinition(rule_id='financial.period', rule_version='v1',
            applies_to=('FINANCIAL_FACT',),
            required_inputs=('financial_provenance', 'financial_period_evidence'),
            role=ValidationRole.HARD_FAIL)

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Fail definite period contradictions; withhold admission for missing/ambiguous inputs."""
        records = _provenance(context)
        field = next(f for f in context.fields if f.name == 'financial_period_evidence')
        if not isinstance(field.value, TextValue) or field.value.value is None:
            raise ValueError('Financial period evidence requires a typed JSON text payload')
        evidence = FinancialPeriodEvidence.model_validate_json(field.value.value)
        period, document = records.fact.period, records.document
        sources = sorted(evidence.source_facts or (), key=lambda source: (source.source_fact_id, source.model_dump_json()))
        details = (ValidationField(name='canonical_period',
                                  value=TextValue(value=period.model_dump_json() if period else None)),
                   ValidationField(name='document_period_start', value=TextValue(
                       value=document.period_start.isoformat() if document and document.period_start else None)),
                   ValidationField(name='document_period_end', value=TextValue(
                       value=document.period_end.isoformat() if document and document.period_end else None)))
        # A typed JSON detail retains each source ID, role and period without
        # duplicate field names or depending on caller iteration order.
        ordered = FinancialPeriodEvidence(source_facts=tuple(sources))
        details += (ValidationField(name='source_period_evidence', value=TextValue(value=ordered.model_dump_json())),)
        if period is None or not sources:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Canonical or source reporting period evidence is missing', details)
        if len({source.source_fact_id for source in sources}) != len(sources):
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Source reporting period evidence contains ambiguous duplicate identities', details)
        if (any(source.document_id != records.fact.document_id
                or source.evidence_id not in records.fact.evidence_ids for source in sources)
                or (document is not None and document.document_id != records.fact.document_id)):
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Period records cannot be linked unambiguously to the canonical fact', details)
        for source in sources:
            observed = source.period
            mismatch = (observed.period_type != period.period_type or observed.period_end != period.period_end
                or (period.period_type == PeriodType.DURATION and observed.period_start != period.period_start)
                or (observed.period_length_days is not None and period.period_length_days is not None
                    and observed.period_length_days != period.period_length_days))
            if mismatch:
                return _outcome(self.definition, context, ValidationStatus.FAIL,
                    'Source and canonical reporting periods are incompatible', details,
                    AdmissibilityReason.NON_COMPARABLE_PERIOD)
        if len({source.period_role for source in sources}) != 1:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Source records disagree about current versus comparative reporting context', details)
        if document is not None:
            current = sources[0].period_role == 'CURRENT'
            end_mismatch = document.period_end is not None and (
                period.period_end != document.period_end if current else period.period_end >= document.period_end)
            start_mismatch = (current and period.period_type == PeriodType.DURATION
                and document.period_start is not None and period.period_start != document.period_start)
            if end_mismatch or start_mismatch:
                return _outcome(self.definition, context, ValidationStatus.FAIL,
                    'Reporting period contradicts applicable document period metadata', details,
                    AdmissibilityReason.NON_COMPARABLE_PERIOD)
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'Source and canonical periods agree with available document reporting metadata', details)


def financial_period_registry() -> RuleRegistry:
    """Compose the period gate with the unchanged identity and grounding rules."""
    registry = RuleRegistry('financial-identity-grounding-period-v1')
    registry.register(FinancialIdentityRule())
    registry.register(FinancialGroundingRule())
    registry.register(FinancialPeriodRule())
    return registry
