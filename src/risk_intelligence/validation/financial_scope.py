"""Financial analytical-scope gate using the existing M3 scope provenance contract."""

from typing import Literal

from risk_intelligence.domain.common import Contract
from risk_intelligence.domain.enums import AdmissibilityReason, ValidationRole, ValidationStatus
from risk_intelligence.domain.evidence import PdfLocator
from risk_intelligence.domain.facts import CodesValue, TextValue
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from .engine import RuleRegistry
from .financial import FinancialGroundingRule, FinancialIdentityRule, _outcome, _provenance
from .financial_period import FinancialPeriodRule


class FinancialScopeEvidence(Contract):
    """Explicit analytical scope and all supporting source observations.

    The requested analytical scope is supplied by the caller, never inferred
    from a company number or canonical concept. Missing source records and
    unresolved requested scope cannot establish compatibility.
    """

    version: Literal['financial-scope-evidence-v1'] = 'financial-scope-evidence-v1'
    analytical_scope: Literal['COMPANY', 'GROUP', 'UNRESOLVED', 'UNSPECIFIED'] | None = None
    source_facts: tuple[SourceFinancialFact, ...] | None = None

    def attach(self, context: AnalyticalInput) -> AnalyticalInput:
        """Append schema-validated scope records through the existing M4.1 field contract."""
        fields = context.fields + (ValidationField(name='financial_scope_evidence',
            value=TextValue(value=self.model_dump_json())),)
        return AnalyticalInput(**(context.model_dump() | {'fields': fields}))


class FinancialScopeRule:
    """Check scope only after matching source heading/page to its structured evidence.

    Conflicting/ambiguous metadata is inconclusive. An independently identifiable
    supporting observation with definite incompatible scope is a hard failure,
    even when another required observation is unresolved. No bytes are read.
    """

    @property
    def definition(self) -> RuleDefinition:
        """Versioned scope admissibility gate; never independent validation support."""
        return RuleDefinition(rule_id='financial.scope', rule_version='v1',
            applies_to=('FINANCIAL_FACT',),
            required_inputs=('financial_provenance', 'financial_scope_evidence'),
            role=ValidationRole.HARD_FAIL)

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Use SourceFinancialFact.source_scope without reinterpreting missing dimensions."""
        records = _provenance(context)
        field = next(f for f in context.fields if f.name == 'financial_scope_evidence')
        if not isinstance(field.value, TextValue) or field.value.value is None:
            raise ValueError('Financial scope evidence requires a typed JSON text payload')
        scope = FinancialScopeEvidence.model_validate_json(field.value.value)
        sources = sorted(scope.source_facts or (), key=lambda s: (s.source_fact_id, s.model_dump_json()))
        ordered = FinancialScopeEvidence(analytical_scope=scope.analytical_scope, source_facts=tuple(sources))
        details = (ValidationField(name='analytical_scope', value=TextValue(value=scope.analytical_scope)),
                   ValidationField(name='source_scope_evidence', value=TextValue(value=ordered.model_dump_json())))
        for index, source in enumerate(sources):
            details += (ValidationField(name=f'source_{index}_id', value=TextValue(value=source.source_fact_id)),
                        ValidationField(name=f'source_{index}_scope', value=TextValue(value=source.source_scope)))
        if scope.analytical_scope not in ('COMPANY', 'GROUP') or not sources:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Analytical scope or required source-scope evidence is unspecified', details)
        unresolved: list[str] = []
        incompatible: list[str] = []
        for source in sources:
            matches = [e for e in records.evidence or () if e.evidence_id == source.evidence_id]
            duplicate = sum(s.source_fact_id == source.source_fact_id for s in sources) != 1
            if (duplicate or len(matches) != 1 or source.evidence_id not in records.fact.evidence_ids
                    or source.document_id != records.fact.document_id):
                unresolved.append(source.source_fact_id)
                continue
            evidence = matches[0]
            locator = evidence.location
            if (evidence.source_id != records.fact.source_id or evidence.document_id != source.document_id
                    or not isinstance(locator, PdfLocator) or locator.page != source.page
                    or locator.section != source.statement_context
                    or locator.label != (source.source_label or source.source_concept)):
                unresolved.append(source.source_fact_id)
                continue
            observed = source.source_scope
            if observed == 'UNRESOLVED':
                unresolved.append(source.source_fact_id)
            elif observed != scope.analytical_scope:
                incompatible.append(source.source_fact_id)
        details += (ValidationField(name='incompatible_source_ids', value=CodesValue(value=tuple(sorted(set(incompatible))))),
                    ValidationField(name='unresolved_source_ids', value=CodesValue(value=tuple(sorted(set(unresolved))))))
        if incompatible:
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Grounded source scope is incompatible with the requested analytical scope', details,
                AdmissibilityReason.INCOMPATIBLE_SCOPE)
        if unresolved:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Source scope or its heading/locator provenance is unresolved, conflicting or incomplete', details)
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'All supplied grounded source scopes match the explicit analytical scope', details)


def financial_scope_registry() -> RuleRegistry:
    """Compose the scope gate with the three completed financial rules, unchanged."""
    registry = RuleRegistry('financial-identity-grounding-period-scope-v1')
    registry.register(FinancialIdentityRule())
    registry.register(FinancialGroundingRule())
    registry.register(FinancialPeriodRule())
    registry.register(FinancialScopeRule())
    return registry
