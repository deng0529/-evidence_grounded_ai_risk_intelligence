"""Cleanup preserves five latest real SQL views, checksums and immutable constraints."""
from datetime import UTC, datetime, timedelta
import json
from urllib.parse import urlsplit
import sqlite3

import pytest

from risk_intelligence.maintenance.retain_latest import COMPANIES, snapshot, plan, cleanup
from risk_intelligence.persistence.connection import open_sqlite, IntegrityError
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.accounts.mapping import FinancialMappingRegistry, MappingRule
from risk_intelligence.services.data_foundation import load_foundation, latest_saved_run


@pytest.fixture
def history(tmp_path):
    with open_sqlite() as db:
        migrate(db)
        storage = LocalStorage(tmp_path/'raw')
        registry=FinancialMappingRegistry('synthetic',tuple(MappingRule(source_concept='{urn:test}'+c,
            canonical_concept=c) for c in ('NET_ASSETS','TOTAL_ASSETS','CURRENT_ASSETS','CURRENT_LIABILITIES','INVENTORY')))
        for iteration in range(2):
            for number in COMPANIES:
                now=datetime(2026,10,3,tzinfo=UTC)+timedelta(minutes=iteration)
                def api(path):
                    name=urlsplit(path).path.rsplit('/',1)[1]
                    if name==number:
                        data={'company_number':number,'company_name':'SYNTHETIC'}
                    else:
                        items=[{'transaction_id':'filing','date':'2026-04-01','type':'AA','category':'accounts',
                            'links':{'document_metadata':'/document/doc'},'description_values':{'made_up_date':'2025-06-30'}}] if name=='filing-history' else []
                        data={'items':items,'start_index':0,'items_per_page':100,'total_results':len(items)}
                    return Response(path,json.dumps(data).encode(),200,now)
                prefix=f'foundation-{number}-{iteration}'
                CompaniesHouseIngestion(db,storage,CompaniesHouseClient(api),clock=lambda:now).ingest(number,now.date(),prefix+'-m2',force_refresh=True)
                class Documents:
                    def get(self,url,media_type='application/json'):
                        if media_type=='application/json':
                            content=b'{"resources":{"application/xhtml+xml":{}}}'
                        else:
                            content=f'''<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:x="http://www.xbrl.org/2003/instance"
                                xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:t="urn:test">
                                <x:context id="c"><x:entity><x:identifier scheme="test">{number}</x:identifier></x:entity>
                                <x:period><x:instant>2025-06-30</x:instant></x:period></x:context>
                                <x:unit id="GBP"><x:measure>iso:GBP</x:measure></x:unit>
                                '''.encode()+b''.join(f'<ix:nonFraction name="t:{concept}" contextRef="c" unitRef="GBP">{value}</ix:nonFraction>'.encode()
                                    for concept,value in (('NET_ASSETS',100),('TOTAL_ASSETS',1000),('CURRENT_ASSETS',200),('CURRENT_LIABILITIES',100),('INVENTORY',50)))+b'</html>'
                        return Response(url,content,200,now,media_type)
                AccountsIngestion(db,storage,Documents(),registry=registry).ingest(number,now.date(),prefix+'-m3',reporting_year=2025,force_refresh=True)
        yield db,storage,tmp_path


def test_cleanup_preserves_only_latest_five_pairs_and_readback(history):
    db,storage,tmp=history
    before={n:load_foundation(db,*latest_saved_run(db,n)) for n in COMPANIES}
    report=cleanup(db,storage,tmp/'backup',apply=True)
    assert report['applied'] and not report['pending_objects']
    assert report['r2_deleted']==report['old_objects']>0
    runs=db.query('SELECT processing_run_id FROM processing_run')
    assert len(runs)==10 and all('-1-m' in r['processing_run_id'] for r in runs)
    assert not db.query('PRAGMA foreign_key_check')
    for n in COMPANIES: assert load_foundation(db,*latest_saved_run(db,n))==before[n]
    # A second cleanup is idempotent and performs no physical deletion.
    second=cleanup(db,storage,tmp/'backup2',apply=True)
    assert not second['removed_rows'] and second['old_objects']==0
    with sqlite3.connect(tmp/'backup/before_cleanup.sqlite3') as saved:
        assert saved.execute('SELECT count(*) FROM processing_run').fetchone()[0]==20
        assert not saved.execute('PRAGMA foreign_key_check').fetchall()
    # Original immutability triggers must be restored after authorized maintenance.
    with pytest.raises(Exception): db.execute('DELETE FROM financial_fact_missing_reason')


def test_read_only_plan_never_deletes(history):
    db,storage,tmp=history
    before=snapshot(db)
    report=cleanup(db,storage,tmp/'not_created',apply=False)
    assert not report['applied'] and snapshot(db)==before and not (tmp/'not_created').exists()


def test_missing_pilot_refuses_deletion(history):
    db,storage,tmp=history
    # A missing required result is simulated by removing only its selection in a transaction.
    with db.transaction():
        db.execute("UPDATE processing_run SET status='FAILED' WHERE processing_run_id LIKE 'foundation-02251694-%-m3'")
    before=snapshot(db)
    with pytest.raises(IntegrityError,match='No latest saved'): cleanup(db,storage,tmp/'backup',apply=True)
    assert snapshot(db)==before and not (tmp/'backup').exists()


def test_missing_retained_object_stops_before_database_deletion(history):
    db,storage,tmp=history
    before=snapshot(db)
    action=plan(db,before)
    removed=set(action['removed']['raw_evidence'])
    kept=next(row for row in before['rows']['raw_evidence'] if row['__maintenance_rowid'] not in removed)
    (storage.root/kept['object_path']).unlink()
    with pytest.raises(Exception): cleanup(db,storage,tmp/'backup',apply=True)
    assert snapshot(db)==before
    assert (tmp/'backup/before_cleanup.sqlite3').is_file()


def test_object_delete_failure_is_reported_without_losing_backup(history):
    db,storage,tmp=history
    class FailedCloud:
        _bucket='synthetic'
        def read(self,key): return storage.read(key)
        class Client:
            def delete_object(self,**kwargs): raise OSError('synthetic transport failure')
        _client=Client()
    report=cleanup(db,FailedCloud(),tmp/'backup',apply=True)
    assert report['applied'] and report['r2_deleted']==0
    assert len(report['pending_objects'])==report['old_objects']>0
    assert len(db.query('SELECT processing_run_id FROM processing_run'))==10
    for key in report['pending_objects']:
        assert (storage.root/key).is_file() and (tmp/'backup/objects'/key).is_file()
