"""Exact scalar codecs. Database representations never enter domain models."""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
import re

from .connection import IntegrityError, SqlValue


def encode(value: object) -> SqlValue:
    """Encode a supported typed scalar or code tuple without float conversion."""
    if value is None:
        return None
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise IntegrityError("Non-finite Decimal cannot be stored")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise IntegrityError("Timestamp must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) in (str, int):
        return value
    raise IntegrityError("Unsupported persistence scalar type")


def text(value: SqlValue) -> str:
    """Require stored text without coercing numbers or NULL."""
    if not isinstance(value, str):
        raise IntegrityError("Expected stored TEXT")
    return value


def decimal_value(value: SqlValue) -> Decimal | None:
    """Restore finite Decimal, preserving digits and exponent exactly."""
    if value is None:
        return None
    raw = text(value)
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", raw):
        raise IntegrityError("Malformed stored Decimal")
    try:
        result = Decimal(raw)
    except InvalidOperation:
        raise IntegrityError("Malformed stored Decimal") from None
    if not result.is_finite():
        raise IntegrityError("Non-finite stored Decimal")
    return result


def date_value(value: SqlValue) -> date | None:
    """Restore only canonical ISO calendar dates, retaining NULL."""
    if value is None:
        return None
    raw = text(value)
    try:
        result = date.fromisoformat(raw)
    except ValueError:
        raise IntegrityError("Malformed stored date") from None
    if result.isoformat() != raw:
        raise IntegrityError("Noncanonical stored date")
    return result


def timestamp_value(value: SqlValue) -> datetime | None:
    """Restore canonical, aware UTC timestamps; never infer a missing timezone."""
    if value is None:
        return None
    raw = text(value)
    try:
        result = datetime.fromisoformat(raw)
    except ValueError:
        raise IntegrityError("Malformed stored timestamp") from None
    if result.tzinfo is None or encode(result) != raw:
        raise IntegrityError("Noncanonical stored UTC timestamp")
    return result.astimezone(UTC)


def boolean_value(value: SqlValue) -> bool | None:
    """Restore constrained integers only; reject strings and invalid integers."""
    if value is None:
        return None
    if type(value) is not int or value not in (0, 1):
        raise IntegrityError("Malformed stored boolean")
    return bool(value)


def codes_value(value: SqlValue) -> tuple[str, ...] | None:
    """Restore an ordered code collection, distinguishing empty from missing."""
    if value is None:
        return None
    try:
        result = json.loads(text(value))
    except (ValueError, TypeError):
        raise IntegrityError("Malformed stored codes") from None
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise IntegrityError("Stored codes must be an array of strings")
    return tuple(result)
