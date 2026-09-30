"""Focused structured scope checks; existing M4 offline fixture prohibits network I/O."""

from datetime import date
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import AdmissibilityReason, EvidenceUse, ValidationStrength
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.financial import FinancialGroundingRule, FinancialIdentityRule
from risk_intelligence.validation.financial_period import FinancialPeriodEvidence, FinancialPeriodRule
from risk_intelligence.validation.financial_scope import FinancialScopeEvidence, FinancialScopeRule, financial_scope_registry
from risk_intelligence.validation.policy import classify_support
from test_financial_identity_grounding import provenance
from test_financial_period import source


def grounded(provenance, source, heading):
    """Supply matching source and SQL evidence context, not an asserted scope result."""
    dimensions = (('pdf:entity-scope', 'GROUP'),) if heading and heading.startswith(('Group', 'Consolidated')) else ()
    source = source.model_copy(update={'statement_context': heading, 'source_label': 'Net assets', 'dimensions': dimensions})
    reference = provenance.evidence[0]
    reference = reference.model_copy(update={'location': reference.location.model_copy(
        update={'section': heading, 'label': 'Net assets'})})
    return provenance.model_copy(update={'evidence': (reference, provenance.evidence[1])}), source


def context(provenance, sources, target):
    base = provenance.analytical_input('ZZ000003', date(2026, 9, 30))
    base = FinancialPeriodEvidence(source_facts=sources).attach(base)
    return FinancialScopeEvidence(analytical_scope=target, source_facts=sources).attach(base)


def validate(provenance, sources, target):
    report = ValidationEngine(financial_scope_registry()).validate(context(provenance, sources, target))
    return report, next(o for o in report.outcomes if o.rule_id == 'financial.scope')


@pytest.mark.parametrize('heading,target', [
    ('Company balance sheet', 'COMPANY'), ('Company statement of financial position', 'COMPANY'),
    ('Group balance sheet', 'GROUP'), ('Consolidated balance sheet', 'GROUP'),
])
def test_compatible_explicit_scope_passes_without_strength(provenance, source, heading, target) -> None:
    provenance, source = grounded(provenance, source, heading)
    report, outcome = validate(provenance, (source,), target)
    assert report.admissible and outcome.result.value == 'PASS' and not outcome.hard_fail
    assert outcome.evidence_ids == ('e1', 'e2') and outcome.reason and outcome.structured_details
    assert outcome.rule_version == 'v1' and outcome.validation_strength_candidate == ValidationStrength.NONE
    assert outcome.evidence_use == EvidenceUse.ADMISSION_ONLY and outcome.independence_group is None
    assert classify_support(report.outcomes, report.context.construction_evidence_ids).strength == ValidationStrength.NONE


@pytest.mark.parametrize('heading,target', [('Company balance sheet', 'GROUP'), ('Group balance sheet', 'COMPANY')])
def test_definite_mismatch_propagates_typed_hard_failure(provenance, source, heading, target) -> None:
    provenance, source = grounded(provenance, source, heading)
    report, outcome = validate(provenance, (source,), target)
    assert outcome.result.value == 'FAIL' and outcome.hard_fail and not report.admissible
    assert outcome.failure_code == AdmissibilityReason.INCOMPATIBLE_SCOPE
    assert outcome.evidence_ids == ('e1', 'e2') and 'incompatible' in outcome.reason
    assert any(f.code == outcome.failure_code and f.reason == outcome.reason
               and f.evidence_ids == outcome.evidence_ids for f in report.failures)


@pytest.mark.parametrize('heading', [None, 'Balance Sheet', 'Statement of financial position',
    'Company and Group balance sheet', 'Company balance sheet\nGroup balance sheet'])
