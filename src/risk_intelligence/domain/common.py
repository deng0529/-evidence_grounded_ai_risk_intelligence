"""Shared structural invariants; no evidence or risk scoring logic."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, ValidationInfo


def _reject_inexact_number(value: object, info: ValidationInfo) -> object:
    # Float-to-Decimal conversion cannot recover precision already lost upstream.
    if isinstance(value, (float, bool)):
        raise ValueError("use Decimal, not float or bool, for exact numeric values")
    # JSON has no Decimal type. Decode our decimal-string wire format explicitly;
    # Python callers still have to supply Decimal rather than numeric strings.
    if info.mode == "json" and isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as error:
            raise ValueError("expected an exact decimal string") from error
    return value


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware; UTC cannot be inferred")
    return value.astimezone(UTC)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


Text = Annotated[str, Field(min_length=1), AfterValidator(_not_blank)]
# Company identity stays text to retain leading zeroes and alphabetic prefixes.
CompanyNumber = Annotated[str, Field(pattern=r"^[A-Z0-9]{8}$")]
ExactDecimal = Annotated[
    Decimal, BeforeValidator(_reject_inexact_number), Field(allow_inf_nan=False)
]
UnitInterval = Annotated[ExactDecimal, Field(ge=Decimal("0"), le=Decimal("1"))]
NonNegativeDecimal = Annotated[ExactDecimal, Field(ge=Decimal("0"))]
UtcTimestamp = Annotated[datetime, AfterValidator(_utc_timestamp)]


class Contract(BaseModel):
    """Immutable, strict record rejecting unknown fields and implicit coercion.

    JSON uses ISO dates/timestamps and decimal strings via Pydantic's explicit
    model_dump_json/model_validate_json boundary. Normal constructors require
    typed Python values. Nested collections use tuples to prevent mutation.
    """

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", validate_default=True,
        revalidate_instances="always", hide_input_in_errors=True,
    )
