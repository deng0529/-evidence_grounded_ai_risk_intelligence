"""Allowlisted source observations, not risk interpretation or semantic validation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from risk_intelligence.domain.enums import AvailabilityStatus as Status
from risk_intelligence.domain.facts import BooleanValue, CodesValue, DateValue, FactValue, NumericValue, TextValue
from .client import ParseError
from .policy import Resource


@dataclass(frozen=True)
class Observation:
    """One typed, source-located observation scoped to a stable resource subject."""

    subject: str
    concept: str
    path: str
    value: FactValue
    status: Status


def text(value: object) -> str:
    """Require nonblank source text, never coerce a number/name into identity."""
    if not isinstance(value, str) or not value.strip():
        raise ParseError("Expected nonblank source text")
    return value


def source_date(value: object) -> date:
    """Parse an exact ISO source date without sentinel or partial-date inference."""
    try:
        result = date.fromisoformat(text(value))
        if result.isoformat() != value:
            raise ValueError()
        return result
    except ValueError:
        raise ParseError("Expected an exact ISO source date") from None


def get(item: dict[str, object], path: str) -> object:
    """Read optional nested source fields; a malformed parent is a parsing failure."""
    value: object = item
    for key in path.split("."):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ParseError("Unexpected nested source shape")
        value = value.get(key)
    return value


def _value(raw: object, kind: str) -> FactValue:
    if kind == "date":
        return DateValue(value=None if raw is None else source_date(raw))
    if kind == "bool":
        if raw is not None and type(raw) is not bool:
            raise ParseError("Expected source boolean")
        return BooleanValue(value=raw)
    if kind == "number":
        if raw is not None and (type(raw) is not int or raw < 0):
            raise ParseError("Expected nonnegative source integer")
        return NumericValue(value=None if raw is None else Decimal(raw))
    if kind == "codes":
        if raw is not None and not isinstance(raw, list):
            raise ParseError("Expected source code list")
        return CodesValue(value=None if raw is None else tuple(text(v) for v in raw))
    return TextValue(value=None if raw is None else text(raw))


# Each path is an intentional canonical observation, not a recursive JSON flatten.
FIELDS: dict[Resource, dict[str, str]] = {
    Resource.PROFILE: {
        **{key: "text" for key in ("company_number", "company_name", "company_status", "company_status_detail",
                                  "type", "subtype", "accounts.last_accounts.type")},
        **{key: "date" for key in ("date_of_creation", "date_of_cessation", "accounts.last_accounts.period_start_on",
            "accounts.last_accounts.period_end_on", "accounts.next_accounts.period_start_on",
            "accounts.next_accounts.period_end_on", "accounts.next_accounts.due_on",
            "confirmation_statement.last_made_up_to", "confirmation_statement.next_made_up_to",
            "confirmation_statement.next_due")},
        "accounts.next_accounts.overdue": "bool", "confirmation_statement.overdue": "bool", "sic_codes": "codes",
    },
    Resource.OFFICERS: {
        **{key: "text" for key in ("name", "officer_role", "nationality", "country_of_residence", "occupation",
                                  "appointed_before", "links.officer.appointments", "links.self")},
        "appointed_on": "date", "resigned_on": "date", "is_pre_1992_appointment": "bool",
    },
    Resource.PSC: {
        **{key: "text" for key in ("kind", "name", "nationality", "country_of_residence", "links.self",
            "identification.registration_number", "identification.place_registered", "identification.legal_form",
            "identification.legal_authority", "identification.country_registered")},
        "notified_on": "date", "ceased_on": "date", "ceased": "bool", "natures_of_control": "codes",
    },
    Resource.STATEMENTS: {
        **{key: "text" for key in ("statement", "kind", "linked_psc_name", "links.person_with_significant_control",
                                  "links.self", "restrictions_notice_withdrawal_reason")},
        "notified_on": "date", "ceased_on": "date", "restrictions_notice_withdrawal_date": "date",
    },
    Resource.FILINGS: {
        **{key: "text" for key in ("transaction_id", "category", "type", "description", "links.document_metadata", "links.self")},
        "date": "date", "action_date": "date", "paper_filed": "bool", "pages": "number",
    },
}


def subject_identity(resource: Resource, item: dict[str, object], number: str) -> str:
    """Use resource IDs, with appointment-event composite fallback, never a name."""
    if resource == Resource.PROFILE:
        if item.get("company_number") != number:
            raise ParseError("Profile company identity differs from requested identity")
        text(item.get("company_name"))
        return number
    if resource == Resource.FILINGS:
        return "filing:" + text(item.get("transaction_id"))
    self_link = get(item, "links.self")
    if self_link is not None:
        return text(self_link)
    if resource == Resource.OFFICERS:
        person = text(get(item, "links.officer.appointments"))
        role = text(item.get("officer_role"))
        anchor = item.get("appointed_on") or item.get("appointed_before")
        if anchor is None:
            raise ParseError("Appointment lacks a stable event identity")
        # Exclude mutable resigned_on, names and page position from identity.
        identity = json.dumps([person, role, text(anchor)], separators=(",", ":"))
        return "appointment:" + sha256(identity.encode()).hexdigest()
    raise ParseError("Resource lacks stable self identity")


def observations(resource: Resource, item: dict[str, object], number: str,
                 prefix: str = "$") -> list[Observation]:
    """Extract source fields with field-specific absent-date/type semantics."""
    subject = subject_identity(resource, item, number)
    fields = dict(FIELDS[resource])
    if resource == Resource.PROFILE:
        for key in ("registered_office_address", "accounts.accounting_reference_date", "links"):
            nested = item.get(key) if "." not in key else get(item, key)
            if nested is not None:
                if not isinstance(nested, dict):
                    raise ParseError("Expected profile metadata object")
                for name, value in nested.items():
                    if isinstance(value, str):
                        fields[key + "." + name] = "text"
    result: list[Observation] = []
    for path, kind in fields.items():
        raw = get(item, path)
        status = Status.AVAILABLE if raw is not None else Status.NOT_DISCLOSED
        if raw is None and path in ("resigned_on", "ceased_on"):
            status = Status.NOT_APPLICABLE
            if path == "ceased_on" and item.get("ceased") is True:
                status = Status.NOT_DISCLOSED
        if raw is None and resource == Resource.PSC and path.startswith("identification."):
            if "individual" in str(item.get("kind", "")):
                status = Status.NOT_APPLICABLE
        value = _value(raw, kind)
        concept = resource.name + "_" + path.upper().replace(".", "_")
        result.append(Observation(subject, concept, prefix + "." + path, value, status))
    # Selected compound event metadata remains individually located. Raw JSON is
    # still the source; these TEXT observations are clearly labelled JSON context.
    compound = ("annotations", "associated_filings", "resolutions", "description_values", "subcategory")
    if resource == Resource.FILINGS:
        for path in compound:
            if item.get(path) is not None:
                value = json.dumps(item[path], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                result.append(Observation(subject, "FILINGS_" + path.upper() + "_JSON", prefix + "." + path,
                                          TextValue(value=value), Status.AVAILABLE))
    return result


def page_items(data: dict[str, object], index: int) -> tuple[list[dict[str, object]], int]:
    """Require progressive pagination and an explicit population count, including zero."""
    items = data.get("items")
    total = data.get("total_results", data.get("total_count"))
    start = data.get("start_index")
    # Filing-history currently also emits digit strings for pagination fields.
    if isinstance(start, str) and start.isascii() and start.isdigit():
        start = int(start)
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ParseError("Expected resource items array")
    if type(total) is not int or total < 0 or type(start) is not int or start != index:
        raise ParseError("Invalid pagination count or progression")
    if index + len(items) > total or (not items and index < total):
        raise ParseError("Pagination is incomplete or inconsistent")
    return items, total
