"""Offline real SQLite/local integration of M2 completeness, facts and provenance."""

from datetime import date, timedelta

import pytest

from risk_intelligence.domain.enums import AvailabilityStatus, ProcessingStatus
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, RetrievalError
from risk_intelligence.ingestion.companies_house.policy import FreshnessPolicy, Resource, horizon_start
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import Database
from risk_intelligence.persistence.fact_repositories import SqlStructuredFactRepository
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum, EvidenceIntegrityError, StorageAccessError
from conftest import FakeAPI, NOW, NUMBER


def service(database: Database, storage: LocalStorage, api: FakeAPI, policy: FreshnessPolicy | None = None) -> CompaniesHouseIngestion:
    return CompaniesHouseIngestion(database, storage, CompaniesHouseClient(api, pause=lambda _: None),
                                   policy or FreshnessPolicy(page_size=2), clock=lambda: api.now)


def test_complete_population_typed_values_window_and_provenance(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    result = service(database, storage, api).ingest(NUMBER, NOW.date(), "test-run")
    assert result.run.status == ProcessingStatus.COMPLETE
    assert all(s.complete for s in result.snapshots)
    assert result.snapshots[-1].item_count == 2
    facts = database.query("SELECT * FROM fact")
    assert any(f['value_date'] == '2015-01-01' for f in facts)
    assert not any(f['subject_identifier'] == 'filing:filing-c' for f in facts)
    assert any(f['subject_identifier'] == 'filing:filing-b' for f in facts)
    active = next(f for f in facts if f['canonical_concept'] == 'OFFICERS_RESIGNED_ON' and f['subject_identifier'].endswith('a'))
    assert active['value_date'] is None and active['availability_status'] == 'NOT_APPLICABLE'
    boolean = next(f for f in facts if f['canonical_concept'] == 'PROFILE_ACCOUNTS_NEXT_ACCOUNTS_OVERDUE')
    assert boolean['value_boolean'] == 0
    assert len({f['subject_identifier'] for f in facts if f['canonical_concept'] == 'OFFICERS_APPOINTED_ON'}) == 2
    for row in database.query('SELECT * FROM raw_evidence'):
        assert checksum(storage.read(row['object_path'])) == row['checksum']
    repository = SqlStructuredFactRepository(database)
    for row in database.query('SELECT * FROM fact_evidence'):
        assert row['fact_id'] in repository.fact_ids_for_evidence(row['evidence_id'])
        assert row['evidence_id'] in repository.get(row['fact_id']).evidence_ids
    assert not database.query('PRAGMA foreign_key_check')
    assert database.query("SELECT count(*) AS n FROM company")[0]['n'] == 1


def test_reuse_then_only_stale_resource_refreshes_and_preserves_history(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    first = service(database, storage, api).ingest(NUMBER, NOW.date(), 'first')
    original_count = len(database.query('SELECT * FROM raw_evidence'))
    api.calls.clear()
    second = service(database, storage, api).ingest(NUMBER, NOW.date(), 'second')
    assert api.calls == [] and all(s.reused_snapshot_id for s in second.snapshots)
    policy = FreshnessPolicy(max_age={r: timedelta(0) if r==Resource.OFFICERS else timedelta(days=1) for r in Resource})
    third = service(database, storage, api, policy).ingest(NUMBER, NOW.date(), 'third')
    assert len(api.calls) == 1 and '/officers?' in api.calls[0]
    assert len(database.query('SELECT * FROM raw_evidence')) == original_count + 1
    assert third.snapshots[1].reused_snapshot_id is None
    assert len(database.query('SELECT * FROM company')) == 1
    assert len(database.query('SELECT * FROM processing_run')) == 3
    assert service(database, storage, api).runs.get_processing_run('first') == first.run


def test_partial_page_failure_cannot_reuse_and_other_endpoints_survive(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    api.failures['officers:1'] = 503
    policy = FreshnessPolicy(page_size=1)
    first = service(database, storage, api, policy).ingest(NUMBER, NOW.date(), 'partial')
    assert first.run.status == ProcessingStatus.PARTIAL
    assert not first.snapshots[1].complete and first.snapshots[1].page_count == 1
    assert first.snapshots[-1].complete
    api.failures.clear(); api.calls.clear()
    second = service(database, storage, api, policy).ingest(NUMBER, NOW.date(), 'retry')
    assert second.run.status == ProcessingStatus.COMPLETE
    assert all('/officers?' in p for p in api.calls)


def test_missing_coverage_or_expired_data_refreshes(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    service(database, storage, api).ingest(NUMBER, NOW.date()-timedelta(days=1), 'old-window')
    api.calls.clear()
    service(database, storage, api).ingest(NUMBER, NOW.date(), 'new-window')
    assert any('/filing-history?' in p for p in api.calls)
    api.now += timedelta(days=2); api.calls.clear()
    service(database, storage, api).ingest(NUMBER, api.now.date(), 'stale')
    assert len(api.calls) >= 5


def test_nonexistent_company_stops_without_invented_identity(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    api.failures['profile:0'] = 404
    with pytest.raises(RetrievalError):
        service(database, storage, api).ingest(NUMBER, NOW.date(), 'missing')
    assert len(api.calls)==1 and database.query('SELECT * FROM company')==[]


@pytest.mark.parametrize('mode', ['write', 'readback'])
def test_storage_failure_publishes_no_false_facts(database: Database, storage: LocalStorage, api: FakeAPI,
                                                monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    def failed(*args: object) -> None:
        raise StorageAccessError('synthetic')
    if mode == 'write':
        monkeypatch.setattr(storage, 'put', failed)
    else:
        monkeypatch.setattr(storage, 'read', lambda p: b'corrupt')
    with pytest.raises((StorageAccessError, EvidenceIntegrityError)):
        service(database, storage, api).ingest(NUMBER, NOW.date(), 'storage-failure')
    assert database.query('SELECT * FROM fact') == []
    assert database.query('SELECT * FROM raw_evidence') == []


def test_changed_population_and_malformed_fields_are_incomplete(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    api.payloads['officers'][1]['appointed_on'] = 'UNKNOWN'
    result = service(database, storage, api).ingest(NUMBER, NOW.date(), 'malformed')
    assert result.snapshots[1].availability_status == AvailabilityStatus.EXTRACTION_FAILED
    assert not result.snapshots[1].complete
    assert result.snapshots[2].complete
    assert database.query("SELECT * FROM api_response WHERE resource='officers'")
    assert not database.query("SELECT * FROM fact WHERE canonical_concept LIKE 'OFFICERS_%'")


def test_empty_psc_is_complete_observation_not_risk(database: Database, storage: LocalStorage, api: FakeAPI) -> None:
    api.payloads['persons-with-significant-control'] = []
    api.payloads['persons-with-significant-control-statements'] = [
        {'statement':'no-individual-or-entity-with-signficant-control', 'notified_on':'2020-01-01',
         'links':{'self':'/synthetic/statement'}}]
    result = service(database, storage, api).ingest(NUMBER, NOW.date(), 'empty-psc')
    assert result.snapshots[2].complete and result.snapshots[2].item_count==0
    assert result.snapshots[3].item_count==1
    assert database.query('SELECT * FROM assessment')==[]


def test_calendar_horizon_boundaries() -> None:
    assert horizon_start(date(2026,9,29))==date(2023,9,29)
    assert horizon_start(date(2024,2,29))==date(2021,2,28)


def test_statements_404_remains_incomplete_and_only_that_resource_retries(
    database: Database, storage: LocalStorage, api: FakeAPI,
) -> None:
    api.failures['persons-with-significant-control-statements:0'] = 404
    first = service(database,storage,api).ingest(NUMBER,NOW.date(),'no-statements')
    assert first.run.status == ProcessingStatus.PARTIAL
    assert first.snapshots[3].complete is False
    assert first.snapshots[3].availability_status == AvailabilityStatus.RETRIEVAL_FAILED
    assert first.snapshots[3].error_code == 'HTTP_404'
    assert database.query("SELECT * FROM fact WHERE canonical_concept LIKE 'STATEMENTS_%'") == []
    api.calls.clear()
    second = service(database,storage,api).ingest(NUMBER,NOW.date(),'recheck-statements')
    assert len(api.calls)==1 and '/persons-with-significant-control-statements?' in api.calls[0]
    assert second.run.status == ProcessingStatus.PARTIAL
    assert all(s.reused_snapshot_id for s in second.snapshots if s.resource != Resource.STATEMENTS)
