"""Consistency checks for existing financial normalizations; no new normalization."""

from typing import Literal

from risk_intelligence.domain.common import Contract, Text
from risk_intelligence.domain.enums import AdmissibilityReason, ValidationRole, ValidationStatus
from risk_intelligence.domain.facts import TextValue
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from risk_intelligence.ingestion.accounts.mapping import default_registry
from risk_intelligence.ingestion.accounts.models import CONCEPTS, SemanticSupport, SourceFinancialFact
from .engine import RuleRegistry
from .financial import FinancialGroundingRule, FinancialIdentityRule, _outcome, _provenance
from .financial_period import FinancialPeriodRule
from .financial_scope import FinancialScopeRule
from .financial_units import FinancialCurrencyRule, FinancialUnitScaleRule


class SemanticAdmission(Contract):
    """Relevant existing financial_interpretation ledger fields, without artifact reads."""

    interpretation_id: Text
    canonical_fact_id: Text | None
    source_fact_id: Text | None
    document_id: Text
    target_concept: Text
    method: Text
    status: Text
    rule_version: Text
    artifact_raw_id: Text
    llm_artifact_raw_id: Text | None = None


class FinancialSemanticEvidence(Contract):
    """Structured source/lineage and optional M4.0a support for one normalization.

    canonical_fact_id and mapping_version come from the observation lineage;
    method/admission come from its interpretation when present. No declaration
    of successful admission substitutes for the supporting source context.
    """

    version: Literal['financial-semantic-evidence-v1'] = 'financial-semantic-evidence-v1'
    canonical_fact_id: Text
    source: SourceFinancialFact | None = None
    method: Text | None = None
    mapping_version: Text | None = None
    admission: SemanticAdmission | None = None
    support: SemanticSupport | None = None

    def attach(self, context: AnalyticalInput) -> AnalyticalInput:
        """Append typed provenance using the existing M4.1 JSON field boundary."""
        fields = context.fields + (ValidationField(name='financial_semantic_evidence',
            value=TextValue(value=self.model_dump_json())),)
        return AnalyticalInput(**(context.model_dump() | {'fields': fields}))


def _normalized(text: str) -> str:
    return ' '.join(text.lower().split())


def _context_supports(source: SourceFinancialFact, support: SemanticSupport, target: str) -> bool:
    """Recognize only the existing versioned M3 contextual-normalization patterns.

    This is a predicate on a claimed target, not a mapper: no fact, candidate,
    proposal or replacement concept is produced. Unsupported patterns stay open.
    """
    if (source.parser_version not in ('financial-statement-structure-v3', 'financial-statement-structure-v4')
            or source.source_concept != 'structure:context-row' or source.source_label is None):
        return False
    context = support.context
    if _normalized(context.statement) not in ('company balance sheet', 'company statement of financial position'):
        return False
    label, section, quote = map(_normalized, (source.source_label, context.section, context.supporting_text))
    if label not in quote or section not in quote:
        return False
    section_targets = {'current assets': 'CURRENT_ASSETS', 'current liabilities': 'CURRENT_LIABILITIES',
        'inventories': 'INVENTORY', 'net assets': 'NET_ASSETS', 'total assets': 'TOTAL_ASSETS',
        'total interest-bearing debt': 'INTEREST_BEARING_DEBT'}
    return ((label == 'amounts falling due within one year' and section == 'creditors' and target == 'CURRENT_LIABILITIES')
            or (label in ('total', 'aggregate', 'carrying amount') and section_targets.get(section) == target))


