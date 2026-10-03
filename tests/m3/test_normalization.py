"""Foundation v1 canonical financial cleaning is route-independent and provenance-safe."""

from datetime import date
from decimal import Decimal

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from risk_intelligence.ingestion.accounts.normalization import normalize_source_fact, normalize_canonical_fact


def source(*, label='creditors: amounts falling due within one year', raw='(10,583,194)',
           value=Decimal('-10583194'), scale=0, method=ExtractionMethod.LLM_OCR_TEXT):
    period = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=date(2025,12,31),
                             comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    return SourceFinancialFact(source_fact_id='s1', document_id='d1', evidence_id='e1',
        source_concept='llm-semantic:CURRENT_LIABILITIES', source_label=label, raw_value=raw,
        value=value, availability_status=AvailabilityStatus.AVAILABLE, currency='GBP', unit='GBP',
        context_ref='page-14', entity_identifier='01234567', entity_scheme='test', period=period,
        period_role='CURRENT', scale=scale, sign='-' if value < 0 else '+', extraction_method=method,
        parser_version='test', page=14, statement_context='balance sheet')


def canonical(value=Decimal('-10583194')):
    period = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=date(2025,12,31),
                             comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    return FinancialFact(financial_fact_id='f1', company_id='c1', company_number='01234567',
        canonical_concept='CURRENT_LIABILITIES', source_concept='llm-semantic:CURRENT_LIABILITIES',
        value_numeric=value, currency='GBP', unit='GBP', period=period, source_id='src', document_id='d1',
        evidence_ids=('e1',), extraction_method=ExtractionMethod.LLM_OCR_TEXT,
        availability_status=AvailabilityStatus.AVAILABLE, processing_run_id='r1')


def test_parenthesized_current_liability_becomes_positive_without_losing_raw_value():
    original = source()
    cleaned = normalize_source_fact(original)
    assert original.raw_value == cleaned.raw_value == '(10,583,194)'
    assert original.value == Decimal('-10583194')
    assert cleaned.value == Decimal('10583194')
    assert cleaned.transformation == 'balance-sheet-creditor-deduction'
    assert cleaned.sign == '+'


def test_scale_is_not_applied_twice():
    fact = source(label='current liabilities', raw='(10,583)', value=Decimal('-10583000'), scale=3)
    cleaned = normalize_source_fact(fact)
    assert cleaned.value == Decimal('10583000')
    assert cleaned.scale == 3
    assert cleaned.raw_value == '(10,583)'


def test_canonical_guard_versions_identity_only_when_value_changes():
    cleaned = normalize_canonical_fact(canonical(), source())
    assert cleaned.value_numeric == Decimal('10583194')
    assert cleaned.financial_fact_id != 'f1'
    unchanged = normalize_canonical_fact(canonical(Decimal('10583194')), normalize_source_fact(source()))
    assert unchanged.financial_fact_id == 'f1'


def test_normalization_does_not_infer_unrelated_negative_amount():
    fact = source(label='net assets', raw='(100)', value=Decimal('-100'))
    cleaned = normalize_source_fact(fact)
    assert cleaned.value == Decimal('-100')
