"""Frozen leaf references, exact transformations, minimum reliability and audit contracts."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Literal

from risk_intelligence.domain.common import Contract, ExactDecimal, Text, UnitInterval
from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.domain.risk import BeliefDistribution, ProvisionalBelief, VariableCode, VariableResult

CALCULATION_VERSION = "m5-calculation-v1"
RISK_MODEL_VERSION = "1"
DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


class Reason(StrEnum):
    """M5 calculation exclusions, separate from source validation failures."""

    MISSING_INPUT = "MISSING_REQUIRED_INPUT"
    UNUSABLE_INPUT = "UNUSABLE_VALIDATED_INPUT"
    AMBIGUOUS_SELECTION = "AMBIGUOUS_INPUT_SELECTION"
    INCOMPATIBLE_INPUTS = "INCOMPATIBLE_INPUTS"
    NON_COMPARABLE = "NON_COMPARABLE_PERIODS"
    NON_POSITIVE_ASSETS = "NON_POSITIVE_TOTAL_ASSETS"
    NON_POSITIVE_LIABILITIES = "NON_POSITIVE_CURRENT_LIABILITIES"
    ZERO_PREVIOUS_NET_ASSETS = "ZERO_PREVIOUS_NET_ASSETS"
    INCOMPLETE_POPULATION = "INCOMPLETE_POPULATION"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_DIRECTOR_IDENTITY"
    AMBIGUOUS_ROLE = "AMBIGUOUS_DIRECTOR_ROLE"
    MISSING_APPOINTMENT = "MISSING_EXACT_APPOINTMENT"
    EMPTY_POPULATION = "EMPTY_DIRECTOR_POPULATION"
    ZERO_DENOMINATOR = "ZERO_DIRECTOR_DENOMINATOR"
    NO_COMPUTABLE_WINDOW = "NO_COMPUTABLE_WINDOW"
    AMBIGUOUS_CONTROL = "AMBIGUOUS_SUBSTANTIVE_CONTROL_CHANGE"
    UNRESOLVED_OBLIGATION = "UNRESOLVED_OBLIGATION"


@dataclass(frozen=True)
class VariableDefinition:
    """References and metadata only; importance weights are reserved for M6."""

    low: Decimal
    high: Decimal
    unit: str
    local_weight: Decimal
    effective_weight: Decimal


DEFINITIONS = MappingProxyType({
    code: VariableDefinition(*(Decimal(v) for v in (low, high)), unit, Decimal(weight), Decimal(effective))
    for code, low, high, unit, weight, effective in (
        ("G1.1", "0", "90", "days", ".60", ".072"),
        ("G1.2", "0", "30", "days", ".40", ".048"),
        ("G2.1", "0", ".50", "ratio", ".40", ".072"),
        ("G2.2", "5", "1", "years", ".25", ".045"),
        ("G2.3", "0", ".50", "ratio", ".35", ".063"),
        ("G3.1", "0", "2", "count", "1", ".10"),
        ("F1.1", ".10", "0", "ratio", ".65", ".1365"),
        ("F1.2", "0", "-.20", "ratio", ".35", ".0735"),
        ("F2.2", "1.50", "1.10", "ratio", ".60", ".144"),
        ("F2.3", "1", ".70", "ratio", ".40", ".096"),
        ("F3.1", ".20", ".60", "ratio", "1", ".15"),
    )
})


class ValidatedInput(Contract):
    """Exact upstream observation identity, role and frozen reliability provenance."""

    kind: Literal["FACT", "SET", "OBLIGATION"]
    validated_id: Text
    mandatory: bool = True
    reliability_r: UnitInterval
    validation_version: Text
    reliability_version: Text


class TraceStep(Contract):
    """Deterministic explanatory step; no evidence bytes or model-generated explanation."""

    operation: Text
    detail: Text


class Calculation(Contract):
    """Pre-belief variable value or typed failure with every inspected input retained."""

    value: ExactDecimal | None
    inputs: tuple[ValidatedInput, ...] = ()
    reasons: tuple[Reason, ...] = ()
    trace: tuple[TraceStep, ...] = ()
    selected_dates: tuple[date, ...] = ()
    availability: AvailabilityStatus | None = AvailabilityStatus.AVAILABLE


class LeafAssessment(Contract):
    """Persistable M5 result and audit context; result is the unchanged M6 leaf shape."""

    result: VariableResult
    company_id: Text
    company_number: Text
    assessment_date: date
    analytical_scope: Literal["COMPANY", "GROUP"]
    calculation_version: Literal["m5-calculation-v1"] = CALCULATION_VERSION
    calculation: Calculation


def unavailable(reason: Reason, inputs: tuple[ValidatedInput, ...] = (), *,
                trace: tuple[TraceStep, ...] = (), dates: tuple[date, ...] = (),
                availability: AvailabilityStatus | None = None) -> Calculation:
    """Withhold arithmetic output, preserving source availability when explicitly known."""
    return Calculation(value=None, inputs=inputs, reasons=(reason,), trace=trace,
                       selected_dates=dates, availability=availability)


def provisional(code: VariableCode, value: Decimal) -> ProvisionalBelief:
    """Linearly interpolate the frozen references; never use reliability or weights here."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Finite Decimal value required")
    definition = DEFINITIONS[code]
    with localcontext(DECIMAL_CONTEXT):
        high = max(Decimal(0), min(Decimal(1), (value - definition.low) / (definition.high - definition.low)))
        return ProvisionalBelief(low_belief=1 - high, high_belief=high)


