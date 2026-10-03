"""Regression for missing concepts without parser contexts and source-safe completion."""
from datetime import date
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import ReportingPeriod
from risk_intelligence.ingestion.accounts.ixbrl_semantic import TARGETS, admit, complete
from risk_intelligence.ingestion.accounts.llm import IxbrlSemanticCandidate
from risk_intelligence.ingestion.accounts.mapping import default_registry
from risk_intelligence.ingestion.accounts.models import ExtractionResult, SourceFinancialFact
from risk_intelligence.ingestion.companies_house.client import ParseError


PERIOD = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=date(2025, 6, 30),
                         comparability_status=ComparabilityStatus.REVIEW_REQUIRED)


def fact(concept):
    return SourceFinancialFact(source_fact_id=concept, document_id='doc', evidence_id='e-' + concept,
        source_concept='llm-semantic:' + concept, source_label=concept, raw_value='100',
        value=Decimal(100), availability_status=AvailabilityStatus.AVAILABLE, currency='GBP', unit='GBP',
        context_ref='current', entity_identifier='ZZ000003', entity_scheme='synthetic', period=PERIOD,
        period_role='CURRENT', extraction_method=ExtractionMethod.IXBRL_DIRECT, parser_version='synthetic')


def candidate(concept='INVENTORY', **updates):
    data = dict(concept=concept, kind='DIRECT', scope='COMPANY', support='SUPPORTED',
                label='Stocks', reporting_year=2025, currency='GBP', unit='GBP', raw_value='300', quote='Stocks 300')
    return IxbrlSemanticCandidate(**(data | updates))


def service(candidates=(), fail=False):
    requests, events = [], []
    original = '<html><body>Company balance sheet 2025 Stocks 300 Assets 400 Creditors 500</body></html>'

    class LLM:
        enabled, model, config_version = True, 'synthetic', 'v1'

        def extract_ixbrl(self, evidence):
            requests.append(json.loads(evidence))
            if fail:
                raise ParseError('Synthetic provider failure')
            return json.dumps({'status': 'completed', 'output': json.dumps({
                'candidates': [c.model_dump() for c in candidates]})}).encode()

    class Cache:
        def run(self, raw, run_id, stage, version, config, operation):
            return operation(original.encode()), False

    obj = SimpleNamespace(registry=default_registry(), llm=LLM(), cache=Cache(),
        evidence=SimpleNamespace(read=lambda _: original.encode()), _progress=lambda *args: events.append(args))
    return obj, requests, events


def test_two_of_five_without_contexts_sends_original_xhtml_and_merges_only_missing():
    obj, requests, events = service([candidate(), candidate('TOTAL_ASSETS', label='Assets', raw_value='400', quote='Assets 400'),
                                  candidate('CURRENT_LIABILITIES', label='Creditors', raw_value='500', quote='Creditors 500')])
    deterministic = ExtractionResult(facts=(fact('NET_ASSETS'), fact('CURRENT_ASSETS')), periods=(PERIOD,), complete=False)
    assert not deterministic.contexts
    result = complete(obj, SimpleNamespace(source_id='source', raw_evidence_id='raw', document_id='doc'),
                      'run', 'ZZ000003', deterministic, 2025, PERIOD.period_end)
    assert set(requests[0]['unresolved_concepts']) == {'TOTAL_ASSETS', 'CURRENT_LIABILITIES', 'INVENTORY'}
    assert requests[0]['original_ixbrl_xhtml'].startswith('<html>')
    assert requests[0]['preferred_reporting_year'] == 2025
    assert len(result.facts) == 5
    assert result.facts[:2] == deterministic.facts
    assert all(d.status == 'AVAILABLE' for d in result.fallback.decisions)
    assert any(e[0] == 'semantic_llm' for e in events)


