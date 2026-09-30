"""Currency and unit/scale admissibility from structured monetary metadata only."""

import re
from typing import Literal

from risk_intelligence.domain.common import Contract, ExactDecimal, Text
from risk_intelligence.domain.enums import AdmissibilityReason, ValidationRole, ValidationStatus
from risk_intelligence.domain.facts import TextValue
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from .engine import RuleRegistry
from .financial import FinancialGroundingRule, FinancialIdentityRule, FinancialProvenance, _outcome, _provenance
from .financial_period import FinancialPeriodRule
from .financial_scope import FinancialScopeRule


class MonetarySource(Contract):
    """Nullable projection of existing M3 fields, preserving unavailable metadata.

    M3's SQL scale is explicit and non-null. Partial projections must use None,
    never the SourceFinancialFact constructor's default zero, for missing scale.
    Raw/value fields are retained as normalization provenance, never used to guess
    currency, units or scale from numeric magnitude.
    """

    source_fact_id: Text
    document_id: Text
    evidence_id: Text
    currency: Text | None = None
    unit: Text | None = None
    scale: int | None = None
    parser_version: Text | None = None
    raw_value: Text | None = None
    value: ExactDecimal | None = None

    @classmethod
    def from_source(cls, source: SourceFinancialFact) -> 'MonetarySource':
        """Copy persisted M3 metadata without parsing or changing any monetary value."""
        return cls(**{name: getattr(source, name) for name in cls.model_fields})


class FinancialMonetaryEvidence(Contract):
    """All relevant source monetary metadata; absent/duplicate observations stay unresolved."""

    version: Literal['financial-monetary-evidence-v1'] = 'financial-monetary-evidence-v1'
    sources: tuple[MonetarySource, ...] | None = None

    def attach(self, context: AnalyticalInput) -> AnalyticalInput:
        """Append structured metadata using the existing M4.1 typed JSON field boundary."""
        fields = context.fields + (ValidationField(name='financial_monetary_evidence',
            value=TextValue(value=self.model_dump_json())),)
        return AnalyticalInput(**(context.model_dump() | {'fields': fields}))


def _inputs(context: AnalyticalInput) -> tuple[
        FinancialProvenance, tuple[MonetarySource, ...], tuple[ValidationField, ...], bool]:
    records = _provenance(context)
    field = next(f for f in context.fields if f.name == 'financial_monetary_evidence')
    if not isinstance(field.value, TextValue) or field.value.value is None:
        raise ValueError('Financial monetary evidence requires a typed JSON text payload')
    metadata = FinancialMonetaryEvidence.model_validate_json(field.value.value)
    sources = tuple(sorted(metadata.sources or (), key=lambda s: (s.source_fact_id, s.model_dump_json())))
    details = (ValidationField(name='canonical_currency', value=TextValue(value=records.fact.currency)),
        ValidationField(name='canonical_unit', value=TextValue(value=records.fact.unit)),
        ValidationField(name='source_monetary_evidence', value=TextValue(
            value=FinancialMonetaryEvidence(sources=sources).model_dump_json())))
    linked = bool(sources) and len({s.source_fact_id for s in sources}) == len(sources) and all(
        s.document_id == records.fact.document_id and s.evidence_id in records.fact.evidence_ids for s in sources)
    return records, sources, details, linked


def _currency(value: str | None) -> bool:
    # M3's explicit three-letter currency identifier contract; no country default
    # or symbol-to-currency guess. This does not claim to validate an ISO catalogue.
    return value is not None and re.fullmatch(r'[A-Z]{3}', value) is not None


def _unit(value: str | None) -> bool:
    # Recognize explicit monetary labels solely for compatibility comparison.
    # Distinct labels are not silently converted or treated as interchangeable.
    return value is not None and re.fullmatch(r'(?:[A-Z]{3}(?: thousands)?|£(?:000|1)?)', value) is not None