def make_leaf(*, code: VariableCode, calculation: Calculation, assessment_id: str,
              company_id: str, company_number: str, assessment_date: date,
              scope: Literal["COMPANY", "GROUP"], calculated_at: datetime) -> LeafAssessment:
    """Apply minimum mandatory reliability exactly once; missing leaves remain present."""
    calculation = Calculation.model_validate(calculation)
    identities = [(item.kind, item.validated_id) for item in calculation.inputs]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate validated calculation input")
    required = [item for item in calculation.inputs if item.mandatory]
    usable = calculation.value is not None
    if usable and (calculation.reasons or calculation.availability != AvailabilityStatus.AVAILABLE or not required):
        raise ValueError("Usable calculation requires mandatory evidence and no exclusion")
    if not usable and (not calculation.reasons or calculation.availability == AvailabilityStatus.AVAILABLE):
        raise ValueError("Unavailable calculation requires typed reason and must not be AVAILABLE")
    if any(item.reliability_r > Decimal('.99') or item.reliability_version != 'm4-reliability-v1'
           for item in calculation.inputs):
        raise ValueError("Unsupported upstream reliability contract")
    reliability = min(item.reliability_r for item in required) if usable else Decimal(0)
    prior = provisional(code, calculation.value) if usable else None
    with localcontext(DECIMAL_CONTEXT):
        belief = BeliefDistribution(low_belief=reliability * prior.low_belief if prior else Decimal(0),
                                   high_belief=reliability * prior.high_belief if prior else Decimal(0),
                                   unknown_belief=1 - reliability)
    fingerprint = sha256((assessment_id + "|" + code + "|" + scope + "|" + CALCULATION_VERSION
                          + "|" + calculation.model_dump_json()).encode()).hexdigest()
    definition = DEFINITIONS[code]
    result = VariableResult(
        variable_result_id=fingerprint, assessment_id=assessment_id, variable_code=code,
        raw_value=calculation.value, unit=definition.unit, low_reference=definition.low,
        high_reference=definition.high, provisional_belief=prior, reliability_id="minimum-" + fingerprint,
        reliability_r=reliability, final_belief=belief, availability_status=(calculation.availability if calculation.availability is not None else AvailabilityStatus.VALIDATION_FAILED),
        risk_model_version=RISK_MODEL_VERSION, reliability_model_version="m4-reliability-v1",
        calculated_at=calculated_at,
    )
    return LeafAssessment(result=result, company_id=company_id, company_number=company_number,
                          assessment_date=assessment_date, analytical_scope=scope, calculation=calculation)