class FinancialSemanticConsistencyRule:
    """Validate an already-normalized concept against linked versioned provenance."""

    @property
    def definition(self) -> RuleDefinition:
        """Mandatory semantic gate, with no independent validation-strength candidate."""
        return RuleDefinition(rule_id='financial.semantic_consistency', rule_version='v1',
            applies_to=('FINANCIAL_FACT',),
            required_inputs=('financial_provenance', 'financial_semantic_evidence'), role=ValidationRole.HARD_FAIL)

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Preserve original meaning/provenance; missing semantic support is never reconstructed."""
        records = _provenance(context)
        field = next(f for f in context.fields if f.name == 'financial_semantic_evidence')
        if not isinstance(field.value, TextValue) or field.value.value is None:
            raise ValueError('Financial semantic evidence requires a typed JSON text payload')
        semantic = FinancialSemanticEvidence.model_validate_json(field.value.value)
        source, fact = semantic.source, records.fact
        details = (ValidationField(name='canonical_concept', value=TextValue(value=fact.canonical_concept)),
            ValidationField(name='source_label', value=TextValue(value=source.source_label if source else None)),
            ValidationField(name='normalization_method', value=TextValue(value=semantic.method)),
            ValidationField(name='semantic_provenance', value=TextValue(value=semantic.model_dump_json())))

        def unresolved(reason: str) -> RuleOutcome:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE, reason, details)

        def contradiction(reason: str) -> RuleOutcome:
            # M4.1's existing identity exclusion covers a contradictory concept
            # identity. No new failure taxonomy is introduced in this bounded step.
            return _outcome(self.definition, context, ValidationStatus.FAIL, reason, details,
                            AdmissibilityReason.IDENTITY_FAILURE)

        if semantic.method == 'DETERMINISTIC_DERIVATION':
            if semantic.canonical_fact_id != fact.financial_fact_id or semantic.source is not None:
                return unresolved('Derived semantic handoff is missing or ambiguously linked')
            # A method label alone cannot exempt a direct/mislabelled fact from
            # semantic validation. Only a linked, supported derivation target
            # may delegate to the mandatory derivation/completeness gates.
            from .financial_derivation import FinancialDerivationEvidence
            field = next((item for item in context.fields if item.name == 'financial_derivation_evidence'), None)
            if field is None or not isinstance(field.value, TextValue) or field.value.value is None:
                return unresolved('Derived semantics require structured derivation evidence')
            derivation = FinancialDerivationEvidence.model_validate_json(field.value.value)
            relationship = {'TOTAL_ASSETS': 'ASSET_SIDE', 'INTEREST_BEARING_DEBT': 'EXHAUSTIVE_INTEREST_BEARING'}.get(fact.canonical_concept)
            if (fact.extraction_method.value != 'DERIVED' or derivation.origin != 'DERIVED'
                    or derivation.canonical_fact_id != fact.financial_fact_id
                    or derivation.mapping_version != semantic.mapping_version
                    or not derivation.components or derivation.proof is None
                    or relationship is None or derivation.proof.relationship != relationship
                    or derivation.proof.target != fact.canonical_concept):
                return unresolved('Derived target lacks a matching supported semantic completeness contract')
            return _outcome(
                self.definition, context, ValidationStatus.NOT_APPLICABLE,
                'Derived target semantics are validated by structured derivation and completeness rules',
                details,
            )

        if (source is None or semantic.canonical_fact_id != fact.financial_fact_id
                or source.document_id != fact.document_id or source.evidence_id not in fact.evidence_ids):
            return unresolved('Normalization source/observation linkage is missing or ambiguous')
        if fact.source_concept is not None and fact.source_concept != source.source_concept:
            return contradiction('Canonical source concept contradicts its linked source observation')
        registry = default_registry()
        approved = [rule for rule in registry.rules
                    if rule.source_concept == source.source_concept and rule.dimensions == source.dimensions]
        if semantic.method == 'DETERMINISTIC_MAPPING':
            if semantic.mapping_version != registry.version or len(approved) != 1:
                return unresolved('Approved versioned mapping is absent or source meaning is ambiguous')
            if approved[0].canonical_concept != fact.canonical_concept:
                return contradiction('Approved source mapping contradicts the canonical concept')
        elif semantic.method == 'LLM_SEMANTIC':
            admission, support = semantic.admission, semantic.support
            if (admission is None or admission.status != 'AVAILABLE' or admission.method != 'LLM_SEMANTIC'
                    or admission.rule_version != 'financial-interpretation-v1'
                    or semantic.mapping_version != admission.rule_version):
                return unresolved('Accepted versioned semantic-normalization ledger is missing or unsupported')
            if (admission.canonical_fact_id != fact.financial_fact_id or admission.source_fact_id != source.source_fact_id
                    or admission.document_id != fact.document_id):
                return unresolved('Semantic admission is not linked to this source and canonical observation')
            if admission.target_concept != fact.canonical_concept:
                return contradiction('Accepted semantic target contradicts the canonical concept')
            if (support is None or support.interpretation_id != admission.interpretation_id
                    or support.context.source_fact_id != source.source_fact_id):
                return unresolved('Required structured semantic support is missing or belongs to another interpretation')
            targets = support.context.compatible_concepts
            if len(targets) != 1:
                return unresolved('Persisted semantic context does not identify one unambiguous compatible concept')
            if targets[0] != fact.canonical_concept:
                return contradiction('Persisted source context contradicts the canonical concept')
            if approved:
                if len(approved) != 1 or approved[0].canonical_concept != fact.canonical_concept:
                    return contradiction('Approved source meaning contradicts the accepted semantic target')
            elif not _context_supports(source, support, fact.canonical_concept):
                if any(_context_supports(source, support, other) for other in CONCEPTS if other != fact.canonical_concept):
                    return contradiction('Explicit statement/section meaning contradicts the canonical concept')
                return unresolved('Source label lacks sufficient supported statement/section context')
        else:
            return unresolved('Normalization method is missing or outside supported semantic-consistency checks')
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'Existing canonical concept is consistent with supported structured normalization provenance', details)


def financial_semantic_registry() -> RuleRegistry:
    """Compose only the seven completed financial consistency/admissibility rules."""
    registry = RuleRegistry('financial-core-consistency-v1')
    for rule in (FinancialIdentityRule(), FinancialGroundingRule(), FinancialPeriodRule(), FinancialScopeRule(),
                 FinancialCurrencyRule(), FinancialUnitScaleRule(), FinancialSemanticConsistencyRule()):
        registry.register(rule)
    return registry
