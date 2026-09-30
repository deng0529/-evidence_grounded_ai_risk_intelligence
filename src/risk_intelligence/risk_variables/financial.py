"""M5 ratios over persisted M4 observations; no extraction or financial revalidation."""

from datetime import date
from decimal import localcontext

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus
from risk_intelligence.persistence.validated_repository import PersistedValidatedFact
from .core import Calculation, DECIMAL_CONTEXT, Reason, TraceStep, ValidatedInput, unavailable

DEPENDENCIES = {
    "F1.1": ("NET_ASSETS", "TOTAL_ASSETS"),
    "F1.2": ("NET_ASSETS",),
    "F2.2": ("CURRENT_ASSETS", "CURRENT_LIABILITIES"),
    "F2.3": ("CURRENT_ASSETS", "INVENTORY", "CURRENT_LIABILITIES"),
    "F3.1": ("INTEREST_BEARING_DEBT", "TOTAL_ASSETS"),
}


def fact_input(fact: PersistedValidatedFact, *, mandatory: bool = True) -> ValidatedInput:
    """Reference the validated observation, not just its underlying source fact."""
    return ValidatedInput(kind="FACT", validated_id=fact.validated_fact_id, mandatory=mandatory,
                          reliability_r=fact.reliability_r, validation_version=fact.validation_ruleset_version,
                          reliability_version=fact.reliability_policy_version)


def calculate_financial(code: str, facts: tuple[PersistedValidatedFact, ...], *,
                        company_id: str, company_number: str, scope: str, assessment_date: date) -> Calculation:
    """Select the latest complete compatible inputs; ambiguous observations stay unresolved."""
    concepts = DEPENDENCIES[code]
    candidates = sorted((f for f in facts if f.company_id == company_id and f.company_number == company_number
                         and f.canonical_concept in concepts and f.analytical_scope == scope
                         and f.assessment_date <= assessment_date), key=lambda f: f.validated_fact_id)
    if len({f.validated_fact_id for f in candidates}) != len(candidates):
        raise ValueError("Duplicate validated fact ID")
    inspected = tuple(fact_input(f, mandatory=False) for f in candidates)
    trace = tuple(TraceStep(operation="candidate", detail=f"{f.validated_fact_id}: {f.canonical_concept}; "
                           f"period={f.period_start}/{f.period_end}; scope={f.analytical_scope}; "
                           f"unit={f.currency}/{f.unit}; availability={f.availability_status.value}; "
                           f"admissible={f.validation_report.admissible}; value={f.value_numeric}") for f in candidates)
    usable = [f for f in candidates if f.availability_status == AvailabilityStatus.AVAILABLE
              and f.validation_report.admissible and f.value_numeric is not None
              and f.period_end is not None and f.period_end <= assessment_date
              and f.period_type is not None and f.currency and f.unit]
    if code == "F1.2":
        usable = [f for f in usable if f.comparability_status == ComparabilityStatus.COMPARABLE]
    periods = sorted({f.period_end for f in usable}, reverse=True)
    selected: list[PersistedValidatedFact] = []
    for period in periods:
        observations = [f for f in usable if f.period_end == period]
        if not all(any(f.canonical_concept == concept for f in observations) for concept in concepts):
            continue
        if any(sum(f.canonical_concept == concept for f in observations) != 1 for concept in concepts):
            return unavailable(Reason.AMBIGUOUS_SELECTION, inspected, trace=trace)
        signatures = {(f.period_type, f.period_start, f.period_end, f.period_length_days, f.currency, f.unit)
                      for f in observations}
        if len(signatures) != 1:
            continue
        selected.extend(sorted(observations, key=lambda f: concepts.index(f.canonical_concept)))
        if code != "F1.2" or len(selected) == 2:
            break
    needed = 2 if code == "F1.2" else len(concepts)
    if len(selected) != needed:
        status = AvailabilityStatus.NON_COMPARABLE if code == "F1.2" else AvailabilityStatus.NOT_DISCLOSED
        # Preserve an explicit source failure rather than recasting it as arithmetic.
        failures = {f.availability_status for f in candidates if f.availability_status != AvailabilityStatus.AVAILABLE}
        if len(failures) == 1:
            status = next(iter(failures))
        return unavailable(Reason.NON_COMPARABLE if code == "F1.2" else Reason.MISSING_INPUT,
                           inspected, trace=trace, availability=status)
    if code == "F1.2" and len({(f.currency, f.unit, f.period_type) for f in selected}) != 1:
        return unavailable(Reason.INCOMPATIBLE_INPUTS, inspected, trace=trace)
    ids = {f.validated_fact_id for f in selected}
    inputs = tuple(fact_input(f, mandatory=f.validated_fact_id in ids) for f in candidates)
    dates = tuple(f.period_end for f in selected)
    values = [f.value_numeric for f in selected]
    denominator = values[1].copy_abs() if code == "F1.2" else values[-1]
    if denominator <= 0:
        reason = (Reason.ZERO_PREVIOUS_NET_ASSETS if code == "F1.2" else
                  Reason.NON_POSITIVE_ASSETS if code in ("F1.1", "F3.1") else Reason.NON_POSITIVE_LIABILITIES)
        return unavailable(reason, inputs, trace=trace, dates=dates)
    with localcontext(DECIMAL_CONTEXT):
        numerator = values[0] - values[1] if code in ("F1.2", "F2.3") else values[0]
        value = numerator / denominator
    trace += (TraceStep(operation="arithmetic", detail=f"{code}: numerator={numerator}; denominator={denominator}; value={value}"),)
    return Calculation(value=value, inputs=inputs, selected_dates=dates, trace=trace)
