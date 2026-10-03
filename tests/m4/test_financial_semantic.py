"""Focused semantic consistency of existing normalized facts, with no provider I/O."""

from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import AdmissibilityReason, EvidenceUse, ValidationStrength
from risk_intelligence.ingestion.accounts.models import FinancialContext, SemanticSupport
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.financial_semantic import (
    FinancialSemanticConsistencyRule, FinancialSemanticEvidence, SemanticAdmission, financial_semantic_registry,
)
from risk_intelligence.validation.financial_units import FinancialMonetaryEvidence, MonetarySource
from risk_intelligence.validation.policy import classify_support
from test_financial_identity_grounding import provenance
from test_financial_period import source
from test_financial_scope import context, grounded


def analytical(provenance, source, semantic):
    base = FinancialMonetaryEvidence(sources=(MonetarySource.from_source(source),)).attach(
        context(provenance, (source,), 'COMPANY'))
    return semantic.attach(base)


def validate(provenance, source, semantic):
    report = ValidationEngine(financial_semantic_registry()).validate(analytical(provenance, source, semantic))
    return report, next(o for o in report.outcomes if o.rule_id == 'financial.semantic_consistency')


@pytest.fixture
def deterministic(provenance, source):
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    semantic = FinancialSemanticEvidence(canonical_fact_id='f', source=source,
        method='DETERMINISTIC_MAPPING', mapping_version='financial-concepts-v4')
    return provenance, source, semantic


@pytest.fixture
def semantic_llm(provenance, source):
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    source = source.model_copy(update={'source_label': 'Amounts falling due within one year',
        'source_concept': 'structure:context-row', 'parser_version': 'financial-statement-structure-v4'})
    reference = provenance.evidence[0]
    reference = reference.model_copy(update={'location': reference.location.model_copy(update={'label': source.source_label})})
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'canonical_concept': 'CURRENT_LIABILITIES'}),
        'evidence': (reference, provenance.evidence[1])})
    admission = SemanticAdmission(interpretation_id='i', canonical_fact_id='f', source_fact_id='sf',
        document_id='d', target_concept='CURRENT_LIABILITIES', method='LLM_SEMANTIC', status='AVAILABLE',
        rule_version='financial-interpretation-v1', artifact_raw_id='artifact', llm_artifact_raw_id='llm-artifact')
    support = SemanticSupport(interpretation_id='i', rationale='Explicit current maturity under Creditors',
        context=FinancialContext(source_fact_id='sf', statement='Company balance sheet', section='Creditors',
            supporting_text='Creditors\nAmounts falling due within one year', compatible_concepts=('CURRENT_LIABILITIES',)))
    semantic = FinancialSemanticEvidence(canonical_fact_id='f', source=source, method='LLM_SEMANTIC',
        mapping_version='financial-interpretation-v1', admission=admission, support=support)
    return provenance, source, semantic


@pytest.mark.parametrize('fixture', ['deterministic', 'semantic_llm'])
def test_supported_existing_normalization_passes_without_strength(request, fixture) -> None:
    provenance, source, semantic = request.getfixturevalue(fixture)
    report, outcome = validate(provenance, source, semantic)
    assert report.admissible and outcome.result.value == 'PASS' and outcome.rule_version == 'v1'
    assert outcome.evidence_ids == ('e1', 'e2') and outcome.reason
    details = {d.name: d.value.value for d in outcome.structured_details}
    assert details['source_label'] == source.source_label
    assert details['canonical_concept'] == provenance.fact.canonical_concept
    assert details['normalization_method'] == semantic.method
    assert 'mapping_version' in details['semantic_provenance']
    assert outcome.validation_strength_candidate == ValidationStrength.NONE
    assert outcome.evidence_use == EvidenceUse.ADMISSION_ONLY and outcome.independence_group is None
    assert classify_support(report.outcomes, report.context.construction_evidence_ids).strength == ValidationStrength.NONE


def test_approved_mapping_contradiction_propagates_hard_failure(deterministic) -> None:
    provenance, source, semantic = deterministic
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'canonical_concept': 'INVENTORY'})})
    report, outcome = validate(provenance, source, semantic)
    assert outcome.result.value == 'FAIL' and outcome.hard_fail and not report.admissible
    assert outcome.failure_code == AdmissibilityReason.IDENTITY_FAILURE
    assert outcome.evidence_ids == ('e1', 'e2') and 'contradicts' in outcome.reason
    assert any(f.code == outcome.failure_code and f.reason == outcome.reason and f.evidence_ids == outcome.evidence_ids
               for f in report.failures)


