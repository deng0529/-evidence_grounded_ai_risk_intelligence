"""Exact frozen reference transformations and one-time minimum reliability."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

import pytest

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.risk_variables.core import (
    Calculation, DEFINITIONS, Reason, ValidatedInput, make_leaf, provisional, unavailable,
)


def ref(identity="input", reliability="0.8", mandatory=True):
    return ValidatedInput(kind="FACT", validated_id=identity, reliability_r=Decimal(reliability),
                          mandatory=mandatory, validation_version="financial-v1", reliability_version="m4-reliability-v1")


def leaf(calculation, code="F2.2"):
    return make_leaf(code=code, calculation=calculation, assessment_id="assessment", company_id="company",
                     company_number="ZZ000001", assessment_date=date(2026, 9, 30), scope="COMPANY",
                     calculated_at=datetime(2026, 9, 30, tzinfo=UTC))


@pytest.mark.parametrize("code", list(DEFINITIONS))
def test_frozen_reference_boundaries_midpoint_and_clamping(code):
    definition = DEFINITIONS[code]
    assert provisional(code, definition.low).high_belief == 0
    assert provisional(code, definition.high).high_belief == 1
    assert provisional(code, (definition.low + definition.high) / 2).high_belief == Decimal('.5')
    beyond_low = definition.low + (definition.low - definition.high)
    beyond_high = definition.high + (definition.high - definition.low)
    assert provisional(code, beyond_low).low_belief == 1
    assert provisional(code, beyond_high).high_belief == 1


def test_minimum_only_mandatory_inputs_and_no_double_discount():
    result = leaf(Calculation(value=Decimal('1.3'), inputs=(ref("a", ".8"), ref("b", ".6"), ref("optional", ".1", False)))).result
    assert result.reliability_r == Decimal('.6')
    assert result.final_belief.low_belief == Decimal('.3')
    assert result.final_belief.high_belief == Decimal('.3')
    assert result.final_belief.unknown_belief == Decimal('.4')
    assert result.provisional_belief.high_belief == Decimal('.5')


@pytest.mark.parametrize("status", [AvailabilityStatus.NOT_DISCLOSED, AvailabilityStatus.RETRIEVAL_FAILED,
    AvailabilityStatus.EXTRACTION_FAILED, AvailabilityStatus.CONFLICT_UNRESOLVED,
    AvailabilityStatus.NON_COMPARABLE, None])
def test_unavailable_has_no_raw_or_provisional_value_and_retains_reason(status):
    result = leaf(unavailable(Reason.MISSING_INPUT, availability=status))
    assert result.result.raw_value is None
    assert result.result.provisional_belief is None
    assert result.result.final_belief.model_dump() == {"low_belief": Decimal(0), "high_belief": Decimal(0), "unknown_belief": Decimal(1)}
    assert result.result.availability_status == (status if status is not None else AvailabilityStatus.VALIDATION_FAILED)
    assert result.calculation.reasons == (Reason.MISSING_INPUT,)


def test_reproducible_under_ambient_decimal_context_and_no_weight_discount():
    calculation = Calculation(value=Decimal('1.23456789'), inputs=(ref(),))
    expected = leaf(calculation)
    with localcontext() as context:
        context.prec = 3
        assert leaf(calculation) == expected
    assert set(DEFINITIONS) == {"G1.1", "G1.2", "G2.2", "F1.1", "F2.2", "F2.3"}


def test_available_value_requires_mandatory_evidence_and_unique_ids():
    with pytest.raises(ValueError):
        leaf(Calculation(value=Decimal(1)))
    with pytest.raises(ValueError):
        leaf(Calculation(value=Decimal(1), inputs=(ref(), ref())))


def test_v12_model_membership_is_loaded_from_versioned_configuration():
    from risk_intelligence.risk_variables.core import (
        ACTIVE_VARIABLES, DOMAIN_VARIABLES, DOMAIN_WEIGHTS, WITHIN_DOMAIN_WEIGHTING_POLICY,
        model_definitions,
    )
    assert ACTIVE_VARIABLES == ("G1.1", "G1.2", "G2.2", "F1.1", "F2.2", "F2.3")
    assert tuple(model_definitions("1.1")) == ("G1.1", "G1.2", "G2.2", "F1.1", "F2.2", "F2.3", "F3.1")
    assert len(model_definitions("1")) == 11
    assert DOMAIN_VARIABLES == {
        "GOVERNANCE": ("G1.1", "G1.2", "G2.2"),
        "FINANCIAL": ("F1.1", "F2.2", "F2.3"),
    }
    assert DOMAIN_WEIGHTS == {"GOVERNANCE": Decimal("0.40"), "FINANCIAL": Decimal("0.60")}
    assert WITHIN_DOMAIN_WEIGHTING_POLICY == "EQUAL_WEIGHT_ACTIVE_VARIABLES"