def _definition(identity: str) -> RuleDefinition:
    return RuleDefinition(rule_id=identity, rule_version='v1', applies_to=('FINANCIAL_FACT',),
        required_inputs=('financial_provenance', 'financial_monetary_evidence'), role=ValidationRole.HARD_FAIL)


class FinancialCurrencyRule:
    """Require explicit matching currency identifiers; never infer or convert currency."""

    @property
    def definition(self) -> RuleDefinition:
        """Stable currency admissibility gate with no support strength."""
        return _definition('financial.currency')

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Definite currency differences fail; missing/ambiguous codes remain inconclusive."""
        records, sources, details, linked = _inputs(context)
        currency = records.fact.currency
        if not linked or not _currency(currency):
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Canonical currency or linked monetary provenance is missing or ambiguous', details)
        if any(_currency(source.currency) and source.currency != currency for source in sources):
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Explicit source and canonical currencies are incompatible; no conversion is authorized', details,
                AdmissibilityReason.INCOMPATIBLE_UNIT_CURRENCY)
        if any(not _currency(source.currency) for source in sources):
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Required source currency is missing or ambiguous', details)
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'Explicit source and canonical currencies match', details)


class FinancialUnitScaleRule:
    """Check declared units and upstream normalization, without scaling amounts again.

    Known M3 parsers store normalized base currency units. PDF/structure/located
    admission versions apply explicit scale 0 or 3; ixbrl-monetary-v1 applies an
    explicit exponent in [-18,18]. Nonzero normalization requires the retained
    parser version, raw value and normalized source value. This checks metadata
    compatibility, not numerical extraction accuracy or derivation arithmetic.
    """

    @property
    def definition(self) -> RuleDefinition:
        """Stable unit/scale gate with no independent support strength."""
        return _definition('financial.unit_scale')

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Reject incompatible units/scales and leave unsupported normalization unresolved."""
        records, sources, details, linked = _inputs(context)
        unit = records.fact.unit
        if not linked or not _unit(unit):
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Canonical unit or linked monetary provenance is missing or ambiguous', details)
        unresolved = False
        pdf_versions = {'pdf-table-v3', 'pdf-table-v4', 'financial-statement-structure-v3',
                        'financial-statement-structure-v4', 'located-financial-admission-v3'}
        for source in sources:
            known_pdf = source.parser_version in pdf_versions
            known_ixbrl = source.parser_version == 'ixbrl-monetary-v1'
            invalid_scale = source.scale is not None and (
                not -18 <= source.scale <= 18 or (known_pdf and source.scale not in (0, 3)))
            if (_unit(source.unit) and source.unit != unit) or invalid_scale:
                return _outcome(self.definition, context, ValidationStatus.FAIL,
                    'Explicit monetary unit or scale is incompatible with the stored representation', details,
                    AdmissibilityReason.INCOMPATIBLE_UNIT_CURRENCY)
            if not _unit(source.unit) or source.scale is None:
                unresolved = True
                continue
            if known_pdf or known_ixbrl:
                if not _currency(source.currency):
                    unresolved = True
                elif source.unit != source.currency:
                    return _outcome(self.definition, context, ValidationStatus.FAIL,
                        'Upstream parser declares base currency units but stored unit contradicts that contract',
                        details, AdmissibilityReason.INCOMPATIBLE_UNIT_CURRENCY)
            if source.scale != 0 and (not (known_pdf or known_ixbrl)
                    or source.raw_value is None or source.value is None):
                unresolved = True
        if unresolved:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Unit/scale or explicit upstream normalization provenance is missing or unsupported', details)
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'Declared units match; scale is zero or explicitly normalized by a supported upstream parser', details)


def financial_units_registry() -> RuleRegistry:
    """Compose the two monetary gates with all four completed financial rules, unchanged."""
    registry = RuleRegistry('financial-identity-grounding-period-scope-units-v1')
    for rule in (FinancialIdentityRule(), FinancialGroundingRule(), FinancialPeriodRule(),
                 FinancialScopeRule(), FinancialCurrencyRule(), FinancialUnitScaleRule()):
        registry.register(rule)
    return registry
