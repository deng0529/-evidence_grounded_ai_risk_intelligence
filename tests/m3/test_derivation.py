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


def test_frc_balance_sheet_subtotals_derive_current_liabilities_and_total_assets(ixbrl: bytes) -> None:
    from risk_intelligence.ingestion.accounts.derivation import derive_balance_sheet_subtotals
    base = extract_ixbrl(ixbrl, 'document', 'ZZ000003').facts[0]
    ns = '{http://xbrl.frc.org.uk/fr/2025-01-01/core}'
    def source(identity: str, local: str, value: str) -> SourceFinancialFact:
        return SourceFinancialFact(**(base.model_dump() | {
            'source_fact_id': identity, 'evidence_id': 'e-' + identity,
            'source_concept': ns + local, 'value': Decimal(value), 'dimensions': (),
        }))
    facts = (source('ca','CurrentAssets','8218053'),
             source('nca','NetCurrentAssetsLiabilities','6390856'),
             source('talcl','TotalAssetsLessCurrentLiabilities','6575329'))
    derived = derive_balance_sheet_subtotals(facts, company_id='c', source_id='s', run_id='r', mapping_version='v2')
    by_concept = {fact.canonical_concept: (fact, ids, rule) for fact, ids, rule in derived}
    assert by_concept['CURRENT_LIABILITIES'][0].value_numeric == Decimal('1827197')
    assert by_concept['CURRENT_LIABILITIES'][1] == ('ca','nca')
    assert by_concept['TOTAL_ASSETS'][0].value_numeric == Decimal('8402526')
    assert by_concept['TOTAL_ASSETS'][1] == ('talcl','ca','nca')
    assert all(item[0].extraction_method.value == 'DERIVED' for item in derived)


def test_balance_sheet_subtotals_fail_closed_for_unreviewed_namespace_or_dimensions(ixbrl: bytes) -> None:
    from risk_intelligence.ingestion.accounts.derivation import derive_balance_sheet_subtotals
    base = extract_ixbrl(ixbrl, 'document', 'ZZ000003').facts[0]
    ns = '{http://xbrl.frc.org.uk/fr/2025-01-01/core}'
    ca = SourceFinancialFact(**(base.model_dump() | {'source_fact_id':'ca','evidence_id':'e-ca',
        'source_concept':ns+'CurrentAssets','value':Decimal('10'),'dimensions':()}))
    nca = SourceFinancialFact(**(base.model_dump() | {'source_fact_id':'nca','evidence_id':'e-nca',
        'source_concept':'{urn:unreviewed}NetCurrentAssetsLiabilities','value':Decimal('4'),'dimensions':()}))
    assert derive_balance_sheet_subtotals((ca,nca), company_id='c', source_id='s', run_id='r', mapping_version='v2') == ()
    nca = nca.model_copy(update={'source_concept':ns+'NetCurrentAssetsLiabilities', 'dimensions':(('x','y'),)})
    assert derive_balance_sheet_subtotals((ca,nca), company_id='c', source_id='s', run_id='r', mapping_version='v2') == ()
