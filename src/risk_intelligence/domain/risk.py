"""Leaf and parent result shapes, with no transformations or aggregation."""

from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import Contract, ExactDecimal, Text, UnitInterval, UtcTimestamp
from .enums import AvailabilityStatus, FactRole, NodeType

VariableCode = Literal[
    "G1.1", "G1.2", "G2.1", "G2.2", "G2.3", "G3.1",
    "F1.1", "F1.2", "F2.2", "F2.3", "F3.1",
]
NodeCode = Literal["G1", "G2", "G3", "F1", "F2", "F3", "GOVERNANCE", "FINANCIAL", "OVERALL"]
# This checks record shape only; it is not a belief calculation or rounding rule.
BELIEF_SUM_TOLERANCE = Fraction(1, 100_000_000)


class BeliefDistribution(Contract):
    """A supplied Low/High/Unknown distribution, without deriving any component."""

    low_belief: UnitInterval
    high_belief: UnitInterval
    unknown_belief: UnitInterval

    @model_validator(mode="after")
    def check_total(self) -> Self:
        """Reject malformed totals using the frozen absolute tolerance."""
        # Fraction makes validation independent of a caller's Decimal context.
        total = sum(Fraction(v) for v in (
            self.low_belief, self.high_belief, self.unknown_belief,
        ))
        if abs(total - 1) > BELIEF_SUM_TOLERANCE:
            raise ValueError("belief components must sum to 1 within absolute tolerance 1e-8")
        return self


class ProvisionalBelief(Contract):
    """Supplied pre-reliability Low/High components from a future M5 engine."""

    low_belief: UnitInterval
    high_belief: UnitInterval

    @model_validator(mode="after")
    def check_total(self) -> Self:
        """Validate completeness without converting a metric into beliefs."""
        total = Fraction(self.low_belief) + Fraction(self.high_belief)
        if abs(total - 1) > BELIEF_SUM_TOLERANCE:
            raise ValueError("provisional beliefs must sum to 1 within absolute tolerance 1e-8")
        return self


class VariableResult(Contract):
    """Supplied leaf result, linked to facts, reliability and model versions."""

    variable_result_id: Text
    assessment_id: Text
    variable_code: VariableCode
    raw_value: ExactDecimal | None
    unit: Text
    low_reference: ExactDecimal | None = None
    high_reference: ExactDecimal | None = None
    provisional_belief: ProvisionalBelief | None = None
    reliability_id: Text
    # Reproducibility snapshot of the final reliability used for this leaf.
    # Correspondence with reliability_id is checked by a later milestone.
    reliability_r: Annotated[UnitInterval, Field(le=Decimal("0.99"))]
    final_belief: BeliefDistribution
    availability_status: AvailabilityStatus
    risk_model_version: Text
    reliability_model_version: Text
    calculated_at: UtcTimestamp

    @model_validator(mode="after")
    def check_raw_value_status(self) -> Self:
        """Check missing-value shape without generating its risk consequence."""
        if self.availability_status == AvailabilityStatus.AVAILABLE:
            if self.raw_value is None:
                raise ValueError("AVAILABLE variable result requires raw_value")
        elif self.raw_value is not None:
            raise ValueError("unavailable variable result requires raw_value=None")
        return self


class VariableFactLink(Contract):
    """Exact dependency edge from a leaf result to a source fact."""

    variable_result_id: Text
    fact_id: Text
    role: FactRole


class AggregationResult(Contract):
    """Supplied parent belief result; leaf results use VariableResult instead."""

    aggregation_result_id: Text
    assessment_id: Text
    node_code: NodeCode
    node_type: NodeType
    node_name: Text
    belief: BeliefDistribution
    er_model_version: Text
    calculated_at: UtcTimestamp

    @model_validator(mode="after")
    def check_node_level(self) -> Self:
        """Keep node identity and level structurally consistent."""
        if self.node_code == "OVERALL":
            expected = NodeType.OVERALL
        elif self.node_code in ("GOVERNANCE", "FINANCIAL"):
            expected = NodeType.DOMAIN
        else:
            expected = NodeType.INDICATOR
        if self.node_type != expected:
            raise ValueError("node_type does not match node_code")
        return self


class AggregationInput(Contract):
    """Audit edge recording an importance weight, never evidence reliability."""

    aggregation_result_id: Text
    child_code: VariableCode | NodeCode
    child_result_id: Text
    importance_weight: UnitInterval
