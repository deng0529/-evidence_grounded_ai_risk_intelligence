"""Identity, immutable evidence locators and UTC contracts."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from risk_intelligence.domain.evidence import (
    ApiLocator, Company, Document, EvidenceReference, IxbrlLocator, PdfLocator,
    RawEvidence, Source,
)


@pytest.mark.parametrize("number", ["00000001", "SC137690", "ZZ000001"])
def test_company_number_retains_text_identity(number: str) -> None:
    company = Company(company_id="test", company_number=number, company_name="SYNTHETIC")
    assert company.company_number == number
    assert isinstance(company.company_number, str)


@pytest.mark.parametrize("number", [12345678, "123", " unknown", "sc137690"])
def test_company_number_rejects_noncanonical_input(number: object) -> None:
    with pytest.raises(ValidationError):
        Company(company_id="test", company_number=number, company_name="SYNTHETIC")


def test_source_requires_original_reference(source: Source) -> None:
    data = source.model_dump()
    data["source_url"] = None
    with pytest.raises(ValidationError, match="source_url or source_identifier"):
        Source.model_validate(data)
    data["source_identifier"] = "synthetic-filing-identifier"
    assert Source.model_validate(data).source_identifier == "synthetic-filing-identifier"


def test_naive_timestamp_is_rejected_without_assuming_timezone(source: Source) -> None:
    data = source.model_dump()
    data["retrieved_at"] = datetime(2026, 1, 15, 12)
    with pytest.raises(ValidationError, match="timezone-aware"):
        Source.model_validate(data)


def test_aware_timestamp_normalizes_to_utc(source: Source) -> None:
    data = source.model_dump()
    data["retrieved_at"] = datetime(2026, 1, 15, 13, tzinfo=timezone(timedelta(hours=1)))
    result = Source.model_validate(data)
    assert result.retrieved_at == source.retrieved_at
    assert result.retrieved_at.tzinfo == UTC
    assert Source.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("location,document_id", [
    (ApiLocator(endpoint="/synthetic", json_path="$.status"), None),
    (IxbrlLocator(concept="test:Assets", context_id="period-test"), "doc-test"),
    (PdfLocator(page=1, label="Current assets"), "doc-test"),
])
def test_evidence_locators_roundtrip_with_source_identity(location: object, document_id: str | None) -> None:
    record = EvidenceReference(
        evidence_id="evidence-test", source_id="source-test", document_id=document_id,
        location=location,
    )
    assert EvidenceReference.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("location", [
    IxbrlLocator(concept="test:Assets", context_id="period-test"),
    PdfLocator(page=1, label="Current assets"),
])
def test_document_locator_without_document_is_rejected(location: object) -> None:
    with pytest.raises(ValidationError, match="document_id"):
        EvidenceReference(evidence_id="evidence-test", source_id="source-test", location=location)


@pytest.mark.parametrize("page", [0, -1, True])
def test_pdf_locator_requires_positive_integer_page(page: object) -> None:
    with pytest.raises(ValidationError):
        PdfLocator(page=page, label="SYNTHETIC")


def test_records_are_frozen_and_reject_extra_fields(source: Source) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        source.source_name = "changed"
    data = source.model_dump()
    data["risk_score"] = 50
    with pytest.raises(ValidationError, match="Extra inputs"):
        Source.model_validate(data)


def test_document_and_raw_metadata_link_to_retrieval(source: Source) -> None:
    document = Document(
        document_id="doc-test", company_id=source.company_id, company_number=source.company_number,
        source_id=source.source_id, document_type="ACCOUNTS", representation_type="PDF",
        period_start=date(2025, 1, 1), period_end=date(2025, 12, 31),
    )
    raw = RawEvidence(
        raw_evidence_id="raw-test", source_id=source.source_id, document_id=document.document_id,
        object_path="synthetic/raw.pdf", checksum="synthetic-checksum",
        retrieved_at=source.retrieved_at, processing_run_id=source.processing_run_id,
        media_type="application/pdf",
    )
    assert raw.source_id == document.source_id == source.source_id
    assert Document.model_validate_json(document.model_dump_json()) == document
    assert RawEvidence.model_validate_json(raw.model_dump_json()) == raw


def test_blank_identifiers_cannot_create_broken_provenance(source: Source) -> None:
    data = source.model_dump()
    data["source_id"] = "   "
    with pytest.raises(ValidationError, match="blank"):
        Source.model_validate(data)
