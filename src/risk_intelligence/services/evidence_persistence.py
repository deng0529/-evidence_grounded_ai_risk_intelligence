"""Object-first persistence only; no source retrieval, parsing or assessment."""

from risk_intelligence.domain.enums import RetrievalStatus
from risk_intelligence.domain.evidence import Document, RawEvidence, Source
from risk_intelligence.interfaces import EvidenceStorage
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.evidence_repositories import (
    SqlDocumentRepository, SqlRawEvidenceRepository, SqlSourceRepository,
)
from risk_intelligence.storage.objects import object_key, verify_checksum


class EvidencePersistence:
    """Coordinate verified immutable bytes and their atomic relational metadata.

    This is the application publication boundary; direct repository saves verify
    relational metadata only. Call outside any Database.transaction context.
    The company and run must already exist. SQL failure may leave an orphan
    object, deliberately retained for a safe retry with the same identity.
    """

    def __init__(self, database: Database, storage: EvidenceStorage) -> None:
        self.database = database
        self.storage = storage
        self.sources = SqlSourceRepository(database)
        self.documents = SqlDocumentRepository(database)
        self.raw = SqlRawEvidenceRepository(database)

    def save(self, source: Source, raw: RawEvidence, content: bytes,
             document: Document | None = None) -> None:
        """Verify identities, publish bytes, then commit metadata together."""
        if self.database.in_transaction:
            raise IntegrityError("Evidence publication must start outside a SQL transaction")
        source = Source.model_validate(source)
        raw = RawEvidence.model_validate(raw)
        if document is not None:
            document = Document.model_validate(document)
        verify_checksum(content, raw.checksum)
        if (source.retrieval_status != RetrievalStatus.SUCCESS or source.source_id != raw.source_id
                or source.processing_run_id != raw.processing_run_id or source.retrieved_at != raw.retrieved_at
                or source.checksum not in (None, raw.checksum)):
            raise IntegrityError("Supplied source/raw retrieval identities disagree")
        if raw.object_path != object_key(source, raw.checksum, raw.media_type):
            raise IntegrityError("Raw object key does not match deterministic event metadata")
        if raw.document_id != (document.document_id if document else None):
            raise IntegrityError("Supplied raw/document identities disagree")
        if document is not None and (
            document.source_id != source.source_id or document.company_id != source.company_id
            or document.company_number != source.company_number
            or document.object_path not in (None, raw.object_path)
            or document.checksum not in (None, raw.checksum)
        ):
            raise IntegrityError("Supplied document provenance disagrees")
        if document is not None and (document.object_path is None) != (document.checksum is None):
            raise IntegrityError("Document object path and checksum must be supplied together")
        context = self.database.query(
            "SELECT c.company_number FROM company c JOIN processing_run r USING(company_id) "
            "WHERE c.company_id=? AND r.processing_run_id=?",
            (source.company_id, source.processing_run_id),
        )
        if context != [{"company_number": source.company_number}]:
            raise IntegrityError("Source company/run context is absent or inconsistent")
        # Catch a conflicting retry before creating a new checksum-derived orphan.
        previous = self.raw.get_for_source(source.source_id)
        if previous is not None and previous != raw:
            raise IntegrityError("Retrieval event already has different immutable raw metadata")
        previous_source = self.sources.get(source.source_id)
        if previous_source is not None and previous_source != source:
            raise IntegrityError("Retrieval event already has different immutable source metadata")
        self.storage.put(raw, content)
        verify_checksum(self.storage.read(raw.object_path), raw.checksum)
        with self.database.transaction():
            self.sources.save(source.source_id, source)
            if document is not None:
                self.documents.save(document.document_id, document)
            self.raw.save(raw.raw_evidence_id, raw)

    def read(self, raw_evidence_id: str) -> bytes:
        """Resolve DB metadata and verify object bytes before returning evidence."""
        raw = self.raw.get(raw_evidence_id)
        if raw is None:
            raise FileNotFoundError("Raw evidence metadata is absent")
        content = self.storage.read(raw.object_path)
        verify_checksum(content, raw.checksum)
        return content