def test_five_of_five_does_not_call_openai():
    obj, requests, events = service()
    deterministic = ExtractionResult(facts=tuple(fact(c) for c in TARGETS), periods=(PERIOD,), complete=True)
    assert complete(obj, SimpleNamespace(source_id='source'), 'run', 'ZZ000003', deterministic, 2025, None).facts == deterministic.facts
    assert not requests
    assert any(event[0] == 'semantic_not_needed' for event in events)


def test_empty_success_and_provider_failure_remain_distinct_and_preserve_facts():
    deterministic = ExtractionResult(facts=(fact('NET_ASSETS'),), periods=(PERIOD,), complete=False)
    raw = SimpleNamespace(source_id='source', raw_evidence_id='raw', document_id='doc')
    good, _, _ = service()
    success = complete(good, raw, 'run', 'ZZ000003', deterministic, 2025, None)
    failed, _, _ = service(fail=True)
    failure = complete(failed, raw, 'run', 'ZZ000003', deterministic, 2025, None)
    assert success.fallback.status == 'COMPLETE' and not any('TECHNICAL_EXTRACTION_FAILURE' in n for n in success.completeness_notes)
    assert failure.fallback.status == 'EXTRACTION_FAILED'
    assert any('TECHNICAL_EXTRACTION_FAILURE' in note for note in failure.completeness_notes)
    assert failure.facts == success.facts == deterministic.facts


@pytest.mark.parametrize('updates', [{'scope': 'GROUP'}, {'raw_value': '999'}, {'raw_value': '30'}, {'currency': 'USD'},
    {'concept': 'NET_ASSETS'}, {'kind': 'COMPONENT'}])
def test_conflicting_or_unlocated_candidates_are_rejected(updates):
    with pytest.raises(ParseError):
        admit(candidate(**updates), visible='Stocks 300', requested=('INVENTORY',), document_id='doc',
              number='ZZ000003', year=2025, period_end=PERIOD.period_end)


