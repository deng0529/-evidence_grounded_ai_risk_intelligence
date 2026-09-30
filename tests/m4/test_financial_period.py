"""Focused period consistency, exclusions and registry integration; no external I/O."""

from datetime import date

import pytest

from risk_intelligence.domain.enums import (
    AdmissibilityReason, AvailabilityStatus, EvidenceUse, PeriodType, ValidationStrength,
)
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.financial import FinancialGroundingRule, FinancialIdentityRule
from risk_intelligence.validation.financial_period import (
    FinancialPeriodEvidence, FinancialPeriodRule, financial_period_registry,
)
from risk_intelligence.validation.policy import classify_support
from test_financial_identity_grounding import provenance


@pytest.fixture
def source(provenance) -> SourceFinancialFact:
    fact = provenance.fact
    return SourceFinancialFact(source_fact_id='sf', document_id='d', evidence_id='e1',
        source_concept='pdf-label:net assets', value=fact.value_numeric,
        availability_status=fact.availability_status, currency=fact.currency, unit=fact.unit,
        context_ref='page-1:2025', entity_identifier=fact.company_number, entity_scheme='M2_DOCUMENT_LINEAGE',
        period=fact.period, period_role='CURRENT', extraction_method=fact.extraction_method,
        parser_version='pdf-table-v4', page=1)


def validate(provenance, sources):
    context = FinancialPeriodEvidence(source_facts=sources).attach(
        provenance.analytical_input('ZZ000003', date(2026, 9, 29)))
    report = ValidationEngine(financial_period_registry()).validate(context)
    return report, next(outcome for outcome in report.outcomes if outcome.rule_id == 'financial.period')


def test_matching_period_passes_with_evidence_and_no_strength(provenance, source) -> None:
    provenance = provenance.model_copy(update={'document': provenance.document.model_copy(
        update={'period_end': date(2025, 12, 31), 'filing_date': date(2026, 5, 1)})})
    report, outcome = validate(provenance, (source,))
    assert report.admissible and outcome.result.value == 'PASS'
    assert outcome.rule_version == 'v1' and outcome.evidence_ids == ('e1', 'e2')
    assert outcome.reason and {d.name for d in outcome.structured_details} == {
        'canonical_period', 'document_period_start', 'document_period_end', 'source_period_evidence'}
    assert outcome.validation_strength_candidate == ValidationStrength.NONE
    assert outcome.evidence_use == EvidenceUse.ADMISSION_ONLY and outcome.independence_group is None
    assert classify_support(report.outcomes, report.context.construction_evidence_ids).strength == ValidationStrength.NONE


@pytest.mark.parametrize('target', ['source', 'document'])
def test_definite_end_date_mismatch_propagates_hard_failure(provenance, source, target) -> None:
    if target == 'source':
        source = source.model_copy(update={'period': source.period.model_copy(update={'period_end': date(2024, 12, 31)})})
    else:
        provenance = provenance.model_copy(update={'document': provenance.document.model_copy(
            update={'period_end': date(2024, 12, 31)})})
    report, outcome = validate(provenance, (source,))
    assert outcome.result.value == 'FAIL' and outcome.hard_fail and not report.admissible
    assert outcome.failure_code == AdmissibilityReason.NON_COMPARABLE_PERIOD
    assert outcome.evidence_ids == ('e1', 'e2') and outcome.reason
    assert any(f.code == outcome.failure_code and f.reason == outcome.reason
               and f.evidence_ids == outcome.evidence_ids for f in report.failures)


@pytest.mark.parametrize('sources', [None, ()])
def test_missing_source_period_is_inconclusive(provenance, sources) -> None:
    _, outcome = validate(provenance, sources)
    assert outcome.result.value == 'INCONCLUSIVE' and outcome.hard_fail
    assert outcome.failure_code == AdmissibilityReason.MISSING_REQUIRED_EVIDENCE
    assert outcome.evidence_ids == ('e1', 'e2')


def test_missing_canonical_period_is_not_filled_from_source(provenance, source) -> None:
    fact = provenance.fact.model_copy(update={'period': None, 'value_numeric': None,
                                             'availability_status': AvailabilityStatus.NOT_DISCLOSED})
    _, outcome = validate(provenance.model_copy(update={'fact': fact}), (source,))
    assert outcome.result.value == 'INCONCLUSIVE'
    assert next(d.value.value for d in outcome.structured_details if d.name == 'canonical_period') is None


def test_ambiguous_source_period_records_remain_inconclusive(provenance, source) -> None:
    _, outcome = validate(provenance, (source, source))
    assert outcome.result.value == 'INCONCLUSIVE' and 'ambiguous' in outcome.reason


def test_ambiguous_period_diagnostics_are_independent_of_input_order(provenance, source) -> None:
    conflicting = source.model_copy(update={'period': source.period.model_copy(
        update={'period_end': date(2024, 12, 31)})})
    first = validate(provenance, (source, conflicting))[1]
    second = validate(provenance, (conflicting, source))[1]
    assert first.result.value == 'INCONCLUSIVE'
    assert first == second


def test_comparative_period_not_forced_to_current_document_end(provenance, source) -> None:
    provenance = provenance.model_copy(update={'document': provenance.document.model_copy(
        update={'period_end': date(2026, 12, 31)})})
    _, outcome = validate(provenance, (source.model_copy(update={'period_role': 'COMPARATIVE'}),))
    assert outcome.result.value == 'PASS'


@pytest.mark.parametrize('difference', ['type', 'start', 'length'])
def test_period_shape_mismatch_is_not_hidden_by_matching_end(provenance, source, difference) -> None:
    period = source.period.model_copy(update={'period_type': PeriodType.DURATION,
        'period_start': date(2025, 1, 1), 'period_length_days': 365})
    provenance = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'period': period})})
    changes = {'type': {'period_type': PeriodType.INSTANT, 'period_start': None},
               'start': {'period_start': date(2025, 2, 1)}, 'length': {'period_length_days': 364}}
    source = source.model_copy(update={'period': period.model_copy(update=changes[difference])})
    assert validate(provenance, (source,))[1].result.value == 'FAIL'


def test_optional_document_period_absence_does_not_invent_dates(provenance, source) -> None:
    _, outcome = validate(provenance, (source,))
    assert outcome.result.value == 'PASS'
    assert next(d.value.value for d in outcome.structured_details if d.name == 'document_period_end') is None


def test_registry_and_source_order_are_deterministic(provenance, source) -> None:
    second = source.model_copy(update={'source_fact_id': 'sf2', 'evidence_id': 'e2'})
    reports = []
    for sources, rules in (((source, second), (FinancialPeriodRule(), FinancialIdentityRule(), FinancialGroundingRule())),
                           ((second, source), (FinancialGroundingRule(), FinancialIdentityRule(), FinancialPeriodRule()))):
        context = FinancialPeriodEvidence(source_facts=sources).attach(
            provenance.analytical_input('ZZ000003', date(2026, 9, 29)))
        registry = RuleRegistry('test-period-v1')
        for rule in rules:
            registry.register(rule)
        reports.append(ValidationEngine(registry).validate(context))
    assert reports[0].outcomes == reports[1].outcomes
    assert [o.rule_id for o in reports[0].outcomes] == [
        'financial.evidence_grounding', 'financial.identity', 'financial.period']
