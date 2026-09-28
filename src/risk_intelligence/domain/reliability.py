"""Evidence quality result contracts; no S/E/V/C/r computation."""

from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, model_validator

from .common import Contract, Text, UnitInterval, UtcTimestamp


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
