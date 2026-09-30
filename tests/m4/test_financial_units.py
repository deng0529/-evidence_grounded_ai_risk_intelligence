"""Focused explicit currency, unit/scale and financial-registry integration checks."""

from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import AdmissibilityReason, EvidenceUse, ValidationStrength
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.financial import FinancialGroundingRule, FinancialIdentityRule
from risk_intelligence.validation.financial_period import FinancialPeriodRule
from risk_intelligence.validation.financial_scope import FinancialScopeRule
from risk_intelligence.validation.financial_units import (
    FinancialCurrencyRule, FinancialMonetaryEvidence, FinancialUnitScaleRule, MonetarySource,
    financial_units_registry,
)
from risk_intelligence.validation.policy import classify_support
from test_financial_identity_grounding import provenance
from test_financial_period import source
from test_financial_scope import context, grounded


def validate(provenance, source, changes=None):
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    monetary = MonetarySource.from_source(source).model_copy(update=changes or {})
    analytical = FinancialMonetaryEvidence(sources=(monetary,)).attach(context(provenance, (source,), 'COMPANY'))
    report = ValidationEngine(financial_units_registry()).validate(analytical)
    return report, {o.rule_id: o for o in report.outcomes}


def test_explicit_currency_unit_and_zero_scale_pass_without_strength(provenance, source) -> None:
    report, outcomes = validate(provenance, source)
    assert report.admissible
    for identity in ('financial.currency', 'financial.unit_scale'):
        item = outcomes[identity]
        assert item.result.value == 'PASS' and not item.hard_fail and item.rule_version == 'v1'
        assert item.evidence_ids == ('e1', 'e2') and item.reason and item.structured_details
        assert item.validation_strength_candidate == ValidationStrength.NONE
        assert item.evidence_use == EvidenceUse.ADMISSION_ONLY and item.independence_group is None
    assert classify_support(report.outcomes, report.context.construction_evidence_ids).strength == ValidationStrength.NONE


@pytest.mark.parametrize('identity,changes', [
    ('financial.currency', {'currency': 'USD'}),
    ('financial.unit_scale', {'unit': 'GBP thousands'}),
    ('financial.unit_scale', {'scale': 4}),
    ('financial.unit_scale', {'scale': 19, 'parser_version': 'ixbrl-monetary-v1'}),
])
def test_definite_mismatch_propagates_typed_failure(provenance, source, identity, changes) -> None:
    report, outcomes = validate(provenance, source, changes)
    item = outcomes[identity]
    assert item.result.value == 'FAIL' and item.hard_fail and not report.admissible
    assert item.failure_code == AdmissibilityReason.INCOMPATIBLE_UNIT_CURRENCY
    assert item.evidence_ids == ('e1', 'e2') and item.reason and item.structured_details
    assert any(f.code == item.failure_code and f.reason == item.reason and f.evidence_ids == item.evidence_ids
               for f in report.failures)


@pytest.mark.parametrize('currency', [None, 'GBP/USD', '£'])
def test_missing_or_ambiguous_source_currency_never_defaults_to_gbp(provenance, source, currency) -> None:
    _, outcomes = validate(provenance, source, {'currency': currency})
    assert provenance.fact.company_number == 'ZZ000003'
    assert outcomes['financial.currency'].result.value == 'INCONCLUSIVE'
    assert outcomes['financial.currency'].failure_code == AdmissibilityReason.MISSING_REQUIRED_EVIDENCE


def test_canonical_currency_is_not_filled_from_source(provenance, source) -> None:
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'currency': None})})
    assert validate(provenance, source)[1]['financial.currency'].result.value == 'INCONCLUSIVE'