def test_llm_missing_structured_support_is_inconclusive(semantic_llm) -> None:
    provenance, source, semantic = semantic_llm
    _, outcome = validate(provenance, source, semantic.model_copy(update={'support': None}))
    assert outcome.result.value == 'INCONCLUSIVE' and outcome.hard_fail
    assert outcome.failure_code == AdmissibilityReason.MISSING_REQUIRED_EVIDENCE
    assert 'support' in outcome.reason and outcome.evidence_ids == ('e1', 'e2')


@pytest.mark.parametrize('value', [Decimal('0'), Decimal('1000'), Decimal('999999')])
def test_generic_label_and_numeric_value_never_supply_meaning(deterministic, value) -> None:
    provenance, source, semantic = deterministic
    source = source.model_copy(update={'source_label': 'Creditors', 'source_concept': 'pdf-label:creditors', 'value': value})
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'value_numeric': value})})
    assert validate(provenance, source, semantic.model_copy(update={'source': source}))[1].result.value == 'INCONCLUSIVE'


@pytest.mark.parametrize('change', [
    {'section': 'Unspecified'}, {'supporting_text': 'Amounts falling due within one year'},
    {'compatible_concepts': ('CURRENT_LIABILITIES', 'NET_ASSETS')},
])
def test_missing_or_ambiguous_context_does_not_get_guessed(semantic_llm, change) -> None:
    provenance, source, semantic = semantic_llm
    support = semantic.support.model_copy(update={'context': semantic.support.context.model_copy(update=change)})
    assert validate(provenance, source, semantic.model_copy(update={'support': support}))[1].result.value == 'INCONCLUSIVE'


def test_explicit_context_contradiction_fails(semantic_llm) -> None:
    provenance, source, semantic = semantic_llm
    source = source.model_copy(update={'source_label': 'Total'})
    support = semantic.support.model_copy(update={'context': semantic.support.context.model_copy(
        update={'section': 'Net assets', 'supporting_text': 'Net assets\nTotal'})})
    _, outcome = validate(provenance, source, semantic.model_copy(update={'source': source, 'support': support}))
    assert outcome.result.value == 'FAIL' and outcome.failure_code == AdmissibilityReason.IDENTITY_FAILURE


@pytest.mark.parametrize('change', [{'status': 'VALIDATION_FAILED'}, {'rule_version': 'unknown'}, {'source_fact_id': 'other'}])
def test_unsupported_or_unlinked_admission_is_inconclusive(semantic_llm, change) -> None:
    provenance, source, semantic = semantic_llm
    admission = semantic.admission.model_copy(update=change)
    assert validate(provenance, source, semantic.model_copy(update={'admission': admission}))[1].result.value == 'INCONCLUSIVE'


def test_support_for_different_interpretation_is_not_reused(semantic_llm) -> None:
    provenance, source, semantic = semantic_llm
    support = semantic.support.model_copy(update={'interpretation_id': 'other'})
    assert validate(provenance, source, semantic.model_copy(update={'support': support}))[1].result.value == 'INCONCLUSIVE'


def test_unknown_mapping_version_is_not_reinterpreted(deterministic) -> None:
    provenance, source, semantic = deterministic
    assert validate(provenance, source, semantic.model_copy(update={'mapping_version': 'unknown'}))[1].result.value == 'INCONCLUSIVE'


def test_registry_order_is_deterministic(deterministic) -> None:
    provenance, source, semantic = deterministic
    rules = financial_semantic_registry().applicable('FINANCIAL_FACT')
    reports = []
    for ordering in (rules, tuple(reversed(rules))):
        registry = RuleRegistry('test-semantic-v1')
        for rule in ordering:
            registry.register(rule)
        reports.append(ValidationEngine(registry).validate(analytical(provenance, source, semantic)))
    assert reports[0] == reports[1]
    assert [o.rule_id for o in reports[0].outcomes] == ['financial.currency', 'financial.evidence_grounding',
        'financial.identity', 'financial.period', 'financial.scope', 'financial.semantic_consistency', 'financial.unit_scale']


def test_derived_method_label_cannot_bypass_required_semantic_evidence(deterministic):
    provenance, source, semantic = deterministic
    semantic = semantic.model_copy(update={"method": "DETERMINISTIC_DERIVATION", "source": None})
    report, outcome = validate(provenance, source, semantic)
    assert not report.admissible
    assert outcome.result.value == "INCONCLUSIVE"
    assert "structured derivation evidence" in outcome.reason
