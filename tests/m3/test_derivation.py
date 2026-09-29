"""Complete, non-overlapping financing components only; no partial debt totals."""

from decimal import Decimal
from datetime import date

import pytest

from risk_intelligence.ingestion.accounts.derivation import derive_debt, COMPLETENESS_QUOTE
from risk_intelligence.ingestion.accounts.ixbrl import extract_ixbrl
from risk_intelligence.ingestion.accounts.models import DebtSchedule, SourceFinancialFact
from risk_intelligence.ingestion.companies_house.client import ParseError


def test_complete_debt_sum_and_reject_missing_overlapping_or_mixed_components(ixbrl: bytes) -> None:
    base = extract_ixbrl(ixbrl, 'document', 'ZZ000003').facts[0]
    facts = tuple(SourceFinancialFact(**(base.model_dump() | {
        'source_fact_id': f'component-{i}', 'evidence_id': f'e-{i}', 'source_label': label,
        'value': Decimal(value), 'page': 2})) for i, (label, value) in enumerate(
            [('bank loans', '100000.01'), ('finance lease liabilities', '20000.02')]))
    schedule = DebtSchedule(source_fact_ids=tuple(f.source_fact_id for f in facts),
                            completeness_quote=COMPLETENESS_QUOTE, page=2)
    result = derive_debt(schedule, facts, company_id='c', source_id='s', run_id='r', mapping_version='v1')
    assert result.value_numeric == Decimal('120000.03')
    assert result.extraction_method.value == 'DERIVED'
    assert result.evidence_ids == ('e-0','e-1')
    with pytest.raises(ParseError, match='Missing debt component'):
        derive_debt(schedule, facts[:1], company_id='c', source_id='s', run_id='r', mapping_version='v1')
    bad = DebtSchedule(source_fact_ids=('component-0','component-0'), completeness_quote=COMPLETENESS_QUOTE, page=2)
    with pytest.raises(ParseError, match='Repeated'):
        derive_debt(bad, facts, company_id='c', source_id='s', run_id='r', mapping_version='v1')
    bad = DebtSchedule(source_fact_ids=schedule.source_fact_ids, completeness_quote='Loans mentioned', page=2)
    with pytest.raises(ParseError, match='exhaustive'):
        derive_debt(bad, facts, company_id='c', source_id='s', run_id='r', mapping_version='v1')

    for update in ({'source_label':'trade creditors'}, {'dimensions':(('scope','GROUP'),)},
                   {'period':facts[1].period.model_copy(update={'period_end':date(2020,12,31)})}):
        mixed = (facts[0], facts[1].model_copy(update=update))
        with pytest.raises(ParseError):
            derive_debt(schedule, mixed, company_id='c', source_id='s', run_id='r', mapping_version='v1')
