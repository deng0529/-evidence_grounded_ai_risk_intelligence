"""Generic analytical ER aggregation for explicit Low/High beliefs."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import Iterable

from risk_intelligence.domain.risk import BeliefDistribution
from risk_intelligence.risk_variables.core import DECIMAL_CONTEXT


@dataclass(frozen=True)
class WeightedBelief:
    """One child belief and its importance weight; weight is never reliability."""

    code: str
    result_id: str
    belief: BeliefDistribution
    weight: Decimal


def er_aggregate(children: Iterable[WeightedBelief]) -> BeliefDistribution:
    """Apply the frozen analytical ER formula with Unknown as residual incompleteness."""
    items = tuple(children)
    if not items:
        raise ValueError("ER aggregation requires at least one child")
    if len(items) == 1:
        return items[0].belief
    if len({item.code for item in items}) != len(items):
        raise ValueError("ER child codes must be unique")
    if any(item.weight < 0 or item.weight > 1 for item in items):
        raise ValueError("ER importance weights must be within [0,1]")
    with localcontext(DECIMAL_CONTEXT):
        if abs(sum((item.weight for item in items), Decimal(0)) - Decimal(1)) > Decimal("1e-8"):
            raise ValueError("ER importance weights must sum to 1 within absolute tolerance 1e-8")
        a_low = Decimal(1)
        a_high = Decimal(1)
        b = Decimal(1)
        c = Decimal(1)
        for item in items:
            low = Decimal(item.belief.low_belief)
            high = Decimal(item.belief.high_belief)
            s = low + high
            a_low *= item.weight * low + 1 - item.weight * s
            a_high *= item.weight * high + 1 - item.weight * s
            b *= 1 - item.weight * s
            c *= 1 - item.weight
        normalization_denominator = a_low + a_high - b
        if normalization_denominator == 0:
            raise ValueError("ER normalization is undefined")
        mu = 1 / normalization_denominator
        denominator = 1 - mu * c
        if denominator == 0:
            raise ValueError("ER belief normalization is undefined")
        low = mu * (a_low - b) / denominator
        high = mu * (a_high - b) / denominator
        unknown = 1 - low - high
        # Decimal arithmetic can leave an immaterial negative residue near zero.
        if abs(unknown) <= Decimal("1e-48"):
            unknown = Decimal(0)
        return BeliefDistribution(low_belief=low, high_belief=high, unknown_belief=unknown)


def aggregation_identity(assessment_id: str, node_code: str, er_model_version: str,
                         children: Iterable[WeightedBelief]) -> str:
    """Stable identity over the exact ordered audit inputs used for a parent result."""
    payload = "|".join(
        f"{item.code}:{item.result_id}:{item.weight}:{item.belief.model_dump_json()}"
        for item in sorted(children, key=lambda item: item.code)
    )
    return sha256(f"{assessment_id}|{node_code}|{er_model_version}|{payload}".encode()).hexdigest()
