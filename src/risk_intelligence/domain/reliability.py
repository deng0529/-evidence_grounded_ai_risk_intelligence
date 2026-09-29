"""Evidence quality result contracts; no S/E/V/C/r computation."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import Contract, Text, UnitInterval, UtcTimestamp
from .enums import ConflictLevel, ConflictResolution, CriticalTransformation, SourceType, ValidationStrength
from .validation import AdmissionFailure, RuleOutcome, ValidationReport


class ReliabilityResult(Contract):
    """Recorded evidence-quality components and lineage for a future leaf input.

    Values are supplied by M4. This contract does not verify or compute their
    formula relationships and contains no ER importance weight.
    """

    reliability_id: Text
    fact_ids: Annotated[tuple[Text, ...], Field(min_length=1)]
    evidence_ids: tuple[Text, ...] = ()
    validation_ids: tuple[Text, ...] = ()
    source_quality_s: UnitInterval
    extraction_quality_e: UnitInterval
    validation_factor_v: UnitInterval
    conflict_factor_c: UnitInterval
    base_reliability: UnitInterval
    validated_reliability: UnitInterval
    final_reliability_r: Annotated[UnitInterval, Field(le=Decimal("0.99"))]
    hard_fail: bool
    hard_fail_reason: Text | None = None
    reliability_model_version: Text
    calculated_at: UtcTimestamp
    processing_run_id: Text

    @model_validator(mode="after")
    def check_failure_metadata(self) -> Self:
        """A hard-failure flag must explain itself; no score is manufactured."""
        if self.hard_fail and self.hard_fail_reason is None:
            raise ValueError("hard_fail_reason is required when hard_fail is true")
        if not self.hard_fail and self.hard_fail_reason is not None:
            raise ValueError("hard_fail_reason requires hard_fail=true")
        # Missing required evidence must remain representable without inventing
        # an evidence record. The fact links retain the failed retrieval lineage.
        if not self.hard_fail and not self.evidence_ids:
            raise ValueError("non-failed reliability results require evidence_ids")
        if self.hard_fail and self.final_reliability_r != 0:
            raise ValueError("a supplied hard-fail result must have final_reliability_r=0")
        return self


class ConflictState(Contract):
    """Supplied deterministic conflict classification; no conflict discovery here."""

    level: ConflictLevel
    resolution: ConflictResolution
    reason: Text
    evidence_ids: tuple[Text, ...] = ()

    @model_validator(mode='after')
    def check_resolution(self) -> Self:
        """Resolved classifications cannot conceal an unresolved penalty or vice versa."""
        if (self.level != ConflictLevel.NONE) != (self.resolution == ConflictResolution.UNRESOLVED):
            raise ValueError('Unresolved conflict requires an explicit unresolved level/resolution')
        if self.resolution not in (ConflictResolution.NONE, ConflictResolution.UNRESOLVED) and not self.evidence_ids:
            raise ValueError('Resolved conflict requires supporting evidence references')
        return self


class ValidationSupport(Contract):
    """Selected strength and independently grouped supporting diagnostics."""

    strength: ValidationStrength
    outcomes: tuple[RuleOutcome, ...]
    reason: Text


class ReliabilityComponents(Contract):
    """Exact formula inputs, also usable for isolated formula tests."""

    s: UnitInterval
    e: UnitInterval
    v: UnitInterval
    c: UnitInterval


class ReliabilityCalculation(Contract):
    """Pure formula result; failures explicitly withhold supported analytical evidence."""

    components: ReliabilityComponents
    r_base: UnitInterval
    r_v: UnitInterval
    reliability_r: Annotated[UnitInterval, Field(le=Decimal('0.99'))]
    failures: tuple[AdmissionFailure, ...]
    policy_version: Literal['m4-reliability-v1'] = 'm4-reliability-v1'

    @property
    def supported_analytical_evidence(self) -> bool:
        """A numeric zero accompanying a hard failure is never an admitted fact."""
        return not self.failures

    @model_validator(mode='after')
    def check_failure(self) -> Self:
        """Do not allow a positive reliability alongside an explicit hard exclusion."""
        if self.failures and self.reliability_r != 0:
            raise ValueError('Hard failure requires r=0')
        return self


class ReliabilityAssessment(Contract):
    """Explainable framework result, not a persisted M4.4 ValidatedFact/evidence set."""

    validation: ValidationReport
    source_type: SourceType
    critical_transformation: CriticalTransformation
    transformation_chain: tuple[Text, ...]
    support: ValidationSupport
    conflict: ConflictState
    calculation: ReliabilityCalculation
    source_reason: Text
    transformation_reason: Text
    conflict_reason: Text
    formula_reason: Text
