from decimal import Decimal
from itertools import permutations

import pytest

from risk_intelligence.aggregation import WeightedBelief, er_aggregate
from risk_intelligence.domain.risk import BeliefDistribution


def b(low, high, unknown=0):
    return BeliefDistribution(low_belief=Decimal(str(low)), high_belief=Decimal(str(high)), unknown_belief=Decimal(str(unknown)))


def child(code, belief, weight):
    return WeightedBelief(code, code + "-id", belief, Decimal(str(weight)))


@pytest.mark.parametrize("belief", [b(1,0), b(0,1), b(0,0,1)])
def test_unanimous_extremes_and_unknown_are_identities(belief):
    result = er_aggregate((child("a", belief, ".5"), child("b", belief, ".5")))
    assert result == belief


def test_single_child_is_exact_identity():
    belief = b(".2", ".3", ".5")
    assert er_aggregate((child("a", belief, "1"),)) is belief


def test_unknown_child_is_retained_and_weight_is_not_redistributed():
    known = b(1, 0)
    unknown = b(0, 0, 1)
    mixed = er_aggregate((child("known", known, ".5"), child("missing", unknown, ".5")))
    redistributed = er_aggregate((child("known", known, "1"),))
    assert mixed.unknown_belief > 0
    assert mixed != redistributed


def test_order_invariance():
    items = (child("a", b(".8", ".1", ".1"), ".2"), child("b", b(".1", ".7", ".2"), ".3"), child("c", b(".2", ".2", ".6"), ".5"))
    expected = er_aggregate(items)
    assert all(er_aggregate(order) == expected for order in permutations(items))


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        er_aggregate((child("a", b(1,0), ".2"), child("b", b(0,1), ".2")))


def test_frozen_top_level_conflict_example():
    result = er_aggregate((child("GOVERNANCE", b(1,0), ".40"), child("FINANCIAL", b(0,1), ".60")))
    assert abs(result.low_belief - Decimal(".3076923076923077")) <= Decimal("1e-8")
    assert abs(result.high_belief - Decimal(".6923076923076923")) <= Decimal("1e-8")
    assert result.unknown_belief == 0


def test_pipnut_v12_leaf_regression_reference():
    values = {
        "G1.1": b(".9702", "0", ".0298"),
        "G1.2": b(".9702", "0", ".0298"),
        "G2.2": b(".9702", "0", ".0298"),
        "F1.1": b(".7155279037", ".0919720963", ".1925"),
        "F2.2": b("0", ".8075", ".1925"),
        "F2.3": b(".1779672553", ".6295327447", ".1925"),
    }
    third = Decimal(1) / Decimal(3)
    governance = er_aggregate(tuple(child(code, values[code], third) for code in ("G1.1","G1.2","G2.2")))
    financial = er_aggregate(tuple(child(code, values[code], third) for code in ("F1.1","F2.2","F2.3")))
    overall = er_aggregate((child("GOVERNANCE", governance, ".40"), child("FINANCIAL", financial, ".60")))
    expected = (Decimal(".5826512508995443"), Decimal(".3201263980510458"), Decimal(".0972223510494099"))
    assert all(abs(actual - wanted) <= Decimal("1e-8") for actual, wanted in zip(
        (overall.low_belief, overall.high_belief, overall.unknown_belief), expected, strict=True))
