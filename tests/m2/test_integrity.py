"""M2 failure isolation, raw-first publication, migration and source integrity."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import libsql
import pytest

from risk_intelligence.domain.enums import ProcessingStatus, AvailabilityStatus
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response
from risk_intelligence.ingestion.companies_house.policy import FreshnessPolicy, Resource
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.ingestion.companies_house.parsing import observations
from risk_intelligence.persistence.connection import Database, PersistenceError, SqlValue
from risk_intelligence.persistence.migrations import migrate, MIGRATIONS_DIRECTORY
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum
from tests.m2.conftest import NOW, NUMBER, FakeAPI


def test_m1_database_upgrade_preserves_history_and_is_idempotent(tmp_path: Path) -> None:
    directory=tmp_path/'m1'; directory.mkdir()
    (directory/'001_storage.sql').write_bytes((MIGRATIONS_DIRECTORY/'001_storage.sql').read_bytes())
    with Database(libsql.connect(':memory:',isolation_level=None)) as database:
        migrate(database,directory,applied_at=NOW)
        original=database.query('SELECT * FROM schema_migration')
        migrate(database,applied_at=NOW)
        assert database.query('SELECT * FROM schema_migration ORDER BY version')[0]==original[0]
        before=database.query('SELECT * FROM schema_migration ORDER BY version')
        migrate(database)
        assert database.query('SELECT * FROM schema_migration ORDER BY version')==before
        assert len(before)==len(list(MIGRATIONS_DIRECTORY.glob('*.sql')))
        assert not database.query('PRAGMA foreign_key_check')


def test_sql_failure_after_verified_object_rolls_back_page_and_can_retry(
    database: Database, storage: LocalStorage, api: FakeAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service=CompaniesHouseIngestion(database,storage,CompaniesHouseClient(api),clock=lambda:NOW)
    service.ingest(NUMBER,NOW.date(),'baseline')
    company=service.companies.get_by_company_number(NUMBER)
    response=api('/company/'+NUMBER+'/officers?start_index=0&items_per_page=2')
    # Same processing context with a distinct logical response identity for this probe.
    source,raw=service._records(company,'baseline',Resource.OFFICERS,99,response)
    original=database.execute
    def fail_raw(sql: str, parameters: Sequence[SqlValue]=()) -> None:
        if sql.startswith('INSERT INTO raw_evidence'):
            assert checksum(storage.read(raw.object_path))==raw.checksum
            raise PersistenceError('synthetic SQL failure')
        original(sql,parameters)
    monkeypatch.setattr(database,'execute',fail_raw)
    with pytest.raises(PersistenceError):
        service.evidence.save(source,raw,response.body)
    assert service.evidence.sources.get(source.source_id) is None
    assert service.evidence.raw.get(raw.raw_evidence_id) is None
    assert storage.read(raw.object_path)==response.body
    monkeypatch.setattr(database,'execute',original)
    service.evidence.save(source,raw,response.body)
    service.evidence.save(source,raw,response.body)
    assert service.evidence.read(raw.raw_evidence_id)==response.body


@pytest.mark.parametrize('problem',['count-change','duplicate','order','stalled'])
def test_inconsistent_populations_are_never_marked_complete(
    database: Database,storage: LocalStorage,api: FakeAPI,problem: str,
) -> None:
    def request(path: str) -> Response:
        response=api(path)
        data=json.loads(response.body)
        if '/officers?' in path:
            if problem=='count-change' and data['start_index']==1:
                data['total_results']=3
            if problem=='duplicate':
                data['items'][0]['links']['self']='/synthetic/same'
            if problem=='stalled':
                data['items']=[]
        if problem=='order' and '/filing-history?' in path and data['start_index']==1:
            data['items'][0]['date']='2026-09-30'
        return replace(response,body=json.dumps(data).encode())
    result=CompaniesHouseIngestion(database,storage,CompaniesHouseClient(request),
                                  FreshnessPolicy(page_size=1),clock=lambda:NOW).ingest(NUMBER,NOW.date(),'bad-pages')
    resource=Resource.FILINGS if problem=='order' else Resource.OFFICERS
    snapshot=next(s for s in result.snapshots if s.resource==resource)
    assert not snapshot.complete and snapshot.availability_status==AvailabilityStatus.EXTRACTION_FAILED
    assert result.run.status==ProcessingStatus.PARTIAL


def test_cross_store_io_precedes_sql_and_bytes_are_not_reconstructed(
    database: Database,storage: LocalStorage,api: FakeAPI,monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies={}
    def request(path: str) -> Response:
        response=api(path)
        bodies[path]=response.body
        return response
    read,put=storage.read,storage.put
    def checked_read(path: str) -> bytes:
        assert not database.in_transaction
        return read(path)
    def checked_put(raw,content: bytes) -> None:
        assert not database.in_transaction
        put(raw,content)
    monkeypatch.setattr(storage,'read',checked_read)
    monkeypatch.setattr(storage,'put',checked_put)
    CompaniesHouseIngestion(database,storage,CompaniesHouseClient(request),clock=lambda:NOW).ingest(NUMBER,NOW.date(),'raw-first')
    for row in database.query('SELECT a.request_path,r.object_path FROM api_response a JOIN raw_evidence r USING(source_id)'):
        assert read(row['object_path'])==bodies[row['request_path']]


def test_later_profile_404_stops_subordinate_resources_but_preserves_prior_snapshot(
    database: Database,storage: LocalStorage,api: FakeAPI,
) -> None:
    service=CompaniesHouseIngestion(database,storage,CompaniesHouseClient(api),clock=lambda:api.now)
    service.ingest(NUMBER,NOW.date(),'first')
    rows=database.query('SELECT * FROM fact')
    api.now+=timedelta(days=2)
    api.calls.clear(); api.failures['profile:0']=404
    result=service.ingest(NUMBER,api.now.date(),'missing-profile')
    assert result.run.status==ProcessingStatus.FAILED
    assert len(api.calls)==1 and len(result.snapshots)==1
    assert database.query('SELECT * FROM fact')==rows


def test_page_fact_batch_rollback_exact_retry_and_conflict(
    database: Database, storage: LocalStorage, api: FakeAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CompaniesHouseIngestion(database, storage, CompaniesHouseClient(api), clock=lambda: NOW)
    service.ingest(NUMBER, NOW.date(), 'page-probe')
    company = service.companies.get_by_company_number(NUMBER)
    response = api('/company/'+NUMBER+'/officers?start_index=0&items_per_page=2')
    source, raw = service._records(company,'page-probe',Resource.OFFICERS,98,response)
    service.evidence.save(source,raw,response.body)
    parsed = observations(Resource.OFFICERS,api.payloads['officers'][0],NUMBER,'$.items[0]')
    original = database.execute
    def fail_links(sql: str, parameters: Sequence[SqlValue] = ()) -> None:
        if sql.startswith('INSERT INTO fact_evidence'):
            raise PersistenceError('synthetic link insertion failure')
        original(sql,parameters)
    monkeypatch.setattr(database,'execute',fail_links)
    with pytest.raises(PersistenceError):
        service._save_observations(source,parsed)
    assert database.query('SELECT * FROM fact WHERE source_id=?',(source.source_id,)) == []
    assert database.query('SELECT * FROM evidence_reference WHERE source_id=?',(source.source_id,)) == []
    monkeypatch.setattr(database,'execute',original)
    service._save_observations(source,parsed)
    service._save_observations(source,parsed)
    changed = observations(Resource.OFFICERS,api.payloads['officers'][0]|{'name':'DIFFERENT'},NUMBER,'$.items[0]')
    with pytest.raises(PersistenceError,match='Conflicting'):
        service._save_observations(source,changed)
