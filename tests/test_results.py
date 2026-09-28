"""Supplied result-shape invariants; no calculation-engine tests."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from risk_intelligence.domain.enums import (
    AssessmentStatus, AvailabilityStatus, FactRole, NodeType, ProcessingStatus,
    Severity, TriggerType, ValidationStatus, ValidationType,
)
from risk_intelligence.domain.facts import NumericValue
from risk_intelligence.domain.reliability import ReliabilityResult
from risk_intelligence.domain.risk import (
    AggregationInput, AggregationResult, BeliefDistribution, ProvisionalBelief,
    VariableFactLink, VariableResult,
)
from risk_intelligence.domain.runs import Assessment, ProcessingRun
from risk_intelligence.domain.validation import ValidationResult


def test_validation_result_preserves_typed_observations(timestamp: datetime) -> None:
    result = ValidationResult(
        validation_id="validation-test", fact_id="fact-test",
        validation_type=ValidationType.ARITHMETIC, rule_code="SYNTHETIC_RULE",
        status=ValidationStatus.WARNING, severity=Severity.WARNING,
        validated_at=timestamp, processing_run_id="run-test",
        expected_value=NumericValue(value=Decimal("100")),
        observed_value=NumericValue(value=Decimal("101")), tolerance=Decimal("0"),
    )
    assert result.status == ValidationStatus.WARNING
    assert ValidationResult.model_validate_json(result.model_dump_json()) == result


def test_reliability_components_are_stored_not_calculated(reliability: ReliabilityResult) -> None:
    data = reliability.model_dump()
    data["source_quality_s"] = Decimal("0.9")
    changed = ReliabilityResult.model_validate(data)
    assert changed.final_reliability_r == reliability.final_reliability_r
    assert ReliabilityResult.model_validate_json(changed.model_dump_json()) == changed
    assert "importance_weight" not in type(changed).model_fields


@pytest.mark.parametrize("field,value", [
    ("source_quality_s", Decimal("1.01")), ("conflict_factor_c", Decimal("-0.1")),
    ("final_reliability_r", Decimal("1")), ("final_reliability_r", 0.95),
])
def test_reliability_rejects_out_of_range_or_inexact_components(
    reliability: ReliabilityResult, field: str, value: object,
) -> None:
    data = reliability.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        ReliabilityResult.model_validate(data)


def test_hard_fail_can_represent_absent_evidence_without_invented_ids(reliability: ReliabilityResult) -> None:
    data = reliability.model_dump()
    data.update(hard_fail=True, hard_fail_reason="RETRIEVAL_FAILED", evidence_ids=(),
                final_reliability_r=Decimal("0"))
    result = ReliabilityResult.model_validate(data)
    assert result.fact_ids == ("fact-test",)
    assert not result.evidence_ids


@pytest.mark.parametrize("changes", [
    {"hard_fail": True}, {"hard_fail_reason": "unexpected reason"},
    {"hard_fail": True, "hard_fail_reason": "failure"}, {"evidence_ids": ()},
])
def test_reliability_failure_metadata_must_be_consistent(
    reliability: ReliabilityResult, changes: dict[str, object],
) -> None:
    data = reliability.model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        ReliabilityResult.model_validate(data)


@pytest.mark.parametrize("values", [
    ("0.2", "0.3", "0.4"), ("-0.1", "0.6", "0.5"),
    ("1.1", "0", "0"), ("NaN", "0", "0"),
])
def test_belief_record_rejects_malformed_supplied_components(values: tuple[str, str, str]) -> None:
    with pytest.raises(ValidationError):
        BeliefDistribution(low_belief=Decimal(values[0]), high_belief=Decimal(values[1]),
                           unknown_belief=Decimal(values[2]))


def test_belief_sum_tolerance_is_structural_and_does_not_round() -> None:
    with localcontext() as context:
        context.prec = 3
        result = BeliefDistribution(
            low_belief=Decimal("0.200000009"), high_belief=Decimal("0.3"),
            unknown_belief=Decimal("0.5"),
        )
        assert str(result.low_belief) == "0.200000009"
        with pytest.raises(ValidationError, match="sum to 1"):
            BeliefDistribution(low_belief=Decimal("0.200000011"), high_belief=Decimal("0.3"),
                               unknown_belief=Decimal("0.5"))


def test_variable_links_to_facts_without_recalculating_output(variable: VariableResult) -> None:
    data = variable.model_dump()
    data["raw_value"] = Decimal("9.99")
    result = VariableResult.model_validate(data)
    link = VariableFactLink(variable_result_id=result.variable_result_id, fact_id="fact-test",
                            role=FactRole.REQUIRED)
    assert result.final_belief == variable.final_belief
    assert link.variable_result_id == result.variable_result_id
    assert VariableResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("changes", [
    {"raw_value": None}, {"raw_value": "UNKNOWN"}, {"variable_code": "F2.1"},
    {"availability_status": AvailabilityStatus.NOT_DISCLOSED},
])
def test_variable_rejects_invalid_identity_or_raw_value(
    variable: VariableResult, changes: dict[str, object],
) -> None:
    data = variable.model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        VariableResult.model_validate(data)


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("0.99")])
def test_leaf_reliability_snapshot_accepts_inclusive_boundaries(
    variable: VariableResult, value: Decimal,
) -> None:
    data = variable.model_dump()
    data["reliability_r"] = value
    result = VariableResult.model_validate(data)
    assert result.reliability_r == value
    assert VariableResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("value", [
    Decimal("-0.0001"), Decimal("0.990000001"), Decimal("1"), Decimal("1.01"),
])
def test_leaf_reliability_snapshot_rejects_values_outside_final_reliability_range(
    variable: VariableResult, value: Decimal,
) -> None:
    data = variable.model_dump()
    data["reliability_r"] = value
    with pytest.raises(ValidationError, match="reliability_r"):
        VariableResult.model_validate(data)
    payload = variable.model_dump(mode="json")
    payload["reliability_r"] = str(value)
    with pytest.raises(ValidationError, match="reliability_r"):
        VariableResult.model_validate_json(json.dumps(payload))


def test_missing_leaf_record_does_not_generate_beliefs(variable: VariableResult) -> None:
    data = variable.model_dump()
    data.update(raw_value=None, availability_status=AvailabilityStatus.NOT_DISCLOSED)
    result = VariableResult.model_validate(data)
    assert result.final_belief == variable.final_belief  # Mapping belongs to M5.


def test_provisional_beliefs_are_supplied_and_checked() -> None:
    supplied = ProvisionalBelief(low_belief=Decimal("0.4"), high_belief=Decimal("0.6"))
    assert ProvisionalBelief.model_validate_json(supplied.model_dump_json()) == supplied
    with pytest.raises(ValidationError):
        ProvisionalBelief(low_belief=Decimal("0.4"), high_belief=Decimal("0.4"))


def test_parent_result_and_importance_edge_are_separate(
    timestamp: datetime, beliefs: BeliefDistribution,
) -> None:
    result = AggregationResult(
        aggregation_result_id="aggregation-test", assessment_id="assessment-test",
        node_code="G3", node_type=NodeType.INDICATOR, node_name="Ownership",
        belief=beliefs, er_model_version="1", calculated_at=timestamp,
    )
    edge = AggregationInput(aggregation_result_id=result.aggregation_result_id,
                            child_code="G3.1", child_result_id="variable-test",
                            importance_weight=Decimal("1"))
    assert result.belief == beliefs
    assert "reliability_r" not in type(edge).model_fields
    assert AggregationResult.model_validate_json(result.model_dump_json()) == result
    assert AggregationInput.model_validate_json(edge.model_dump_json()) == edge
    data = result.model_dump()
    data["node_type"] = NodeType.OVERALL
    with pytest.raises(ValidationError, match="node_type"):
        AggregationResult.model_validate(data)


def test_assessment_and_run_metadata_do_not_execute_processing(timestamp: datetime) -> None:
    run = ProcessingRun(
        processing_run_id="run-test", company_id="company-test", company_number="ZZ000001",
        started_at=timestamp, status=ProcessingStatus.RUNNING, current_stage="SYNTHETIC",
        trigger_type=TriggerType.LIVE, app_version="0.1.0",
    )
    assessment = Assessment(
        assessment_id="assessment-test", company_id=run.company_id, company_number=run.company_number,
        processing_run_id=run.processing_run_id, assessment_date=date(2026, 1, 15),
        status=AssessmentStatus.PARTIAL, risk_model_version="1", reliability_model_version="1",
        er_model_version="1", data_dictionary_version="1.0",
    )
    assert Assessment.model_validate_json(assessment.model_dump_json()) == assessment
    assert ProcessingRun.model_validate_json(run.model_dump_json()) == run
    data = run.model_dump()
    data["completed_at"] = timestamp - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="completed_at"):
        ProcessingRun.model_validate(data)
