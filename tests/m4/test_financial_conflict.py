"""Focused deterministic M4 financial conflict tests."""

from datetime import date
from decimal import Decimal

from risk_intelligence.domain.enums import (
    AvailabilityStatus, ComparabilityStatus, ConflictLevel,
    ConflictResolution, ExtractionMethod, PeriodType,
)
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.validation.financial_conflict import classify_financial_conflict


PERIOD = ReportingPeriod(
    period_type=PeriodType.INSTANT,
    period_end=date(2025, 12, 31),
    comparability_status=ComparabilityStatus.COMPARABLE,
)


def fact(
        identity: str,
        value: str,
        *,
        concept: str = "TOTAL_ASSETS",
        period: ReportingPeriod = PERIOD,
        currency: str = "GBP",
        unit: str = "GBP",
) -> FinancialFact:
    return FinancialFact(
        financial_fact_id=identity,
        company_id="c",
        company_number="ZZ000003",
        canonical_concept=concept,
        source_concept="source",
        value_numeric=Decimal(value),
        currency=currency,
        unit=unit,
        period=period,
        source_id=f"s-{identity}",
        document_id=f"d-{identity}",
        evidence_ids=(f"e-{identity}",),
        extraction_method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC,
        availability_status=AvailabilityStatus.AVAILABLE,
        processing_run_id="r",
    )


def test_no_competitor_has_no_conflict() -> None:
    state = classify_financial_conflict(fact("a", "100"), ())
    assert state.level == ConflictLevel.NONE
    assert state.resolution == ConflictResolution.NONE


def test_equal_compatible_observations_have_no_conflict() -> None:
    state = classify_financial_conflict(
        fact("a", "100"), (fact("b", "100"),)
    )
    assert state.level == ConflictLevel.NONE
    assert state.resolution == ConflictResolution.NONE


def test_period_difference_is_resolved_explanation_not_penalty() -> None:
    other_period = PERIOD.model_copy(
        update={"period_end": date(2024, 12, 31)}
    )
    state = classify_financial_conflict(
        fact("a", "100"),
        (fact("b", "90", period=other_period),),
    )
    assert state.level == ConflictLevel.NONE
    assert state.resolution == ConflictResolution.PERIOD_DIFFERENCE
    assert set(state.evidence_ids) == {"e-a", "e-b"}


def test_unit_difference_is_resolved_explanation_not_penalty() -> None:
    state = classify_financial_conflict(
        fact("a", "100"),
        (fact("b", "0.1", unit="GBP thousands"),),
    )
    assert state.level == ConflictLevel.NONE
    assert state.resolution == ConflictResolution.UNIT_DIFFERENCE
    assert set(state.evidence_ids) == {"e-a", "e-b"}


def test_compatible_numeric_disagreement_fails_closed() -> None:
    state = classify_financial_conflict(
        fact("a", "100"),
        (fact("b", "90"),),
    )
    assert state.level == ConflictLevel.SERIOUS_UNRESOLVED
    assert state.resolution == ConflictResolution.UNRESOLVED
    assert set(state.evidence_ids) == {"e-a", "e-b"}


def test_later_observation_is_not_assumed_to_be_restatement() -> None:
    selected = fact("a", "100")
    later = fact("b", "90").model_copy(update={"processing_run_id": "later-run"})

    state = classify_financial_conflict(selected, (later,))

    assert state.level == ConflictLevel.SERIOUS_UNRESOLVED
    assert state.resolution == ConflictResolution.UNRESOLVED
    assert state.resolution != ConflictResolution.RESTATEMENT
    assert state.resolution != ConflictResolution.SUPERSEDED
