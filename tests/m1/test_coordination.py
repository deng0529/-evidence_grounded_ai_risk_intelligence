"""Cross-store failure, retrieval history and structural provenance integration."""

from collections.abc import Sequence
from datetime import timedelta

import pytest

from risk_intelligence.domain.enums import AvailabilityStatus, RetrievalStatus
from risk_intelligence.domain.evidence import Company, Document, EvidenceReference, RawEvidence, Source
from risk_intelligence.domain.facts import FinancialFact
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError, PersistenceError, SqlValue
from risk_intelligence.persistence.evidence_repositories import (
    SqlDocumentRepository, SqlEvidenceReferenceRepository, SqlRawEvidenceRepository, SqlSourceRepository,
)
from risk_intelligence.persistence.fact_repositories import SqlFinancialFactRepository
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.objects import EvidenceIntegrityError, StorageAccessError, checksum, object_key

from conftest import EvidenceChain


def next_event(chain: EvidenceChain, content: bytes, *, run_id: str | None = None) -> tuple[Source, RawEvidence, Document]:
    source = Source.model_validate(chain.source.model_dump() | {
        "source_id": "source-later", "retrieved_at": chain.source.retrieved_at + timedelta(days=1),
        "processing_run_id": run_id or chain.run.processing_run_id, "checksum": checksum(content),
    })
    key = object_key(source, checksum(content), chain.raw.media_type)
    document = Document.model_validate(chain.document.model_dump() | {
        "document_id": "document-later", "source_id": source.source_id,
        "object_path": key, "checksum": checksum(content),
    })
    raw = RawEvidence.model_validate(chain.raw.model_dump() | {
        "raw_evidence_id": "raw-later", "source_id": source.source_id, "document_id": document.document_id,
        "object_path": key, "checksum": checksum(content), "retrieved_at": source.retrieved_at,
        "processing_run_id": source.processing_run_id,
    })
    return source, raw, document


def test_storage_failure_creates_no_false_sql_pointer(database: Database, chain: EvidenceChain) -> None:
    class FailedStorage:
        def put(self, evidence: RawEvidence, content: bytes) -> None:
            raise StorageAccessError("Synthetic upload failure")
        def read(self, object_path: str) -> bytes:
            raise AssertionError("read must not follow failed upload")
    source, raw, document = next_event(chain, b"later")
    with pytest.raises(StorageAccessError):
        EvidencePersistence(database, FailedStorage()).save(source, raw, b"later", document)
    assert SqlSourceRepository(database).get(source.source_id) is None
    assert SqlDocumentRepository(database).get(document.document_id) is None
    assert SqlRawEvidenceRepository(database).get(raw.raw_evidence_id) is None