def test_unresolved_and_conflicting_headings_are_inconclusive(provenance, source, heading) -> None:
    provenance, source = grounded(provenance, source, heading)
    _, outcome = validate(provenance, (source,), 'COMPANY')
    assert outcome.result.value == 'INCONCLUSIVE' and outcome.hard_fail
    assert outcome.failure_code == AdmissibilityReason.MISSING_REQUIRED_EVIDENCE
    assert outcome.evidence_ids == ('e1', 'e2') and 'unresolved' in outcome.reason


@pytest.mark.parametrize('target', [None, 'UNRESOLVED', 'UNSPECIFIED'])
def test_requested_scope_is_never_assumed(provenance, source, target) -> None:
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    assert validate(provenance, (source,), target)[1].result.value == 'INCONCLUSIVE'


@pytest.mark.parametrize('change', [
    {'section': 'Group balance sheet'}, {'page': 2}, {'label': 'Different row'},
])
def test_conflicting_locator_does_not_support_a_scope(provenance, source, change) -> None:
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    evidence = provenance.evidence[0]
    evidence = evidence.model_copy(update={'location': evidence.location.model_copy(update=change)})
    provenance = provenance.model_copy(update={'evidence': (evidence, provenance.evidence[1])})
    assert validate(provenance, (source,), 'COMPANY')[1].result.value == 'INCONCLUSIVE'


def test_admitted_value_concept_and_empty_dimensions_do_not_supply_scope(provenance, source) -> None:
    provenance, source = grounded(provenance, source, 'Balance sheet')
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(
        update={'canonical_concept': 'COMPANY', 'value_numeric': Decimal('999')})})
    assert not source.dimensions and source.availability_status.value == 'AVAILABLE'
    assert validate(provenance, (source,), 'COMPANY')[1].result.value == 'INCONCLUSIVE'


def test_unknown_version_and_duplicate_records_are_inconclusive(provenance, source) -> None:
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    unknown = source.model_copy(update={'parser_version': 'unrecognized'})
    assert validate(provenance, (unknown,), 'COMPANY')[1].result.value == 'INCONCLUSIVE'
    assert validate(provenance, (source, source), 'COMPANY')[1].result.value == 'INCONCLUSIVE'


def test_legacy_explicit_group_dimension_is_respected(provenance, source) -> None:
    provenance, source = grounded(provenance, source, None)
    source = source.model_copy(update={'parser_version': 'pdf-table-v3', 'dimensions': (('pdf:entity-scope', 'GROUP'),)})
    assert validate(provenance, (source,), 'GROUP')[1].result.value == 'PASS'
    assert validate(provenance, (source,), 'COMPANY')[1].result.value == 'FAIL'


def test_registry_order_and_definite_incompatibility_are_order_independent(provenance, source) -> None:
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    group = source.model_copy(update={'source_fact_id': 'group', 'evidence_id': 'e2',
        'statement_context': 'Group balance sheet', 'dimensions': (('pdf:entity-scope', 'GROUP'),)})
    reference = provenance.evidence[1].model_copy(update={'location': provenance.evidence[0].location.model_copy(
        update={'section': 'Group balance sheet'})})
    provenance = provenance.model_copy(update={'evidence': (provenance.evidence[0], reference)})
    reports = []
    for sources, rules in (((source, group), (FinancialScopeRule(), FinancialPeriodRule(), FinancialIdentityRule(), FinancialGroundingRule())),
        ((group, source), (FinancialGroundingRule(), FinancialIdentityRule(), FinancialPeriodRule(), FinancialScopeRule()))):
        registry = RuleRegistry('test-financial-scope-v1')
        for rule in rules:
            registry.register(rule)
        reports.append(ValidationEngine(registry).validate(context(provenance, sources, 'COMPANY')))
    assert reports[0].outcomes == reports[1].outcomes
    assert [o.rule_id for o in reports[0].outcomes] == [
        'financial.evidence_grounding', 'financial.identity', 'financial.period', 'financial.scope']
    assert reports[0].outcomes[-1].result.value == 'FAIL'