@pytest.mark.parametrize('changes', [
    {'unit': None}, {'unit': 'GBP or thousands'}, {'scale': None},
    {'scale': 3, 'parser_version': None, 'raw_value': '10'},
    {'scale': 3, 'parser_version': 'unrecognized', 'raw_value': '10'},
    {'scale': 3, 'raw_value': None}, {'scale': 3, 'raw_value': '10', 'value': None},
])
def test_missing_or_ambiguous_unit_scale_provenance_is_inconclusive(provenance, source, changes) -> None:
    _, outcomes = validate(provenance, source, changes)
    item = outcomes['financial.unit_scale']
    assert item.result.value == 'INCONCLUSIVE' and item.hard_fail
    assert item.evidence_ids == ('e1', 'e2') and item.reason


@pytest.mark.parametrize('scale,version,raw,value', [
    (3, 'pdf-table-v4', '10', Decimal('10000')),
    (-2, 'ixbrl-monetary-v1', '1000', Decimal('10')),
])
def test_explicit_upstream_normalization_is_accepted_without_rescaling(provenance, source, scale, version, raw, value) -> None:
    _, outcomes = validate(provenance, source, {'scale': scale, 'parser_version': version, 'raw_value': raw, 'value': value})
    assert outcomes['financial.unit_scale'].result.value == 'PASS'
    assert provenance.fact.value_numeric == Decimal('10')  # Validation never changes the fact.


@pytest.mark.parametrize('value', [Decimal('0'), Decimal('1000'), Decimal('1000000000')])
def test_numeric_magnitude_cannot_supply_missing_scale(provenance, source, value) -> None:
    _, outcomes = validate(provenance, source, {'scale': None, 'value': value})
    assert outcomes['financial.unit_scale'].result.value == 'INCONCLUSIVE'


def test_thousands_are_not_reinterpreted_as_single_pounds(provenance, source) -> None:
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'unit': '£1'})})
    _, outcomes = validate(provenance, source, {'unit': '£000', 'scale': 0, 'parser_version': None})
    assert outcomes['financial.unit_scale'].result.value == 'FAIL'


def test_explicit_non_gbp_currency_is_not_overridden_by_company(provenance, source) -> None:
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'currency': 'EUR', 'unit': 'EUR'})})
    _, outcomes = validate(provenance, source, {'currency': 'EUR', 'unit': 'EUR', 'parser_version': 'ixbrl-monetary-v1'})
    assert outcomes['financial.currency'].result.value == 'PASS'
    assert outcomes['financial.unit_scale'].result.value == 'PASS'


def test_duplicate_monetary_provenance_is_ambiguous(provenance, source) -> None:
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    record = MonetarySource.from_source(source)
    analytical = FinancialMonetaryEvidence(sources=(record, record)).attach(context(provenance, (source,), 'COMPANY'))
    report = ValidationEngine(financial_units_registry()).validate(analytical)
    assert all(o.result.value == 'INCONCLUSIVE' for o in report.outcomes
               if o.rule_id in ('financial.currency', 'financial.unit_scale'))


def test_registry_and_source_order_are_deterministic(provenance, source) -> None:
    provenance, source = grounded(provenance, source, 'Company balance sheet')
    first = MonetarySource.from_source(source)
    second = first.model_copy(update={'source_fact_id': 'sf2', 'evidence_id': 'e2'})
    rules = (FinancialUnitScaleRule(), FinancialScopeRule(), FinancialPeriodRule(),
             FinancialIdentityRule(), FinancialGroundingRule(), FinancialCurrencyRule())
    reports = []
    for sources, ordering in (((first, second), rules), ((second, first), tuple(reversed(rules)))):
        registry = RuleRegistry('test-monetary-v1')
        for rule in ordering:
            registry.register(rule)
        analytical = FinancialMonetaryEvidence(sources=sources).attach(context(provenance, (source,), 'COMPANY'))
        reports.append(ValidationEngine(registry).validate(analytical))
    assert reports[0].outcomes == reports[1].outcomes
    assert [o.rule_id for o in reports[0].outcomes] == ['financial.currency', 'financial.evidence_grounding',
        'financial.identity', 'financial.period', 'financial.scope', 'financial.unit_scale']
