"""Typed-null, exact-value and provenance semantics without scoring."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from risk_intelligence.domain.enums import AvailabilityStatus, ExtractionMethod
from risk_intelligence.domain.facts import (
    BooleanValue, CodesValue, DateValue, FinancialFact, NumericValue,
    ReportingPeriod, StructuredFact, TextValue,
)


@pytest.mark.parametrize("value", ["UNKNOWN", 1.25, True, "123.45", Decimal("NaN"), Decimal("Infinity")])
def test_financial_fact_rejects_inexact_or_untyped_numeric_value(
    financial_fact: FinancialFact, value: object,
) -> None:
    data = financial_fact.model_dump()
    data["value_numeric"] = value
    with pytest.raises(ValidationError):
        FinancialFact.model_validate(data)


def test_missing_financial_fact_uses_none_not_unknown_string(financial_fact: FinancialFact) -> None:
    data = financial_fact.model_dump()
    data.update(value_numeric=None, availability_status=AvailabilityStatus.NOT_DISCLOSED)
    missing = FinancialFact.model_validate(data)
    assert missing.value_numeric is None
    assert '"value_numeric":null' in missing.model_dump_json()
    assert "UNKNOWN" not in missing.model_dump_json()
    assert financial_fact.value_numeric == Decimal("12345.6700")


@pytest.mark.parametrize("status", [
    AvailabilityStatus.NOT_DISCLOSED, AvailabilityStatus.NOT_APPLICABLE,
    AvailabilityStatus.RETRIEVAL_FAILED, AvailabilityStatus.EXTRACTION_FAILED,
    AvailabilityStatus.VALIDATION_FAILED, AvailabilityStatus.CONFLICT_UNRESOLVED,
])
def test_unavailable_fact_never_promotes_present_value(
    financial_fact: FinancialFact, status: AvailabilityStatus,
) -> None:
    data = financial_fact.model_dump()
    data["availability_status"] = status
    with pytest.raises(ValidationError, match="unavailable facts require None"):
        FinancialFact.model_validate(data)
    data["value_numeric"] = None
    assert FinancialFact.model_validate(data).value_numeric is None


@pytest.mark.parametrize("status", [AvailabilityStatus.AVAILABLE, AvailabilityStatus.NON_COMPARABLE])
def test_present_source_fact_status_requires_value(
    financial_fact: FinancialFact, status: AvailabilityStatus,
) -> None:
    data = financial_fact.model_dump()
    data.update(availability_status=status, value_numeric=None)
    with pytest.raises(ValidationError, match="require a typed value"):
        FinancialFact.model_validate(data)


def test_noncomparable_source_fact_retains_value(financial_fact: FinancialFact) -> None:
    data = financial_fact.model_dump()
    data["availability_status"] = AvailabilityStatus.NON_COMPARABLE
    assert FinancialFact.model_validate(data).value_numeric == financial_fact.value_numeric


def test_failed_candidate_is_retained_separately(financial_fact: FinancialFact) -> None:
    data = financial_fact.model_dump()
    data.update(value_numeric=None, candidate_value_numeric=Decimal("125.50"),
                availability_status=AvailabilityStatus.VALIDATION_FAILED)
    rejected = FinancialFact.model_validate(data)
    assert rejected.value_numeric is None
    assert rejected.candidate_value_numeric == Decimal("125.50")


@pytest.mark.parametrize("field,value", [("evidence_ids", ()), ("unit", None), ("period", None)])
def test_present_financial_fact_requires_context(
    financial_fact: FinancialFact, field: str, value: object,
) -> None:
    data = financial_fact.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        FinancialFact.model_validate(data)


def test_missing_fact_can_record_failed_retrieval_without_fabricated_evidence(
    financial_fact: FinancialFact,
) -> None:
    data = financial_fact.model_dump()
    data.update(value_numeric=None, availability_status=AvailabilityStatus.RETRIEVAL_FAILED,
                evidence_ids=(), document_id=None, period=None, unit=None)
    result = FinancialFact.model_validate(data)
    assert result.source_id == "source-test"
    assert not result.evidence_ids


def test_money_roundtrip_preserves_decimal_digits(financial_fact: FinancialFact) -> None:
    serialized = financial_fact.model_dump_json()
    assert '"12345.6700"' in serialized
    restored = FinancialFact.model_validate_json(serialized)
    assert restored == financial_fact
    assert restored.value_numeric.as_tuple() == Decimal("12345.6700").as_tuple()


def test_json_float_does_not_bypass_exact_numeric_contract(financial_fact: FinancialFact) -> None:
    serialized = financial_fact.model_dump_json().replace('"12345.6700"', "12345.67")
    with pytest.raises(ValidationError, match="not float"):
        FinancialFact.model_validate_json(serialized)


@pytest.mark.parametrize("value", ["UNKNOWN", "2025-01-01", datetime(2025, 1, 1)])
def test_python_date_contract_rejects_sentinels_and_datetime(value: object) -> None:
    with pytest.raises(ValidationError):
        DateValue(value=value)


def test_iso_date_roundtrip_preserves_calendar_date() -> None:
    value = DateValue(value=date(2025, 1, 1))
    assert DateValue.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("value", ["UNKNOWN", " unknown "])
def test_missing_text_cannot_use_unknown_sentinel(value: str) -> None:
    with pytest.raises(ValidationError, match="use None"):
        TextValue(value=value)


@pytest.mark.parametrize("value", [1, "true", 0])
def test_boolean_value_rejects_coercion(value: object) -> None:
    with pytest.raises(ValidationError):
        BooleanValue(value=value)


@pytest.mark.parametrize("value", [
    NumericValue(value=Decimal("0")), DateValue(value=date(2025, 1, 1)),
    BooleanValue(value=False), TextValue(value="source statement"),
    CodesValue(value=("ownership-of-shares-25-to-50-percent",)),
])
def test_structured_value_variants_roundtrip_without_type_loss(value: object) -> None:
    fact = StructuredFact(
        fact_id="fact-test", company_id="company-test", company_number="ZZ000001",
        canonical_concept="SYNTHETIC_CONCEPT", value=value,
        availability_status=AvailabilityStatus.AVAILABLE, source_id="source-test",
        evidence_ids=("evidence-test",), extraction_method=ExtractionMethod.API_DIRECT,
        processing_run_id="run-test",
    )
    assert StructuredFact.model_validate_json(fact.model_dump_json()) == fact


def test_structured_fact_rejects_untraceable_value() -> None:
    with pytest.raises(ValidationError, match="evidence_ids"):
        StructuredFact(
            fact_id="fact-test", company_id="company-test", company_number="ZZ000001",
            canonical_concept="DIRECTOR_ACTIVE_STATUS", value=BooleanValue(value=True),
            availability_status=AvailabilityStatus.AVAILABLE, source_id="source-test",
            extraction_method=ExtractionMethod.API_DIRECT, processing_run_id="run-test",
        )


def test_date_null_can_represent_not_applicable_governance_field() -> None:
    fact = StructuredFact(
        fact_id="fact-test", company_id="company-test", company_number="ZZ000001",
        canonical_concept="DIRECTOR_RESIGNED_ON", value=DateValue(value=None),
        availability_status=AvailabilityStatus.NOT_APPLICABLE, source_id="source-test",
        extraction_method=ExtractionMethod.API_DIRECT, processing_run_id="run-test",
    )
    assert fact.value.value is None


def test_period_rejects_reversed_dates(financial_fact: FinancialFact) -> None:
    data = financial_fact.period.model_dump()
    data["period_start"] = date(2026, 1, 1)
    with pytest.raises(ValidationError, match="period_start"):
        ReportingPeriod.model_validate(data)
