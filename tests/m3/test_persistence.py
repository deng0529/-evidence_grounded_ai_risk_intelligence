"""Additive schema, exact monetary round trips and same-company lineage."""

from datetime import UTC, datetime
from pathlib import Path

import libsql
import pytest

from risk_intelligence.domain.enums import ProcessingStatus, RetrievalStatus, SourceType, TriggerType
from risk_intelligence.domain.evidence import Company, Document, EvidenceReference, IxbrlLocator, RawEvidence, Source
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.ingestion.accounts.ixbrl import extract_ixbrl
from risk_intelligence.ingestion.accounts.mapping import FinancialMappingRegistry, MappingRule
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError, PersistenceError, open_sqlite
from risk_intelligence.persistence.evidence_repositories import SqlEvidenceReferenceRepository
from risk_intelligence.persistence.migrations import migrate, MIGRATIONS_DIRECTORY
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum, object_key


@pytest.mark.parametrize('driver', ['sqlite', 'libsql'])
def test_upgrade_from_m2_retains_ledger_and_has_no_fk_errors(tmp_path: Path, driver: str) -> None:
    old = tmp_path / 'm2'; old.mkdir()
    for name in ('001_storage.sql', '002_ingestion.sql'):
        (old / name).write_bytes((MIGRATIONS_DIRECTORY / name).read_bytes())
    with (open_sqlite() if driver == 'sqlite' else Database(libsql.connect(':memory:', isolation_level=None))) as db:
        migrate(db, old)
        before = db.query('SELECT * FROM schema_migration ORDER BY version')
        migrate(db)
        assert db.query('SELECT * FROM schema_migration ORDER BY version')[:2] == before
        assert db.query('SELECT version FROM schema_migration ORDER BY version') == [
            {'version': 1}, {'version': 2}, {'version': 3}, {'version': 4}, {'version': 5}, {'version': 6}, {'version': 7}]
        migrate(db)
        assert db.query('PRAGMA foreign_key_check') == []


def test_verified_source_and_canonical_roundtrip_are_immutable(tmp_path: Path, ixbrl: bytes) -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    with open_sqlite() as db:
        migrate(db)
        company = Company(company_id='c', company_number='ZZ000003', company_name='SYNTHETIC')
        SqlCompanyRepository(db).save(company)
        SqlAssessmentRepository(db).save_processing_run(ProcessingRun(processing_run_id='r',
            company_id='c', company_number=company.company_number, started_at=now,
            status=ProcessingStatus.RUNNING, current_stage='M3', trigger_type=TriggerType.LIVE, app_version='test'))
        source = Source(source_id='s', company_id='c', company_number=company.company_number,
            source_type=SourceType.COMPANIES_HOUSE_IXBRL, source_name='Synthetic', source_identifier='test',
            retrieved_at=now, retrieval_status=RetrievalStatus.SUCCESS, processing_run_id='r', checksum=checksum(ixbrl))
        key = object_key(source, checksum(ixbrl), 'application/xhtml+xml')
        document = Document(document_id='d', company_id='c', company_number=company.company_number,
            source_id='s', document_type='ACCOUNTS', representation_type='application/xhtml+xml',
            object_path=key, checksum=checksum(ixbrl))
        raw = RawEvidence(raw_evidence_id='raw', source_id='s', document_id='d', object_path=key,
            checksum=checksum(ixbrl), retrieved_at=now, processing_run_id='r', media_type='application/xhtml+xml')
        coordinator = EvidencePersistence(db, LocalStorage(tmp_path / 'raw'))
        coordinator.save(source, raw, ixbrl, document)
        facts = extract_ixbrl(coordinator.read('raw'), 'd', company.company_number).facts
        repository = AccountsRepository(db)
        registry = FinancialMappingRegistry('synthetic-v1', (
            MappingRule(source_concept='{urn:synthetic:accounts:v1}NetAssets', canonical_concept='NET_ASSETS'),))
        for fact in facts:
            with pytest.raises(IntegrityError):
                repository.save_source(fact)
            SqlEvidenceReferenceRepository(db).save(fact.evidence_id, EvidenceReference(evidence_id=fact.evidence_id,
                source_id='s', document_id='d', location=IxbrlLocator(concept=fact.source_concept, context_id=fact.context_ref)))
            repository.save_source(fact)
            repository.save_source(fact)
            assert repository.get_source(fact.source_fact_id) == fact
            canonical = registry.map(fact, company_id='c', company_number=company.company_number,
                                     source_id='s', processing_run_id='r')
            if canonical:
                repository.save_direct(canonical, fact.source_fact_id, registry.version)
                repository.save_direct(canonical, fact.source_fact_id, registry.version)
                assert repository.canonical.get(canonical.financial_fact_id) == canonical
        assert len(db.query('SELECT * FROM financial_source_fact')) == 4
        assert len(db.query('SELECT * FROM financial_observation_lineage')) == 2
        assert not db.query('PRAGMA foreign_key_check')
        with pytest.raises(PersistenceError):
            db.execute("UPDATE financial_source_fact SET value='0'")
