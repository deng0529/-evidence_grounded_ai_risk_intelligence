"""Typed retrieval/document/raw/locator repositories and structural provenance."""

from risk_intelligence.domain.enums import RetrievalStatus, SourceType
from risk_intelligence.domain.evidence import (
    ApiLocator, Document, EvidenceReference, IxbrlLocator, PdfLocator, RawEvidence, Source,
)
from risk_intelligence.storage.objects import validate_object_path
from .connection import Database, IntegrityError, Row
from .mapping import date_value, encode, text, timestamp_value
from .records import SqlRecordRepository


def _source_row(record: Source) -> Row:
    record = Source.model_validate(record)
    return {
        "source_id": record.source_id, "company_id": record.company_id,
        "company_number": record.company_number, "source_type": encode(record.source_type),
        "source_name": record.source_name, "source_url": record.source_url,
        "source_identifier": record.source_identifier, "retrieved_at": encode(record.retrieved_at),
        "retrieval_status": encode(record.retrieval_status), "processing_run_id": record.processing_run_id,
        "http_status": record.http_status, "checksum": record.checksum,
    }


def _source(row: Row) -> Source:
    return Source(**(row | {
        "source_type": SourceType(text(row["source_type"])),
        "retrieval_status": RetrievalStatus(text(row["retrieval_status"])),
        "retrieved_at": timestamp_value(row["retrieved_at"]),
    }))


def _document_row(record: Document) -> Row:
    record = Document.model_validate(record)
    return {
        "document_id": record.document_id, "company_id": record.company_id,
        "company_number": record.company_number, "source_id": record.source_id,
        "document_type": record.document_type, "representation_type": record.representation_type,
        "filing_id": record.filing_id, "title": record.title, "period_start": encode(record.period_start),
        "period_end": encode(record.period_end), "filing_date": encode(record.filing_date),
        "object_path": record.object_path, "checksum": record.checksum,
    }


def _document(row: Row) -> Document:
    return Document(**(row | {key: date_value(row[key]) for key in
                             ("period_start", "period_end", "filing_date")}))


def _raw_row(record: RawEvidence) -> Row:
    record = RawEvidence.model_validate(record)
    return {
        "raw_evidence_id": record.raw_evidence_id, "source_id": record.source_id,
        "document_id": record.document_id, "object_path": record.object_path,
        "checksum": record.checksum, "retrieved_at": encode(record.retrieved_at),
        "processing_run_id": record.processing_run_id, "media_type": record.media_type,
    }


def _raw(row: Row) -> RawEvidence:
    return RawEvidence(**(row | {"retrieved_at": timestamp_value(row["retrieved_at"])}))


def _reference_row(record: EvidenceReference) -> Row:
    record = EvidenceReference.model_validate(record)
    row: Row = {
        "evidence_id": record.evidence_id, "source_id": record.source_id,
        "document_id": record.document_id, "locator_kind": record.location.kind,
        "endpoint": None, "json_path": None, "concept": None, "context_id": None,
        "page": None, "label": None, "section": None, "table_label": None,
        "evidence_text": record.evidence_text,
    }
    location = record.location
    if isinstance(location, ApiLocator):
        row.update(endpoint=location.endpoint, json_path=location.json_path)
    elif isinstance(location, IxbrlLocator):
        row.update(concept=location.concept, context_id=location.context_id)
    else:
        row.update(page=location.page, label=location.label, section=location.section, table_label=location.table)
    return row


def _reference(row: Row) -> EvidenceReference:
    kind = row["locator_kind"]
    if kind == "JSON_PATH":
        location = ApiLocator(endpoint=row["endpoint"], json_path=row["json_path"])
    elif kind == "IXBRL_FACT":
        location = IxbrlLocator(concept=row["concept"], context_id=row["context_id"])
    elif kind == "PDF_REGION":
        location = PdfLocator(page=row["page"], label=row["label"], section=row["section"], table=row["table_label"])
    else:
        raise IntegrityError("Unknown stored evidence locator")
    result = EvidenceReference(
        evidence_id=row["evidence_id"], source_id=row["source_id"], document_id=row["document_id"],
        location=location, evidence_text=row["evidence_text"],
    )
    if _reference_row(result) != row:
        raise IntegrityError("Extraneous stored locator fields")
    return result


class SqlSourceRepository(SqlRecordRepository[Source]):
    """Persist immutable retrieval events, including failures without objects."""

    def __init__(self, database: Database) -> None:
        super().__init__(database, "source", "source_id", _source_row, _source)


class SqlDocumentRepository(SqlRecordRepository[Document]):
    """Low-level relational metadata only; publish bytes via EvidencePersistence.save."""

    def __init__(self, database: Database) -> None:
        super().__init__(database, "document", "document_id", _document_row, _document)

    def _check(self, record: Document) -> None:
        if (record.object_path is None) != (record.checksum is None):
            raise IntegrityError("Document object path and checksum must be supplied together")
        if record.object_path is not None and record.checksum is not None:
            validate_object_path(record.object_path)


class SqlRawEvidenceRepository(SqlRecordRepository[RawEvidence]):
    """Low-level relational metadata only; callers must publish via EvidencePersistence.save.

    Checks provenance and SQL constraints, not object existence or byte integrity.
    Direct saves are not an application publication API.
    """

    def __init__(self, database: Database) -> None:
        super().__init__(database, "raw_evidence", "raw_evidence_id", _raw_row, _raw)

    def _check(self, record: RawEvidence) -> None:
        source = SqlSourceRepository(self.database).get(record.source_id)
        if source is None or source.retrieval_status != RetrievalStatus.SUCCESS:
            raise IntegrityError("Raw evidence requires a successful source retrieval")
        if source.processing_run_id != record.processing_run_id or source.retrieved_at != record.retrieved_at:
            raise IntegrityError("Raw evidence retrieval lineage differs from source")
        if source.checksum is not None and source.checksum != record.checksum:
            raise IntegrityError("Raw evidence checksum differs from source")
        validate_object_path(record.object_path)

    def get_for_source(self, source_id: str) -> RawEvidence | None:
        """Resolve the single raw response for one immutable retrieval event."""
        rows = self.database.query("SELECT raw_evidence_id FROM raw_evidence WHERE source_id=?", (source_id,))
        return self.get(text(rows[0]["raw_evidence_id"])) if rows else None


class SqlEvidenceReferenceRepository(SqlRecordRepository[EvidenceReference]):
    """Persist typed locators only for an existing, unambiguous raw response."""

    def __init__(self, database: Database) -> None:
        super().__init__(database, "evidence_reference", "evidence_id", _reference_row, _reference)

    def _check(self, record: EvidenceReference) -> None:
        rows = self.database.query("SELECT document_id FROM raw_evidence WHERE source_id=?", (record.source_id,))
        if not rows or (record.document_id is not None and rows[0]["document_id"] != record.document_id):
            raise IntegrityError("Evidence locator has no matching raw response/document")