def test_sql_failure_after_upload_leaves_safe_retryable_object(database: Database, chain: EvidenceChain,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    source, raw, document = next_event(chain, b"later")
    original_save = chain.persistence.raw.save
    def fail_metadata(*args: object) -> None:
        raise PersistenceError("synthetic SQL failure after source/document writes")
    monkeypatch.setattr(chain.persistence.raw, "save", fail_metadata)
    with pytest.raises(PersistenceError):
        chain.persistence.save(source, raw, b"later", document)
    assert chain.storage.read(raw.object_path) == b"later"
    assert chain.persistence.sources.get(source.source_id) is None
    assert chain.persistence.documents.get(document.document_id) is None
    monkeypatch.setattr(chain.persistence.raw, "save", original_save)
    chain.persistence.save(source, raw, b"later", document)
    assert chain.persistence.read(raw.raw_evidence_id) == b"later"


@pytest.mark.parametrize("changed", [False, True])
def test_later_retrieval_preserves_both_snapshots_and_same_logical_filing(
    database: Database, chain: EvidenceChain, changed: bool,
) -> None:
    content = b"later changed bytes" if changed else chain.content
    source, raw, document = next_event(chain, content)
    chain.persistence.save(source, raw, content, document)
    chain.persistence.save(source, raw, content, document)
    assert raw.object_path != chain.raw.object_path
    assert document.filing_id == chain.document.filing_id
    assert chain.persistence.read(chain.raw.raw_evidence_id) == chain.content
    assert chain.persistence.read(raw.raw_evidence_id) == content
    assert len(database.query("SELECT * FROM raw_evidence")) == 2


def test_changed_bytes_cannot_reuse_retrieval_identity(chain: EvidenceChain) -> None:
    content = b"different"
    source = Source.model_validate(chain.source.model_dump() | {"checksum": checksum(content)})
    key = object_key(source, checksum(content), chain.raw.media_type)
    raw = RawEvidence.model_validate(chain.raw.model_dump() | {"checksum": checksum(content), "object_path": key})
    document = Document.model_validate(chain.document.model_dump() | {"checksum": checksum(content), "object_path": key})
    with pytest.raises(IntegrityError, match="already has"):
        chain.persistence.save(source, raw, content, document)
    assert chain.persistence.read(chain.raw.raw_evidence_id) == chain.content
    with pytest.raises(FileNotFoundError):
        chain.storage.read(key)


def test_metadata_aware_read_rejects_external_corruption(chain: EvidenceChain) -> None:
    (chain.storage.root / chain.raw.object_path).write_bytes(b"external corruption")
    with pytest.raises(EvidenceIntegrityError):
        chain.persistence.read(chain.raw.raw_evidence_id)


def test_low_level_repositories_are_relational_only(
    database: Database, chain: EvidenceChain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, raw, document = next_event(chain, b"not stored")
    def reject_storage(*args: object) -> None:
        raise AssertionError("SQL repositories must not access storage")
    monkeypatch.setattr(chain.storage, "read", reject_storage)
    monkeypatch.setattr(chain.storage, "put", reject_storage)
    # Deliberately demonstrate the documented low-level bypass, not publication.
    with database.transaction():
        SqlSourceRepository(database).save(source.source_id, source)
        SqlDocumentRepository(database).save(document.document_id, document)
        SqlRawEvidenceRepository(database).save(raw.raw_evidence_id, raw)
    assert SqlDocumentRepository(database).get(document.document_id) == document
    assert SqlRawEvidenceRepository(database).get(raw.raw_evidence_id) == raw
    assert not (chain.storage.root / raw.object_path).exists()


@pytest.mark.parametrize("failure", ["missing", "corrupt", "access"])
def test_failed_readback_cannot_publish_metadata(
    database: Database, chain: EvidenceChain, failure: str,
) -> None:
    source, raw, document = next_event(chain, b"later")
    class UnverifiedStorage:
        def put(self, evidence: RawEvidence, content: bytes) -> None:
            assert not database.in_transaction
        def read(self, object_path: str) -> bytes:
            assert not database.in_transaction
            if failure == "missing":
                raise FileNotFoundError(object_path)
            if failure == "access":
                raise StorageAccessError("synthetic read failure")
            return b"corrupt"
    expected = {"missing": FileNotFoundError, "corrupt": EvidenceIntegrityError,
                "access": StorageAccessError}[failure]
    with pytest.raises(expected):
        EvidencePersistence(database, UnverifiedStorage()).save(source, raw, b"later", document)
    assert SqlSourceRepository(database).get(source.source_id) is None
    assert SqlDocumentRepository(database).get(document.document_id) is None
    assert SqlRawEvidenceRepository(database).get(raw.raw_evidence_id) is None


def test_publication_verifies_once_before_sql_and_preserves_provenance(
    database: Database, chain: EvidenceChain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, raw, document = next_event(chain, b"later")
    events: list[str] = []
    original_execute = database.execute
    def track_sql(sql: str, parameters: Sequence[SqlValue] = ()) -> None:
        if sql == "BEGIN IMMEDIATE":
            assert events == ["put", "read"]
            events.append("begin")
        original_execute(sql, parameters)
    class ObservedStorage:
        def put(self, evidence: RawEvidence, content: bytes) -> None:
            assert not database.in_transaction
            events.append("put")
            chain.storage.put(evidence, content)
        def read(self, object_path: str) -> bytes:
            assert not database.in_transaction
            assert SqlSourceRepository(database).get(source.source_id) is None
            assert SqlRawEvidenceRepository(database).get(raw.raw_evidence_id) is None
            events.append("read")
            return chain.storage.read(object_path)
    monkeypatch.setattr(database, "execute", track_sql)
    EvidencePersistence(database, ObservedStorage()).save(source, raw, b"later", document)
    assert events == ["put", "read", "begin"]
    assert SqlSourceRepository(database).get(source.source_id) == source
    assert SqlDocumentRepository(database).get(document.document_id) == document
    assert SqlRawEvidenceRepository(database).get(raw.raw_evidence_id) == raw


def test_publication_rejects_enclosing_transaction_before_storage(
    database: Database, chain: EvidenceChain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, raw, document = next_event(chain, b"later")
    def reject_storage(*args: object) -> None:
        raise AssertionError("Storage must not run inside a transaction")
    monkeypatch.setattr(chain.storage, "put", reject_storage)
    monkeypatch.setattr(chain.storage, "read", reject_storage)
    with database.transaction():
        with pytest.raises(IntegrityError, match="outside a SQL transaction"):
            chain.persistence.save(source, raw, b"later", document)
    assert chain.persistence.raw.get(raw.raw_evidence_id) is None


def test_supplied_checksum_failure_precedes_storage(
    database: Database, chain: EvidenceChain, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, raw, document = next_event(chain, b"later")
    def reject_storage(*args: object) -> None:
        raise AssertionError("Invalid bytes must not be published")
    monkeypatch.setattr(chain.storage, "put", reject_storage)
    with pytest.raises(EvidenceIntegrityError):
        chain.persistence.save(source, raw, b"wrong", document)
    assert chain.persistence.sources.get(source.source_id) is None
    assert chain.persistence.documents.get(document.document_id) is None
    assert chain.persistence.raw.get(raw.raw_evidence_id) is None


def test_failed_retrieval_retains_typed_null_without_fabricated_evidence(
    database: Database, chain: EvidenceChain, financial_fact: FinancialFact,
) -> None:
    source = Source.model_validate(chain.source.model_dump() | {
        "source_id": "failed-source", "retrieval_status": RetrievalStatus.FAILED, "checksum": None, "http_status": 503,
    })
    chain.persistence.sources.save(source.source_id, source)
    fact = FinancialFact.model_validate(financial_fact.model_dump() | {
        "source_id": source.source_id, "document_id": None, "evidence_ids": (), "period": None, "unit": None,
        "value_numeric": None, "availability_status": AvailabilityStatus.RETRIEVAL_FAILED,
    })
    repository = SqlFinancialFactRepository(database)
    repository.save(fact.financial_fact_id, fact)
    assert repository.get(fact.financial_fact_id) == fact
    assert chain.persistence.raw.get_for_source(source.source_id) is None


def test_reprocessing_can_reference_prior_run_evidence(database: Database, chain: EvidenceChain,
                                                      financial_fact: FinancialFact) -> None:
    run = ProcessingRun.model_validate(chain.run.model_dump() | {"processing_run_id": "reprocess-run"})
    SqlAssessmentRepository(database).save_processing_run(run)
    fact = FinancialFact.model_validate(financial_fact.model_dump() | {"processing_run_id": run.processing_run_id})
    repository = SqlFinancialFactRepository(database)
    repository.save(fact.financial_fact_id, fact)
    assert repository.get(fact.financial_fact_id).source_id == chain.source.source_id


def test_cross_company_evidence_link_rolls_back_fact(database: Database, chain: EvidenceChain,
                                                   financial_fact: FinancialFact) -> None:
    company = Company(company_id="other-company", company_number="ZZ000002", company_name="SYNTHETIC OTHER")
    SqlCompanyRepository(database).save(company)
    run = ProcessingRun.model_validate(chain.run.model_dump() | {
        "processing_run_id": "other-run", "company_id": company.company_id, "company_number": company.company_number,
    })
    SqlAssessmentRepository(database).save_processing_run(run)
    source = Source.model_validate(chain.source.model_dump() | {
        "source_id": "other-source", "company_id": company.company_id, "company_number": company.company_number,
        "processing_run_id": run.processing_run_id, "retrieval_status": RetrievalStatus.FAILED, "checksum": None,
    })
    chain.persistence.sources.save(source.source_id, source)
    fact = FinancialFact.model_validate(financial_fact.model_dump() | {
        "company_id": company.company_id, "company_number": company.company_number,
        "source_id": source.source_id, "document_id": None, "processing_run_id": run.processing_run_id,
    })
    with pytest.raises(PersistenceError):
        SqlFinancialFactRepository(database).save(fact.financial_fact_id, fact)
    assert SqlFinancialFactRepository(database).get(fact.financial_fact_id) is None


def test_locator_cannot_reference_unstored_or_different_document(database: Database, chain: EvidenceChain) -> None:
    wrong = EvidenceReference.model_validate(chain.reference.model_dump() | {
        "evidence_id": "wrong-evidence", "document_id": "different-document",
    })
    with pytest.raises(IntegrityError, match="matching"):
        SqlEvidenceReferenceRepository(database).save(wrong.evidence_id, wrong)


def test_existing_object_may_be_referenced_by_separate_metadata(database: Database, chain: EvidenceChain) -> None:
    source, raw, document = next_event(chain, chain.content)
    # Deliberate metadata reference to existing immutable bytes, not deduplication.
    raw = RawEvidence.model_validate(raw.model_dump() | {"object_path": chain.raw.object_path})
    document = Document.model_validate(document.model_dump() | {"object_path": chain.raw.object_path})
    with database.transaction():
        chain.persistence.sources.save(source.source_id, source)
        chain.persistence.documents.save(document.document_id, document)
        chain.persistence.raw.save(raw.raw_evidence_id, raw)
    assert chain.persistence.read(raw.raw_evidence_id) == chain.content
    assert len(database.query("SELECT raw_evidence_id FROM raw_evidence WHERE object_path=?", (chain.raw.object_path,))) == 2


def test_inconsistent_run_context_is_rejected_before_object_write(chain: EvidenceChain) -> None:
    source, raw, document = next_event(chain, b"later", run_id="absent-run")
    with pytest.raises(IntegrityError, match="context"):
        chain.persistence.save(source, raw, b"later", document)
    with pytest.raises(FileNotFoundError):
        chain.storage.read(raw.object_path)


def test_raw_source_timestamp_mismatch_is_rejected(database: Database, chain: EvidenceChain) -> None:
    wrong = RawEvidence.model_validate(chain.raw.model_dump() | {"retrieved_at": chain.raw.retrieved_at + timedelta(seconds=1)})
    with pytest.raises(IntegrityError, match="lineage"):
        SqlRawEvidenceRepository(database).save(wrong.raw_evidence_id, wrong)


def test_document_pointer_cannot_commit_without_raw_metadata(database: Database, chain: EvidenceChain) -> None:
    source, raw, document = next_event(chain, b"later")
    chain.storage.put(raw, b"later")
    chain.persistence.sources.save(source.source_id, source)
    with pytest.raises(PersistenceError):
        chain.persistence.documents.save(document.document_id, document)
    assert chain.persistence.documents.get(document.document_id) is None
