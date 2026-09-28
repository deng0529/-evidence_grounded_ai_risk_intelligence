"""Typed source facts and explicit missing/candidate-value semantics."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from .common import CompanyNumber, Contract, ExactDecimal, Text
from .enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, FactType, PeriodType


class NumericValue(Contract):
    """An exact numeric value or an explicit typed null."""

    fact_type: Literal[FactType.NUMERIC] = FactType.NUMERIC
    value: ExactDecimal | None


class DateValue(Contract):
    """A calendar date, never a datetime or sentinel string."""

    fact_type: Literal[FactType.DATE] = FactType.DATE
    value: date | None


class TextValue(Contract):
    """Source text; missingness uses None rather than the UNKNOWN sentinel."""

    fact_type: Literal[FactType.TEXT] = FactType.TEXT
    value: Text | None

    @field_validator("value")
    @classmethod
    def reject_missing_sentinel(cls, value: str | None) -> str | None:
        """Keep missing-text representation consistent with the dictionary."""
        if value is not None and value.strip().upper() == "UNKNOWN":
            raise ValueError("use None and availability_status, not UNKNOWN")
        return value


class BooleanValue(Contract):
    """An explicit boolean observation; integers are not boolean evidence."""

    fact_type: Literal[FactType.BOOLEAN] = FactType.BOOLEAN
    value: bool | None


class CodesValue(Contract):
    """Immutable source code list, for example PSC nature-of-control labels."""

    fact_type: Literal[FactType.CODES] = FactType.CODES
    value: tuple[Text, ...] | None


FactValue = Annotated[
    NumericValue | DateValue | TextValue | BooleanValue | CodesValue,
    Field(discriminator="fact_type"),
]


def _check_availability(value: object, status: AvailabilityStatus) -> None:
    # Non-comparability does not invalidate the source fact itself. Failed
    # candidates live in a separate field, never in the usable value field.
    if status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.NON_COMPARABLE):
        if value is None:
            raise ValueError("AVAILABLE/NON_COMPARABLE facts require a typed value")
    elif value is not None:
        raise ValueError("unavailable facts require None; retain candidates separately")


class StructuredFact(Contract):
    """A typed source observation with evidence links and separate candidate data."""

    fact_id: Text
    company_id: Text
    company_number: CompanyNumber
    canonical_concept: Text
    value: FactValue
    availability_status: AvailabilityStatus
    source_id: Text
    document_id: Text | None = None
    evidence_ids: tuple[Text, ...] = ()
    extraction_method: ExtractionMethod
    processing_run_id: Text
    subject_identifier: Text | None = None
    candidate_value: FactValue | None = None

    @model_validator(mode="after")
    def check_value_and_provenance(self) -> Self:
        """Enforce structural usability without running evidence validation."""
        _check_availability(self.value.value, self.availability_status)
        if self.value.value is not None and not self.evidence_ids:
            raise ValueError("a present fact value requires evidence_ids")
        if self.candidate_value is not None:
            if self.candidate_value.fact_type != self.value.fact_type:
                raise ValueError("candidate and usable value must have the same fact_type")
            if self.candidate_value.value is None or not self.evidence_ids:
                raise ValueError("candidate requires a value and evidence_ids")
        return self


class ReportingPeriod(Contract):
    """Source reporting dates and comparability metadata; no trend logic."""

    period_type: PeriodType
    period_end: date
    period_start: date | None = None
    period_length_days: Annotated[int, Field(ge=1)] | None = None
    comparability_status: ComparabilityStatus

    @model_validator(mode="after")
    def check_period_shape(self) -> Self:
        """Require duration bounds but never derive missing reporting metadata."""
        if self.period_type == PeriodType.DURATION and self.period_start is None:
            raise ValueError("DURATION requires period_start")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start must not follow period_end")
        return self


class FinancialFact(Contract):
    """Dictionary financial fact retaining exact amounts and source provenance."""

    financial_fact_id: Text
    company_id: Text
    company_number: CompanyNumber
    canonical_concept: Text
    source_concept: Text | None = None
    value_numeric: ExactDecimal | None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    unit: Text | None = None
    period: ReportingPeriod | None = None
    source_id: Text
    document_id: Text | None = None
    evidence_ids: tuple[Text, ...] = ()
    extraction_method: ExtractionMethod
    availability_status: AvailabilityStatus
    processing_run_id: Text
    candidate_value_numeric: ExactDecimal | None = None

    @model_validator(mode="after")
    def check_value_and_provenance(self) -> Self:
        """Missing evidence may lack period/unit; present values must be traceable."""
        _check_availability(self.value_numeric, self.availability_status)
        if self.value_numeric is not None or self.candidate_value_numeric is not None:
            if not self.evidence_ids:
                raise ValueError("present or candidate financial value requires evidence_ids")
        if self.value_numeric is not None:
            if self.period is None or self.unit is None:
                raise ValueError("present financial value requires period and unit")
        return self
