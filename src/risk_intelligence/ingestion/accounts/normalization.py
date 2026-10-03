"""Canonical financial-value normalization before structured persistence.

Extraction routes retain their immutable source representation (raw_value, label,
locator, parser/LLM method).  This module applies only source-supported,
deterministic cleaning needed to make admitted monetary observations comparable
before they are mapped into canonical Turso facts.
"""

from decimal import Decimal
from hashlib import sha256

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.domain.facts import FinancialFact
from .models import SourceFinancialFact

NORMALIZATION_VERSION = "financial-normalization-v1"

_CURRENT_LIABILITY_LABELS = {
    "current liabilities",
    "creditors: amounts falling due within one year",
    "creditors: amounts falling due within 1 year",
}


def _zero(value: Decimal) -> Decimal:
    """Canonicalise signed zero without changing precision of non-zero values."""
    return abs(value) if value == 0 else value


def normalize_source_fact(fact: SourceFinancialFact) -> SourceFinancialFact:
    """Return a cleaned source observation while preserving raw provenance.

    Parsers already expand scale (for example £000) into ``value``.  We never
    re-parse or overwrite ``raw_value`` here.  The only sign normalization is a
    reviewed accounting presentation rule: a parenthesized current-liability
    subtotal is a positive obligation even though it is printed as a deduction
    on the balance sheet.  Net liabilities remain negative by design.
    """
    if fact.availability_status not in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.NON_COMPARABLE):
        return fact
    if fact.value is None:
        return fact
    value = _zero(fact.value)
    transformation = fact.transformation
    label = (fact.source_label or "").strip().lower()
    raw = (fact.raw_value or "").strip()
    if label in _CURRENT_LIABILITY_LABELS and raw.startswith("(") and raw.endswith(")"):
        value = value.copy_abs()
        transformation = transformation or "balance-sheet-creditor-deduction"
    elif label == "net liabilities" and value > 0:
        value = value.copy_negate()
        transformation = transformation or "net-liabilities-sign"
    return fact.model_copy(update={
        "value": value,
        "currency": fact.currency.upper() if fact.currency else None,
        "unit": fact.unit.upper() if fact.unit and len(fact.unit) == 3 else fact.unit,
        "sign": "-" if value < 0 else "+",
        "transformation": transformation,
    })


def normalize_canonical_fact(fact: FinancialFact, source: SourceFinancialFact) -> FinancialFact:
    """Final canonical guard immediately before Turso persistence.

    This deliberately does not infer missing values, currencies, periods or
    concepts.  It only enforces the same reviewed normalization on a mapped
    monetary fact and versions a changed canonical identity so immutable old
    observations can coexist with corrected normalization.
    """
    if fact.value_numeric is None:
        return fact
    value = _zero(fact.value_numeric)
    label = (source.source_label or "").strip().lower()
    raw = (source.raw_value or "").strip()
    if fact.canonical_concept == "CURRENT_LIABILITIES" and label in _CURRENT_LIABILITY_LABELS \
            and raw.startswith("(") and raw.endswith(")"):
        value = value.copy_abs()
    if value == fact.value_numeric:
        return fact
    identity = sha256(f"{fact.financial_fact_id}:{NORMALIZATION_VERSION}:{value}".encode()).hexdigest()
    return fact.model_copy(update={"financial_fact_id": identity, "value_numeric": value})


def normalization_rule(source: SourceFinancialFact, canonical: FinancialFact) -> str:
    """Human-readable immutable audit description for one direct observation."""
    label = (source.source_label or "").strip().lower()
    raw = (source.raw_value or "").strip()
    if canonical.canonical_concept == "CURRENT_LIABILITIES" and label in _CURRENT_LIABILITY_LABELS \
            and raw.startswith("(") and raw.endswith(")"):
        return "parenthesized balance-sheet current-liability deduction -> positive obligation"
    if label == "net liabilities":
        return "net liabilities -> negative net-assets amount"
    if source.scale:
        return f"source monetary scale 10^{source.scale} already expanded by extractor"
    return "identity; exact admitted monetary value"
