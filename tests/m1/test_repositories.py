"""Meaningful exact-type, missingness and provenance repository integration tests."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import (
    AssessmentStatus, AvailabilityStatus, ExtractionMethod, ProcessingStatus,
)
from risk_intelligence.domain.evidence import ApiLocator, Company, EvidenceReference, PdfLocator
from risk_intelligence.domain.facts import (
    BooleanValue, CodesValue, DateValue, FinancialFact, NumericValue, StructuredFact, TextValue,
)
from risk_intelligence.domain.runs import Assessment, ProcessingRun
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError, PersistenceError
from risk_intelligence.persistence.evidence_repositories import (
    SqlDocumentRepository, SqlEvidenceReferenceRepository, SqlRawEvidenceRepository, SqlSourceRepository,
)
from risk_intelligence.persistence.fact_repositories import SqlFinancialFactRepository, SqlStructuredFactRepository
from risk_intelligence.persistence.mapping import (
    boolean_value, codes_value, date_value, decimal_value, encode, timestamp_value,
)

from conftest import EvidenceChain


def test_all_metadata_round_trips_and_missing_identity(database: Database, chain: EvidenceChain) -> None:
    assert SqlCompanyRepository(database).get_by_company_number("ZZ000001") == chain.company
    assert SqlCompanyRepository(database).get_by_company_number("ZZ999999") is None
    for repository, identity, record in (
        (SqlSourceRepository(database), chain.source.source_id, chain.source),
        (SqlDocumentRepository(database), chain.document.document_id, chain.document),
        (SqlRawEvidenceRepository(database), chain.raw.raw_evidence_id, chain.raw),
        (SqlEvidenceReferenceRepository(database), chain.reference.evidence_id, chain.reference),
    ):
        assert repository.get(identity) == record
        assert repository.get("absent") is None
        repository.save(identity, record)
        with pytest.raises(IntegrityError, match="ID"):
            repository.save("different-id", record)


def test_company_updates_profile_but_not_identity(database: Database, chain: EvidenceChain) -> None:
    repository = SqlCompanyRepository(database)
    updated = Company.model_validate(chain.company.model_dump() | {"company_name": "SYNTHETIC NEW NAME"})
    repository.save(updated)
    assert repository.get_by_company_number("ZZ000001") == updated
    with pytest.raises(IntegrityError):
        repository.save(Company.model_validate(updated.model_dump() | {"company_number": "ZZ000002"}))


@pytest.mark.parametrize("number", ["12345.6700", "0", "-0.000", "1E+20", "1.2300E-30",
                                   "999999999999999999999999999999999999999999.000001"])
def test_decimal_round_trip_preserves_type_digits_and_exponent(
    database: Database, chain: EvidenceChain, financial_fact: FinancialFact, number: str,
) -> None:
    fact = FinancialFact.model_validate(financial_fact.model_dump() | {"value_numeric": Decimal(number)})
    repository = SqlFinancialFactRepository(database)
    repository.save(fact.financial_fact_id, fact)
    restored = repository.get(fact.financial_fact_id)
    assert restored == fact
    assert isinstance(restored.value_numeric, Decimal)
    assert restored.value_numeric.as_tuple() == Decimal(number).as_tuple()
    assert database.query("SELECT value_numeric, typeof(value_numeric) AS kind FROM fact") == [
        {"value_numeric": str(Decimal(number)), "kind": "text"}]


@pytest.mark.parametrize("status", list(AvailabilityStatus))
def test_every_missingness_status_and_candidate_remains_separate(
    database: Database, chain: EvidenceChain, financial_fact: FinancialFact, status: AvailabilityStatus,
) -> None:
    present = status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.NON_COMPARABLE)
    fact = FinancialFact.model_validate(financial_fact.model_dump() | {
        "availability_status": status, "value_numeric": Decimal("0") if present else None,
        "candidate_value_numeric": None if present else Decimal("99.9900"),
    })
    repository = SqlFinancialFactRepository(database)
    repository.save(fact.financial_fact_id, fact)
    assert repository.get(fact.financial_fact_id) == fact
    stored = database.query("SELECT value_numeric, candidate_numeric, availability_status FROM fact")[0]
    assert stored == {"value_numeric": "0" if present else None,
                      "candidate_numeric": None if present else "99.9900", "availability_status": status.value}


@pytest.mark.parametrize("value", [NumericValue(value=Decimal("1.2300")), DateValue(value=date(2025, 2, 3)),
                                    TextValue(value="SYNTHETIC statement"), BooleanValue(value=False),
                                    BooleanValue(value=True), CodesValue(value=("control-a", "control-b")),
                                    CodesValue(value=())])
def test_structured_fact_variants_ordered_links_and_reverse_lookup(
    database: Database, chain: EvidenceChain, value: object,
) -> None:
    fact = StructuredFact(
        fact_id="structured-test", company_id=chain.company.company_id, company_number=chain.company.company_number,
        canonical_concept="SYNTHETIC", value=value, availability_status=AvailabilityStatus.AVAILABLE,
        source_id=chain.source.source_id, document_id=chain.document.document_id,
        evidence_ids=(chain.reference.evidence_id, chain.reference.evidence_id),
        extraction_method=ExtractionMethod.API_DIRECT, processing_run_id=chain.run.processing_run_id,
        subject_identifier="synthetic-subject",
    )
    repository = SqlStructuredFactRepository(database)
    repository.save(fact.fact_id, fact)
    assert repository.get(fact.fact_id) == fact
    assert repository.fact_ids_for_evidence(chain.reference.evidence_id) == (fact.fact_id,)
    repository.save(fact.fact_id, fact)
    with pytest.raises(IntegrityError):
        repository.save(fact.fact_id, StructuredFact.model_validate(fact.model_dump() | {"evidence_ids": ("evidence-test",)}))
    with pytest.raises(IntegrityError, match="kind"):
        SqlFinancialFactRepository(database).get(fact.fact_id)


@pytest.mark.parametrize("value", [NumericValue(value=None), DateValue(value=None), TextValue(value=None),
                                    BooleanValue(value=None), CodesValue(value=None)])
def test_typed_null_structured_facts(database: Database, chain: EvidenceChain, value: object) -> None:
    fact = StructuredFact(fact_id="null-test", company_id=chain.company.company_id,
                          company_number=chain.company.company_number, canonical_concept="SYNTHETIC",
                          value=value, availability_status=AvailabilityStatus.NOT_DISCLOSED,
                          source_id=chain.source.source_id, extraction_method=ExtractionMethod.API_DIRECT,
                          processing_run_id=chain.run.processing_run_id)
    repository = SqlStructuredFactRepository(database)
    repository.save(fact.fact_id, fact)
    assert repository.get(fact.fact_id) == fact
    assert database.query("SELECT value_numeric, value_date, value_text, value_boolean, value_codes_json FROM fact") == [
        dict.fromkeys(("value_numeric", "value_date", "value_text", "value_boolean", "value_codes_json"))]


def test_assessment_and_processing_lifecycle_are_metadata_only(database: Database, chain: EvidenceChain) -> None:
    repository = SqlAssessmentRepository(database)
    assert repository.get_processing_run(chain.run.processing_run_id) == chain.run
    assert repository.get_processing_run("absent") is None
    run = ProcessingRun.model_validate(chain.run.model_dump() | {
        "completed_at": chain.run.started_at + timedelta(seconds=2), "status": ProcessingStatus.COMPLETE,
    })
    repository.save_processing_run(run)
    repository.save_processing_run(run)
    assert repository.get_processing_run(run.processing_run_id) == run
    with pytest.raises(IntegrityError, match="Finalized"):
        repository.save_processing_run(chain.run)
    assessment = Assessment(
        assessment_id="assessment-test", company_id=chain.company.company_id, company_number=chain.company.company_number,
        processing_run_id=run.processing_run_id, assessment_date=date(2026, 1, 15), data_current_to=date(2025, 12, 31),
        status=AssessmentStatus.PARTIAL, risk_model_version="1", reliability_model_version="1",
        er_model_version="1", data_dictionary_version="1.0",
    )
    repository.save_assessment(assessment)
    assert repository.get_assessment(assessment.assessment_id) == assessment
    assert repository.get_assessment("absent") is None
    with pytest.raises(IntegrityError):
        repository.save_assessment(Assessment.model_validate(assessment.model_dump() | {"status": AssessmentStatus.COMPLETE}))


def test_immutable_history_and_cross_company_lineage(database: Database, chain: EvidenceChain,
                                                   financial_fact: FinancialFact) -> None:
    repository = SqlFinancialFactRepository(database)
    repository.save(financial_fact.financial_fact_id, financial_fact)
    with pytest.raises(IntegrityError):
        repository.save(financial_fact.financial_fact_id,
                        FinancialFact.model_validate(financial_fact.model_dump() | {"value_numeric": Decimal("1")}))
    with pytest.raises(PersistenceError):
        database.execute("DELETE FROM source WHERE source_id=?", (chain.source.source_id,))
    with pytest.raises(PersistenceError):
        database.execute("UPDATE fact SET value_numeric='1' WHERE fact_id=?", (financial_fact.financial_fact_id,))
    other = Company(company_id="other", company_number="ZZ000002", company_name="SYNTHETIC OTHER")
    SqlCompanyRepository(database).save(other)
    wrong = FinancialFact.model_validate(financial_fact.model_dump() | {
        "financial_fact_id": "cross-company", "company_id": other.company_id, "company_number": other.company_number,
    })
    with pytest.raises(PersistenceError):
        repository.save(wrong.financial_fact_id, wrong)
    assert repository.get(wrong.financial_fact_id) is None


@pytest.mark.parametrize("location", [ApiLocator(endpoint="/synthetic", json_path="$.value"),
                                       PdfLocator(page=2, label="Synthetic", section="Balance sheet", table="Assets")])
def test_locator_variants(database: Database, chain: EvidenceChain, location: object) -> None:
    reference = EvidenceReference(evidence_id="another", source_id=chain.source.source_id,
                                  document_id=chain.document.document_id, location=location)
    repository = SqlEvidenceReferenceRepository(database)
    repository.save(reference.evidence_id, reference)
    assert repository.get(reference.evidence_id) == reference


@pytest.mark.parametrize("decoder,value", [
    (decimal_value, 1), (decimal_value, "NaN"), (decimal_value, "UNKNOWN"),
    (date_value, "20250101"), (date_value, "2025-13-01"),
    (timestamp_value, "2026-01-01T00:00:00"), (boolean_value, 2), (boolean_value, "1"),
    (codes_value, '{"code":1}'), (codes_value, '[1]'),
])
def test_malformed_stored_scalars_fail_explicitly(decoder: object, value: object) -> None:
    with pytest.raises(IntegrityError):
        decoder(value)


def test_utc_codec_normalizes_offset_without_clock_or_rounding() -> None:
    value = datetime(2026, 1, 1, 13, 2, 3, 456789, tzinfo=timezone(timedelta(hours=1)))
    encoded = encode(value)
    assert encoded == "2026-01-01T12:02:03.456789Z"
    assert timestamp_value(encoded) == value
    assert timestamp_value(encoded).tzinfo is UTC
    with pytest.raises(IntegrityError):
        encode(datetime(2026, 1, 1))
    with pytest.raises(IntegrityError):
        encode(1.23)


def test_corrupt_stored_fact_is_not_silently_repaired(database: Database, chain: EvidenceChain,
                                                     financial_fact: FinancialFact) -> None:
    repository = SqlFinancialFactRepository(database)
    repository.save(financial_fact.financial_fact_id, financial_fact)
    database.execute("DROP TRIGGER fact_no_update")
    database.execute("UPDATE fact SET value_numeric='not-a-number'")
    with pytest.raises(IntegrityError):
        repository.get(financial_fact.financial_fact_id)


def test_distinct_evidence_order_survives_round_trip(database: Database, chain: EvidenceChain,
                                                   financial_fact: FinancialFact) -> None:
    second = EvidenceReference.model_validate(chain.reference.model_dump() | {"evidence_id": "evidence-second"})
    SqlEvidenceReferenceRepository(database).save(second.evidence_id, second)
    fact = FinancialFact.model_validate(financial_fact.model_dump() | {
        "evidence_ids": (second.evidence_id, chain.reference.evidence_id),
    })
    repository = SqlFinancialFactRepository(database)
    repository.save(fact.financial_fact_id, fact)
    assert repository.get(fact.financial_fact_id).evidence_ids == (second.evidence_id, chain.reference.evidence_id)


def test_structured_candidate_is_not_promoted(database: Database, chain: EvidenceChain) -> None:
    fact = StructuredFact(fact_id="candidate-test", company_id=chain.company.company_id,
                          company_number=chain.company.company_number, canonical_concept="SYNTHETIC_DATE",
                          value=DateValue(value=None), candidate_value=DateValue(value=date(2025, 1, 1)),
                          availability_status=AvailabilityStatus.EXTRACTION_FAILED,
                          source_id=chain.source.source_id, evidence_ids=(chain.reference.evidence_id,),
                          extraction_method=ExtractionMethod.API_DIRECT, processing_run_id=chain.run.processing_run_id)
    repository = SqlStructuredFactRepository(database)
    repository.save(fact.fact_id, fact)
    restored = repository.get(fact.fact_id)
    assert restored == fact and restored.value.value is None
    assert database.query("SELECT value_date, candidate_date FROM fact") == [
        {"value_date": None, "candidate_date": "2025-01-01"}]


def test_unknown_stored_enum_fails_instead_of_defaulting(database: Database, chain: EvidenceChain) -> None:
    database.execute("DROP TRIGGER source_no_update")
    database.execute("PRAGMA ignore_check_constraints=ON")
    database.execute("UPDATE source SET retrieval_status='UNKNOWN_STATUS'")
    with pytest.raises(IntegrityError):
        SqlSourceRepository(database).get(chain.source.source_id)


def test_active_run_rejects_identity_and_start_changes(database: Database, chain: EvidenceChain) -> None:
    changed = ProcessingRun.model_validate(chain.run.model_dump() | {"app_version": "different-version"})
    with pytest.raises(IntegrityError, match="identity/start/version"):
        SqlAssessmentRepository(database).save_processing_run(changed)
