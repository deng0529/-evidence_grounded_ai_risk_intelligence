"""Company, source, document and evidence-location contracts."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import CompanyNumber, Contract, Text, UtcTimestamp
from .enums import RetrievalStatus, SourceType


class Company(Contract):
    """Canonical company number plus optional source-derived registry metadata."""

    company_id: Text
    company_number: CompanyNumber
    company_name: Text
    company_status: Text | None = None
    company_type: Text | None = None
    incorporation_date: date | None = None
    registered_office: Text | None = None
    sic_codes: tuple[Text, ...] = ()


class Source(Contract):
    """An explicit retrieval event; its URL or identifier retains provenance."""

    source_id: Text
    company_id: Text
    company_number: CompanyNumber
    source_type: SourceType
    source_name: Text
    source_url: Text | None = None
    source_identifier: Text | None = None
    retrieved_at: UtcTimestamp
    retrieval_status: RetrievalStatus
    processing_run_id: Text
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    checksum: Text | None = None

    @model_validator(mode="after")
    def require_source_reference(self) -> Self:
        """Prevent source records that cannot identify their original source."""
        if self.source_url is None and self.source_identifier is None:
            raise ValueError("source_url or source_identifier is required")
        return self


class Document(Contract):
    """Metadata for a source document, not its raw bytes or extracted facts."""

    document_id: Text
    company_id: Text
    company_number: CompanyNumber
    source_id: Text
    document_type: Text
    representation_type: Text
    filing_id: Text | None = None
    title: Text | None = None
    period_start: date | None = None
    period_end: date | None = None
    filing_date: date | None = None
    object_path: Text | None = None
    checksum: Text | None = None

    @model_validator(mode="after")
    def check_period_order(self) -> Self:
        """Reject reversed periods without inferring absent dates."""
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must not follow period_end")
        return self


class ApiLocator(Contract):
    """A JSON field location within the referenced source response."""

    kind: Literal["JSON_PATH"] = "JSON_PATH"
    endpoint: Text
    json_path: Text


class IxbrlLocator(Contract):
    """An iXBRL fact identified by concept and reporting context."""

    kind: Literal["IXBRL_FACT"] = "IXBRL_FACT"
    concept: Text
    context_id: Text


class PdfLocator(Contract):
    """A one-based PDF page and human-readable region/label."""

    kind: Literal["PDF_REGION"] = "PDF_REGION"
    page: Annotated[int, Field(ge=1)]
    label: Text
    section: Text | None = None
    table: Text | None = None


EvidenceLocator = Annotated[ApiLocator | IxbrlLocator | PdfLocator, Field(discriminator="kind")]


class EvidenceReference(Contract):
    """Traceable source location, optionally including a verbatim evidence span."""

    evidence_id: Text
    source_id: Text
    document_id: Text | None = None
    location: EvidenceLocator
    evidence_text: Text | None = None

    @model_validator(mode="after")
    def require_document_for_document_locator(self) -> Self:
        """PDF and iXBRL locations must identify the document being cited."""
        if isinstance(self.location, (PdfLocator, IxbrlLocator)) and self.document_id is None:
            raise ValueError("document_id is required for PDF/iXBRL evidence")
        return self


class RawEvidence(Contract):
    """Immutable object metadata linking future storage to the retrieval event."""

    raw_evidence_id: Text
    source_id: Text
    document_id: Text | None = None
    object_path: Text
    checksum: Text
    retrieved_at: UtcTimestamp
    processing_run_id: Text
    media_type: Text
