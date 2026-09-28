"""Validation findings as records, without a validation engine."""

from .common import Contract, NonNegativeDecimal, Text, UtcTimestamp
from .enums import Severity, ValidationStatus, ValidationType
from .facts import FactValue


class ValidationResult(Contract):
    """A future rule's diagnostic result, kept separate from its input fact."""

    validation_id: Text
    fact_id: Text
    validation_type: ValidationType
    rule_code: Text
    status: ValidationStatus
    severity: Severity
    validated_at: UtcTimestamp
    processing_run_id: Text
    expected_value: FactValue | None = None
    observed_value: FactValue | None = None
    tolerance: NonNegativeDecimal | None = None
    details: Text | None = None