@pytest.mark.parametrize('number', ['05127466', 'SC137690', '08624397'])
@pytest.mark.parametrize('period_year', [2025, 2024])
def test_ixbrl_orchestration_persists_five_facts_and_unique_selection(tmp_path, number, period_year):
    """Synthetic filing exercises each demo identifier through real M2/M3/SQL boundaries."""
    from datetime import UTC, datetime
    from urllib.parse import urlsplit
    from risk_intelligence.ingestion.accounts.service import AccountsIngestion
    from risk_intelligence.ingestion.accounts.mapping import FinancialMappingRegistry, MappingRule
    from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response
    from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
    from risk_intelligence.persistence.connection import open_sqlite
    from risk_intelligence.persistence.migrations import migrate
    from risk_intelligence.storage.local import LocalStorage
    from risk_intelligence.services.data_foundation import load_foundation

    now = datetime(2026, 10, 3, tzinfo=UTC)
    content = f'''<html xmlns="http://www.w3.org/1999/xhtml"
        xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
        xmlns:x="http://www.xbrl.org/2003/instance" xmlns:iso="http://www.xbrl.org/2003/iso4217"
        xmlns:t="urn:synthetic:accounts"><x:context id="current"><x:entity>
        <x:identifier scheme="synthetic">{number}</x:identifier></x:entity>
        <x:period><x:instant>{period_year}-06-30</x:instant></x:period></x:context>
        <x:unit id="GBP"><x:measure>iso:GBP</x:measure></x:unit>
        <body>Company balance sheet {period_year}
        <ix:nonFraction name="t:NetAssets" contextRef="current" unitRef="GBP">100</ix:nonFraction>
        <ix:nonFraction name="t:CurrentAssets" contextRef="current" unitRef="GBP">200</ix:nonFraction>
        <p>Stocks 300</p><p>Assets 400</p><p>Creditors 500</p></body></html>'''.encode()

    def api(path):
        name = urlsplit(path).path.rsplit('/', 1)[1]
        if name == number:
            data = {'company_number': number, 'company_name': 'SYNTHETIC DEMO IDENTIFIER'}
        else:
            items = [{'transaction_id':f'synthetic-accounts-{i}','date':f'{2026-i}-04-01','category':'accounts',
                      'type':'AA','description_values':{'made_up_date':f'{period_year-i}-06-30'},
                      'links':{'document_metadata':f'/document/synthetic-{i}'}}
                     for i in range(3)] if name == 'filing-history' else []
            data = {'items':items,'start_index':0,'items_per_page':100,'total_results':len(items)}
        return Response(path, json.dumps(data).encode(), 200, now)

    class Documents:
        calls = []
        def get(self, url, media_type='application/json'):
            self.calls.append(media_type)
            body = json.dumps({'resources': {'application/xhtml+xml': {}, 'application/pdf': {}}}).encode() if media_type == 'application/json' else content
            assert media_type != 'application/pdf'
            return Response(url, body, 200, now, media_type)

    model, requests, _ = service([candidate(), candidate('TOTAL_ASSETS', label='Assets', raw_value='400', quote='Assets 400'),
                                candidate('CURRENT_LIABILITIES', label='Creditors', raw_value='500', quote='Creditors 500')])
    # Simulated AI reads the actual column even when the requested year differs.
    extract = model.llm.extract_ixbrl
    def actual_year(evidence):
        artifact = json.loads(extract(evidence))
        payload = json.loads(artifact['output'])
        for c in payload['candidates']: c['reporting_year'] = period_year
        artifact['output'] = json.dumps(payload)
        return json.dumps(artifact).encode()
    model.llm.extract_ixbrl = actual_year
    registry = FinancialMappingRegistry('synthetic-foundation-v1', default_registry().rules + (
        MappingRule(source_concept='{urn:synthetic:accounts}NetAssets', canonical_concept='NET_ASSETS'),
        MappingRule(source_concept='{urn:synthetic:accounts}CurrentAssets', canonical_concept='CURRENT_ASSETS')))
    with open_sqlite() as db:
        migrate(db)
        storage = LocalStorage(tmp_path/'raw')
        CompaniesHouseIngestion(db,storage,CompaniesHouseClient(api),clock=lambda:now).ingest(number,now.date(),'m2')
        docs = Documents()
        ingestion = AccountsIngestion(db,storage,docs,registry=registry,llm=model.llm)
        events = []
        run = ingestion.ingest(number,now.date(),'m3',reporting_year=2025,force_refresh=True,
                               progress=lambda *args:events.append(args))
        assert run.status.value == 'COMPLETE'
        assert len(requests) == 1
        assert len(docs.calls) == 2  # Do not search more filings after a different actual year.
        assert 'application/pdf' not in docs.calls
        assert len(db.query("SELECT * FROM accounts_run_selection WHERE processing_run_id='m3'")) == 1
        view = load_foundation(db,'m2','m3')
        rows = db.query("SELECT canonical_concept,availability_status FROM fact WHERE processing_run_id='m3' "
                        f"AND period_end='{period_year}-06-30' AND canonical_concept IN ('NET_ASSETS','TOTAL_ASSETS',"
                        "'CURRENT_ASSETS','CURRENT_LIABILITIES','INVENTORY')")
        assert len(rows) == 5 and all(row['availability_status']=='AVAILABLE' for row in rows)
        assert any(event=='canonical_persist_done' for event,_ in events)
        assert view is not None
        assert view.requested_year == 2025 and view.evidence_year == period_year
        assert all(f.value is not None for f in view.facts)
        from risk_intelligence.ingestion.accounts.coverage import coverage_rows
        breakdown = coverage_rows(view.documents)
        assert breakdown[0]['Resolved before OpenAI'] == '2/5'
        assert breakdown[0]['OpenAI asked to examine'] == '3/5'
        assert breakdown[0]['OpenAI recovered'] == '3/3'
        assert breakdown[0]['Final identified'] == '5/5'
        assert not db.query('PRAGMA foreign_key_check')
