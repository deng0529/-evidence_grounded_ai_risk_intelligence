"""Temporary local integration fixtures and synthetic evidence only."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import socket

import pytest

from risk_intelligence.domain.enums import ProcessingStatus, RetrievalStatus, SourceType, TriggerType
from risk_intelligence.domain.evidence import Company, Document, EvidenceReference, IxbrlLocator, RawEvidence, Source
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, open_sqlite
from risk_intelligence.persistence.evidence_repositories import SqlEvidenceReferenceRepository
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum, object_key


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if an M1 test accidentally attempts a network connection."""
    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network access is forbidden in normal M1 tests")
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with open_sqlite(tmp_path / "test.sqlite3") as database:
        migrate(database, applied_at=datetime(2026, 1, 15, tzinfo=UTC))
        yield database


@dataclass(frozen=True)
class EvidenceChain:
    """Synthetic complete retrieval chain with exact content and active run."""

    company: Company
    run: ProcessingRun
    source: Source
    document: Document
    raw: RawEvidence
    reference: EvidenceReference
    content: bytes
    storage: LocalStorage
    persistence: EvidencePersistence


@pytest.fixture
def chain(database: Database, tmp_path: Path) -> EvidenceChain:
    content = b'<synthetic value="12345.6700" />'
    company = Company(company_id="company-test", company_number="ZZ000001",
                      company_name="SYNTHETIC REVIEW COMPANY", incorporation_date=date(2020, 1, 2),
                      sic_codes=("00001", "00002"), registered_office="SYNTHETIC ADDRESS")
    run = ProcessingRun(processing_run_id="run-test", company_id=company.company_id,
                        company_number=company.company_number, started_at=datetime(2026, 1, 15, 12, tzinfo=UTC),
                        status=ProcessingStatus.RUNNING, current_stage="SYNTHETIC_STORAGE",
                        trigger_type=TriggerType.DEMO_PRECOMPUTE, app_version="0.1.0")
    source = Source(source_id="source-test", company_id=company.company_id, company_number=company.company_number,
                    source_type=SourceType.COMPANIES_HOUSE_IXBRL, source_name="SYNTHETIC SOURCE",
                    source_identifier="synthetic-filing", retrieved_at=run.started_at,
                    retrieval_status=RetrievalStatus.SUCCESS, processing_run_id=run.processing_run_id,
                    checksum=checksum(content), http_status=200)
    key = object_key(source, checksum(content), "application/xhtml+xml")
    document = Document(document_id="document-test", company_id=company.company_id,
                        company_number=company.company_number, source_id=source.source_id,
                        document_type="ACCOUNTS", representation_type="IXBRL", filing_id="synthetic-filing",
                        title="SYNTHETIC", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31),
                        filing_date=date(2026, 1, 1), object_path=key, checksum=checksum(content))
    raw = RawEvidence(raw_evidence_id="raw-test", source_id=source.source_id, document_id=document.document_id,
                      object_path=key, checksum=checksum(content), retrieved_at=source.retrieved_at,
                      processing_run_id=run.processing_run_id, media_type="application/xhtml+xml")
    reference = EvidenceReference(evidence_id="evidence-test", source_id=source.source_id,
                                  document_id=document.document_id,
                                  location=IxbrlLocator(concept="test:CurrentAssets", context_id="year-2025"),
                                  evidence_text="12345.6700")
    storage = LocalStorage(tmp_path / "raw")
    persistence = EvidencePersistence(database, storage)
    SqlCompanyRepository(database).save(company)
    SqlAssessmentRepository(database).save_processing_run(run)
    persistence.save(source, raw, content, document)
    SqlEvidenceReferenceRepository(database).save(reference.evidence_id, reference)
    return EvidenceChain(company, run, source, document, raw, reference, content, storage, persistence)
