"""Frozen leaf references, exact transformations, minimum reliability and audit contracts."""

from dataclasses import dataclass
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from hashlib import sha256
from importlib.resources import files
from types import MappingProxyType

import yaml
from typing import Literal

from risk_intelligence.domain.common import Contract, ExactDecimal, Text, UnitInterval
from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.domain.risk import BeliefDistribution, ProvisionalBelief, VariableCode, VariableResult

CALCULATION_VERSION = "m5-calculation-v1.2"
RISK_MODEL_VERSION = "1.2"
ER_MODEL_VERSION = "1.2"
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
    """Reference levels and metadata loaded from the versioned model specification."""

    low: Decimal
    high: Decimal
    unit: str


def _load_model_spec() -> dict:
    path = files("risk_intelligence.risk_variables").joinpath("config/risk_model.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("Risk model configuration must be a mapping")
    if raw.get("current_model_version") != RISK_MODEL_VERSION:
        raise RuntimeError("Risk model configuration/version mismatch")
    if raw.get("calculation_version") != CALCULATION_VERSION:
        raise RuntimeError("Risk model calculation-version mismatch")
    if raw.get("er_model_version") != ER_MODEL_VERSION:
        raise RuntimeError("ER model configuration/version mismatch")
    return raw


_MODEL_SPEC = _load_model_spec()
_VARIABLE_SPECS = _MODEL_SPEC["variables"]
_ALL_DEFINITIONS = MappingProxyType({
    code: VariableDefinition(Decimal(str(spec["low"])), Decimal(str(spec["high"])), str(spec["unit"]))
    for code, spec in _VARIABLE_SPECS.items()
})


def _definitions_for(version: str) -> Mapping[str, VariableDefinition]:
    try:
        codes = tuple(_MODEL_SPEC["models"][version]["active_variables"])
    except KeyError:
        raise ValueError("Unsupported risk model version") from None
    unknown = tuple(code for code in codes if code not in _ALL_DEFINITIONS)
    if unknown:
        raise RuntimeError(f"Risk model {version} references undefined variables: {unknown}")
    return MappingProxyType({code: _ALL_DEFINITIONS[code] for code in codes})


HISTORICAL_DEFINITIONS = _definitions_for("1")
V11_DEFINITIONS = _definitions_for("1.1")
DEFINITIONS = _definitions_for(RISK_MODEL_VERSION)
ACTIVE_VARIABLES = tuple(DEFINITIONS)
MODEL_DEFINITIONS = MappingProxyType({
    version: _definitions_for(version) for version in _MODEL_SPEC["models"]
})


def model_definitions(version: str) -> Mapping[str, VariableDefinition]:
    """Resolve an explicit model; unknown versions never fall back to the current MVP."""
    try:
        return MODEL_DEFINITIONS[version]
    except KeyError:
        raise ValueError("Unsupported risk model version") from None


_CURRENT_DOMAINS = _MODEL_SPEC["models"][RISK_MODEL_VERSION]["domains"]
DOMAIN_VARIABLES = MappingProxyType({
    domain: tuple(spec["variables"]) for domain, spec in _CURRENT_DOMAINS.items()
})
DOMAIN_WEIGHTS = MappingProxyType({
    domain: Decimal(str(spec["weight"])) for domain, spec in _CURRENT_DOMAINS.items()
})
_policies = {str(spec["weighting_policy"]) for spec in _CURRENT_DOMAINS.values()}
if len(_policies) != 1:
    raise RuntimeError("MVP domains must use one within-domain weighting policy")
WITHIN_DOMAIN_WEIGHTING_POLICY = next(iter(_policies))


def model_aggregation_config(version: str) -> Mapping[str, Mapping[str, object]]:
    """Return versioned domain membership/weights; never infer aggregation from code names."""
    try:
        domains = _MODEL_SPEC["models"][version]["domains"]
    except KeyError:
        raise ValueError("Risk model version has no aggregation configuration") from None
    active = tuple(model_definitions(version))
    configured = tuple(code for spec in domains.values() for code in spec["variables"])
    if configured != active:
        raise RuntimeError("Aggregation domains must exactly partition active variables in registry order")
    weights = [Decimal(str(spec["weight"])) for spec in domains.values()]
    if sum(weights, Decimal(0)) != Decimal(1):
        raise RuntimeError("Aggregation domain weights must sum to 1")
    return MappingProxyType({domain: MappingProxyType({
        "weight": Decimal(str(spec["weight"])),
        "weighting_policy": str(spec["weighting_policy"]),
        "variables": tuple(spec["variables"]),
    }) for domain, spec in domains.items()})


if tuple(code for codes in DOMAIN_VARIABLES.values() for code in codes) != ACTIVE_VARIABLES:
    raise RuntimeError("Current model domain variables must exactly match active variables")
if sum(DOMAIN_WEIGHTS.values(), Decimal("0")) != Decimal("1"):
    raise RuntimeError("Current model domain weights must sum to 1")



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
    calculation_version: Literal["m5-calculation-v1", "m5-calculation-v1.1", "m5-calculation-v1.2"] = CALCULATION_VERSION
    calculation: Calculation


def unavailable(reason: Reason, inputs: tuple[ValidatedInput, ...] = (), *,
                trace: tuple[TraceStep, ...] = (), dates: tuple[date, ...] = (),
                availability: AvailabilityStatus | None = None) -> Calculation:
    """Withhold arithmetic output, preserving source availability when explicitly known."""
    return Calculation(value=None, inputs=inputs, reasons=(reason,), trace=trace,
                       selected_dates=dates, availability=availability)


def provisional(code: VariableCode, value: Decimal, *, model_version: str = RISK_MODEL_VERSION) -> ProvisionalBelief:
    """Linearly interpolate the frozen references; never use reliability or weights here."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Finite Decimal value required")
    definition = model_definitions(model_version)[code]
    with localcontext(DECIMAL_CONTEXT):
        high = max(Decimal(0), min(Decimal(1), (value - definition.low) / (definition.high - definition.low)))
        return ProvisionalBelief(low_belief=1 - high, high_belief=high)


def make_leaf(*, code: VariableCode, calculation: Calculation, assessment_id: str,
              company_id: str, company_number: str, assessment_date: date,
              scope: Literal["COMPANY", "GROUP"], calculated_at: datetime,
              model_version: str = RISK_MODEL_VERSION) -> LeafAssessment:
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
    definitions = model_definitions(model_version)
    calculation_version = "m5-calculation-v" + model_version
    prior = provisional(code, calculation.value, model_version=model_version) if usable else None
    with localcontext(DECIMAL_CONTEXT):
        belief = BeliefDistribution(low_belief=reliability * prior.low_belief if prior else Decimal(0),
                                   high_belief=reliability * prior.high_belief if prior else Decimal(0),
                                   unknown_belief=1 - reliability)
    fingerprint = sha256((assessment_id + "|" + code + "|" + scope + "|" + calculation_version
                          + "|" + calculation.model_dump_json()).encode()).hexdigest()
    definition = definitions[code]
    result = VariableResult(
        variable_result_id=fingerprint, assessment_id=assessment_id, variable_code=code,
        raw_value=calculation.value, unit=definition.unit, low_reference=definition.low,
        high_reference=definition.high, provisional_belief=prior, reliability_id="minimum-" + fingerprint,
        reliability_r=reliability, final_belief=belief, availability_status=(calculation.availability if calculation.availability is not None else AvailabilityStatus.VALIDATION_FAILED),
        risk_model_version=model_version, reliability_model_version="m4-reliability-v1",
        calculated_at=calculated_at,
    )
    return LeafAssessment(result=result, company_id=company_id, company_number=company_number,
                          assessment_date=assessment_date, analytical_scope=scope, calculation=calculation,
                          calculation_version=calculation_version)
