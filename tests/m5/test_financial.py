"""M5 financial selection, arithmetic and unavailable edge cases over saved DTOs."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ConflictLevel, ConflictResolution, PeriodType, ValidationStatus
from risk_intelligence.domain.reliability import ConflictState
from risk_intelligence.domain.validation import AnalyticalInput
from risk_intelligence.persistence.validated_repository import PersistedValidatedFact
from risk_intelligence.risk_variables.financial import calculate_financial
from risk_intelligence.risk_variables.core import Reason
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine

DAY = date(2026, 9, 30)


def fact(concept, value, year=2025, **changes):
    identity = f"{concept}-{year}"
    context = AnalyticalInput(input_id=identity, input_type="FINANCIAL", company_number="ZZ000001",
                              assessment_date=DAY, evidence_ids=("evidence-" + identity,))
    record = PersistedValidatedFact(
        validated_fact_id=identity, fact_id="source-" + identity, company_id="company", company_number="ZZ000001",
        processing_run_id="run", assessment_date=DAY, canonical_concept=concept, analytical_scope="COMPANY",
        value_numeric=Decimal(value), currency="GBP", unit="GBP", period_type=PeriodType.INSTANT,
        period_start=None, period_end=date(year, 12, 31), period_length_days=None,
        comparability_status=ComparabilityStatus.COMPARABLE, source_id="source", document_id="document",
        evidence_ids=context.evidence_ids, availability_status=AvailabilityStatus.AVAILABLE,
        provenance_type="DIRECT", normalization_method="deterministic", derivation_method=None,
        transformation_chain=("source",), critical_transformation="TAGGED_IXBRL_DETERMINISTIC",
        validation_report=ValidationEngine(RuleRegistry("financial-test-v1")).validate(context),
        conflict_state=ConflictState(level=ConflictLevel.NONE, resolution=ConflictResolution.NONE, reason="No conflict"),
        source_quality_s=Decimal('.97'), extraction_quality_e=Decimal('.98'), validation_factor_v=Decimal(0),
        conflict_factor_c=Decimal(0), reliability_r=Decimal('.9506'), validation_status=ValidationStatus.PASS,
        validation_ruleset_version="financial-test-v1", reliability_policy_version="m4-reliability-v1",
    )
    return replace(record, **changes)


def calculate(code, *facts, reporting_year=None):
    return calculate_financial(code, facts, company_id="company", company_number="ZZ000001", scope="COMPANY", assessment_date=DAY, reporting_year=reporting_year)


@pytest.mark.parametrize("code,operands,expected", [
    ("F1.1", (("NET_ASSETS", "20"), ("TOTAL_ASSETS", "100")), ".2"),
    ("F2.2", (("CURRENT_ASSETS", "150"), ("CURRENT_LIABILITIES", "100")), "1.5"),
    ("F2.3", (("CURRENT_ASSETS", "150"), ("INVENTORY", "30"), ("CURRENT_LIABILITIES", "100")), "1.2"),
    ("F3.1", (("INTEREST_BEARING_DEBT", "40"), ("TOTAL_ASSETS", "100")), ".4"),
])
def test_financial_exact_formulas_and_derived_inputs(code, operands, expected):
    inputs = tuple(fact(concept, value, provenance_type="DERIVED", derivation_method="approved-v1") for concept, value in operands)
    result = calculate(code, *inputs)
    assert result.value == Decimal(expected)
    assert {i.validated_id for i in result.inputs if i.mandatory} == {f.validated_fact_id for f in inputs}
    assert result.trace[-1].operation == "arithmetic"


@pytest.mark.parametrize("denominator", ["0", "-1"])
@pytest.mark.parametrize("code,operands", [
    ("F1.1", (("NET_ASSETS", "20"), ("TOTAL_ASSETS", None))),
    ("F2.2", (("CURRENT_ASSETS", "150"), ("CURRENT_LIABILITIES", None))),
    ("F2.3", (("CURRENT_ASSETS", "150"), ("INVENTORY", "30"), ("CURRENT_LIABILITIES", None))),
    ("F3.1", (("INTEREST_BEARING_DEBT", "40"), ("TOTAL_ASSETS", None))),
])
def test_nonpositive_denominators_do_not_become_infinite_or_low_risk(code, operands, denominator):
    result = calculate(code, *(fact(concept, value if value is not None else denominator) for concept, value in operands))
    assert result.value is None
    assert result.reasons[0] in (Reason.NON_POSITIVE_ASSETS, Reason.NON_POSITIVE_LIABILITIES)


def test_trend_exact_zero_tiny_nonzero_and_negative_previous():
    assert calculate("F1.2", fact("NET_ASSETS", "80"), fact("NET_ASSETS", "100", 2024)).value == Decimal('-.2')
    assert calculate("F1.2", fact("NET_ASSETS", "80"), fact("NET_ASSETS", "0", 2024)).reasons == (Reason.ZERO_PREVIOUS_NET_ASSETS,)
    assert calculate("F1.2", fact("NET_ASSETS", "2e-30"), fact("NET_ASSETS", "1e-30", 2024)).value == 1
    assert calculate("F1.2", fact("NET_ASSETS", "-80"), fact("NET_ASSETS", "-100", 2024)).value == Decimal('.2')


def test_no_inventory_default_partial_debt_or_noncomparable_trend():
    assert calculate("F2.3", fact("CURRENT_ASSETS", "100"), fact("CURRENT_LIABILITIES", "50")).value is None
    partial = fact("INTEREST_BEARING_DEBT", "10", availability_status=AvailabilityStatus.VALIDATION_FAILED, value_numeric=None)
    assert calculate("F3.1", partial, fact("TOTAL_ASSETS", "100")).value is None
    assert calculate("F1.2", fact("NET_ASSETS", "80"), fact("NET_ASSETS", "100", 2024,
                     comparability_status=ComparabilityStatus.NON_COMPARABLE)).value is None


@pytest.mark.parametrize("change", [{"analytical_scope": "GROUP"}, {"currency": "USD"}, {"unit": "GBP_THOUSANDS"},
    {"company_id": "other"}, {"period_end": date(2027, 12, 31)}])
def test_no_silent_input_mixing(change):
    assert calculate("F2.2", fact("CURRENT_ASSETS", "100"), fact("CURRENT_LIABILITIES", "50", **change)).value is None


def test_latest_compatible_period_and_ambiguous_duplicates():
    old = (fact("CURRENT_ASSETS", "80", 2024), fact("CURRENT_LIABILITIES", "100", 2024))
    new = (fact("CURRENT_ASSETS", "150"), fact("CURRENT_LIABILITIES", "100"))
    result = calculate("F2.2", *old, *new)
    assert result.value == Decimal('1.5')
    assert all(item.mandatory == item.validated_id.endswith('2025') for item in result.inputs)
    duplicate = replace(new[0], validated_fact_id="competing")
    assert calculate("F2.2", *new, duplicate).reasons == (Reason.AMBIGUOUS_SELECTION,)


def test_v11_selected_reporting_year_never_falls_back_to_another_year():
    old = (fact("CURRENT_ASSETS", "80", 2024), fact("CURRENT_LIABILITIES", "100", 2024))
    new = (fact("CURRENT_ASSETS", "150", 2025), fact("CURRENT_LIABILITIES", "100", 2025))
    assert calculate("F2.2", *old, *new, reporting_year=2024).value == Decimal(".8")
    assert calculate("F2.2", *old, *new, reporting_year=2025).value == Decimal("1.5")
    missing = calculate("F2.2", *old, reporting_year=2025)
    assert missing.value is None
    assert missing.reasons == (Reason.MISSING_INPUT,)


def test_other_year_failure_does_not_change_selected_year_missingness():
    old = fact("CURRENT_LIABILITIES", "10", 2024,
               availability_status=AvailabilityStatus.EXTRACTION_FAILED, value_numeric=None)
    result = calculate("F2.2", old, reporting_year=2025)
    assert result.availability == AvailabilityStatus.NOT_DISCLOSED
    assert not result.inputs
