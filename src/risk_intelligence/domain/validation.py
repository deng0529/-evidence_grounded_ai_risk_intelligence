"""Historical validation records and immutable M4 rule execution contracts."""

from datetime import date
from typing import Self

from pydantic import model_validator

from .common import CompanyNumber, Contract, NonNegativeDecimal, Text, UtcTimestamp
from .enums import (AdmissibilityReason, AvailabilityStatus, EvidenceUse, Severity,
                    ValidationRole, ValidationStatus, ValidationStrength, ValidationType)
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


class ValidationField(Contract):
    """Named immutable typed input/detail; a missing value remains typed None."""

    name: Text
    value: FactValue


class AdmissionFailure(Contract):
    """Typed exclusion and explanation, without inventing an analytical value."""

    code: AdmissibilityReason
    reason: Text
    evidence_ids: tuple[Text, ...] = ()


class AnalyticalInput(Contract):
    """Explicit in-memory assessment context; no loading or source interpretation.

    Input type selects rule applicability. Fields supply typed data for generic
    rules; later domain contexts may extend this contract. Evidence IDs enumerate
    the supplied evidence population, with construction evidence marked separately.
    """

    input_id: Text
    input_type: Text
    company_number: CompanyNumber
    assessment_date: date
    availability_status: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    fields: tuple[ValidationField, ...] = ()
    evidence_ids: tuple[Text, ...] = ()
    construction_evidence_ids: tuple[Text, ...] = ()
    admission_failures: tuple[AdmissionFailure, ...] = ()

    @model_validator(mode='after')
    def check_identity(self) -> Self:
        """Reject ambiguous names and references outside the provided population."""
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError('Duplicate validation input field')
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError('Duplicate input evidence ID')
        referenced = set(self.construction_evidence_ids)
        referenced.update(e for failure in self.admission_failures for e in failure.evidence_ids)
        if not referenced <= set(self.evidence_ids):
            raise ValueError('Input references evidence outside its population')
        return self


class RuleDefinition(Contract):
    """Stable registration identity; applicability is an explicit input-type list."""

    rule_id: Text
    rule_version: Text
    applies_to: tuple[Text, ...]
    required_inputs: tuple[Text, ...] = ()
    role: ValidationRole

    @model_validator(mode='after')
    def check_names(self) -> Self:
        """An empty applicability list or duplicate requirement is a configuration error."""
        if not self.applies_to or len(set(self.applies_to)) != len(self.applies_to):
            raise ValueError('Require distinct applicable input types')
        if len(set(self.required_inputs)) != len(self.required_inputs):
            raise ValueError('Duplicate required input')
        return self


class RuleOutcome(Contract):
    """One rule execution, separate from legacy persisted ValidationResult identity."""

    rule_id: Text
    rule_version: Text
    result: ValidationStatus
    role: ValidationRole
    validation_strength_candidate: ValidationStrength = ValidationStrength.NONE
    evidence_use: EvidenceUse = EvidenceUse.ADMISSION_ONLY
    independence_group: Text | None = None
    evidence_ids: tuple[Text, ...] = ()
    reason: Text
    structured_details: tuple[ValidationField, ...] = ()
    failure_code: AdmissibilityReason | None = None

    @property
    def hard_fail(self) -> bool:
        """A failed or unresolved mandatory gate withholds analytical evidence."""
        return self.role == ValidationRole.HARD_FAIL and self.result in (
            ValidationStatus.FAIL, ValidationStatus.INCONCLUSIVE)

    @model_validator(mode='after')
    def check_outcome(self) -> Self:
        """Preserve four M4 outcomes while keeping legacy WARNING readable elsewhere."""
        if self.result == ValidationStatus.WARNING:
            raise ValueError('M4 requires PASS/FAIL/INCONCLUSIVE/NOT_APPLICABLE')
        if self.hard_fail != (self.failure_code is not None):
            raise ValueError('Active hard failure requires a typed failure code, and only then')
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError('Duplicate outcome evidence ID')
        if len({field.name for field in self.structured_details}) != len(self.structured_details):
            raise ValueError('Duplicate outcome detail')
        if self.validation_strength_candidate != ValidationStrength.NONE and (
                self.result != ValidationStatus.PASS or self.role != ValidationRole.SUPPORT
                or not self.evidence_ids or self.independence_group is None):
            raise ValueError('Support candidate requires PASS, SUPPORT, evidence and independence group')
        return self


class ValidationReport(Contract):
    """Versioned engine output preserving input context, diagnostics and exclusions."""

    context: AnalyticalInput
    ruleset_version: Text
    outcomes: tuple[RuleOutcome, ...]
    failures: tuple[AdmissionFailure, ...]

    @model_validator(mode='after')
    def check_exclusions(self) -> Self:
        """Serialized reports cannot drop mandatory exclusions or invent evidence."""
        identities = {(o.rule_id, o.rule_version) for o in self.outcomes}
        if len(identities) != len(self.outcomes):
            raise ValueError('Duplicate validation outcome identity')
        required = set(self.context.admission_failures)
        required.update(AdmissionFailure(code=o.failure_code, reason=o.reason, evidence_ids=o.evidence_ids)
                        for o in self.outcomes if o.hard_fail)
        if not required <= set(self.failures):
            raise ValueError('Validation report dropped an admission failure')
        if (self.context.availability_status != AvailabilityStatus.AVAILABLE or not self.context.evidence_ids) and not self.failures:
            raise ValueError('Unavailable analytical evidence cannot be admitted')
        references = {e for o in self.outcomes for e in o.evidence_ids}
        references.update(e for f in self.failures for e in f.evidence_ids)
        if not references <= set(self.context.evidence_ids):
            raise ValueError('Report references evidence outside supplied population')
        return self

    @property
    def admissible(self) -> bool:
        """No numeric evidence may be admitted while an exclusion remains."""
        return not self.failures

    @property
    def support_outcomes(self) -> tuple[RuleOutcome, ...]:
        """Expose support diagnostics; the V classifier still checks independence."""
        return tuple(outcome for outcome in self.outcomes if outcome.role == ValidationRole.SUPPORT)
