"""Persisted traceability, exact beliefs and strict no-calculation boundaries."""

from decimal import Decimal

import pytest

from risk_intelligence.explanation import AssessmentExplanation
from risk_intelligence.persistence.connection import IntegrityError
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.risk_variables.service import RiskVariableService
from risk_intelligence.services.aggregation import AggregationService
from risk_intelligence.services.company_assessment import run_company_assessment
from risk_intelligence.services.explanation import ExplanationService
from tests.m2.conftest import NOW, NUMBER
from tests.m5.test_company_runner import services
from tests.m5.test_obligations import prepare
from tests.m6.test_service import context


@pytest.fixture
def assessed(database, storage, api, ixbrl):
    m2, m3, _ = services(database, storage, api, ixbrl)
    report = run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025,
                                    run_id="m7", calculated_at=NOW, m2=m2, m3=m3)
    parents = AggregationService(database).calculate_and_persist(assessment_id=report.assessment_id, calculated_at=NOW)
    return report, parents


def test_exact_tree_weights_beliefs_reporting_year_and_determinism(database, assessed):
    report, parents = assessed
    service = ExplanationService(database)
    explanation = service.for_assessment(report.assessment_id)
    assert explanation == service.for_assessment(report.assessment_id)
    assert AssessmentExplanation.model_validate_json(explanation.model_dump_json()) == explanation
    assert tuple(item.leaf.result.variable_code for item in explanation.variables) == (
        "G1.1", "G1.2", "G2.2", "F1.1", "F2.2", "F2.3")
    assert tuple(item.leaf for item in explanation.variables) == report.leaves
    assert tuple(item.result for item in explanation.domains) + (explanation.overall.result,) == parents
    assert [(edge.child_code, edge.importance_weight) for edge in explanation.overall.children] == [
        ("GOVERNANCE", Decimal('.40')), ("FINANCIAL", Decimal('.60'))]
    assert [tuple(edge.child_code for edge in item.children) for item in explanation.domains] == [
        ("G1.1", "G1.2", "G2.2"), ("F1.1", "F2.2", "F2.3")]
    assert all(item.reporting_year == (2025 if item.domain == "FINANCIAL" else None) for item in explanation.variables)
    assert database.query("PRAGMA foreign_key_check") == []


def test_no_calculation_raw_access_or_writes(database, assessed, monkeypatch):
    import risk_intelligence.persistence.variable_repository as variables
    import risk_intelligence.services.aggregation as aggregation
    import risk_intelligence.validation.policy as policy
    from risk_intelligence.storage.local import LocalStorage
    from risk_intelligence.storage.r2 import R2Storage

    def forbidden(*args, **kwargs):
        raise AssertionError("M7 must only read persisted records")

    for target, name in [(variables, "make_leaf"), (aggregation, "er_aggregate"),
                         (policy, "assess_reliability"), (RiskVariableService, "calculate_and_persist"),
                         (AggregationService, "calculate_and_persist"), (LocalStorage, "read"), (R2Storage, "read"),
                         (database, "execute")]:
        monkeypatch.setattr(target, name, forbidden)
    assert ExplanationService(database).for_assessment(assessed[0].assessment_id).variables


def test_inputs_and_evidence_are_resolved_without_fabrication(database, assessed):
    from risk_intelligence.persistence.validated_repository import ValidatedEvidenceRepository

    explanation = ExplanationService(database).for_assessment(assessed[0].assessment_id)
    financial_inputs = [item for variable in explanation.variables for item in variable.inputs if item.reference.kind == "FACT"]
    assert financial_inputs
    for item in financial_inputs:
        assert item.record == ValidatedEvidenceRepository(database).get_fact(item.reference.validated_id)
        assert item.record.fact_id == item.observations[0].financial_fact_id
        assert item.record.reliability_r == item.reference.reliability_r
        for evidence in item.evidence:
            assert evidence.reference.source_id == evidence.source.source_id
            if evidence.reference.document_id:
                assert evidence.document.document_id == evidence.reference.document_id
    obligations = [item for variable in explanation.variables for item in variable.inputs if item.reference.kind == "OBLIGATION"]
    assert obligations and all(item.observations and item.evidence for item in obligations)
    assert any(e.reference.location.kind == "JSON_PATH" for item in obligations for e in item.evidence)
    assert all(e.document is None for item in obligations for e in item.evidence)
    # Missing analytical financial observations have no manufactured source components.
    absent = [item for item in financial_inputs if item.record.value_numeric is None]
    assert absent and all(item.financial_lineage is None for item in absent)


def test_unknown_leaf_retains_reason_and_inputs(database, assessed):
    explanation = ExplanationService(database).for_assessment(assessed[0].assessment_id)
    unavailable = [item for item in explanation.variables if item.leaf.result.raw_value is None]
    assert unavailable
    for item in unavailable:
        assert item.leaf.result.final_belief.unknown_belief == 1
        assert item.leaf.result.availability_status.value != "AVAILABLE"
        assert item.leaf.calculation.reasons
        assert tuple(i.reference for i in item.inputs) == item.leaf.calculation.inputs


@pytest.mark.parametrize("version", ["1", "1.1"])
def test_historical_versions_rejected_explicitly(database, storage, api, version):
    obligation = prepare(database, storage, api)
    context(database, obligation, version)
    with pytest.raises(IntegrityError, match="v1.2 only"):
        ExplanationService(database).for_assessment("m5")


def test_missing_assessment_and_missing_m6_fail_clearly(database, storage, api):
    with pytest.raises(IntegrityError, match="missing persisted assessment"):
        ExplanationService(database).for_assessment("absent")
    obligation = prepare(database, storage, api)
    context(database, obligation)
    RiskVariableService(database).calculate_and_persist(assessment_id="m5", calculated_at=NOW, scope="COMPANY")
    with pytest.raises(IntegrityError, match="persisted M6"):
        ExplanationService(database).for_assessment("m5")


def test_dangling_evidence_is_an_integrity_error(database, assessed, monkeypatch):
    from risk_intelligence.persistence.evidence_repositories import SqlEvidenceReferenceRepository
    monkeypatch.setattr(SqlEvidenceReferenceRepository, "get", lambda *args: None)
    with pytest.raises(IntegrityError, match="evidence reference"):
        ExplanationService(database).for_assessment(assessed[0].assessment_id)


def test_wrong_m6_child_reference_rejected(database, assessed, monkeypatch):
    from risk_intelligence.persistence.aggregation_repository import AggregationRepository
    original = AggregationRepository.get
    def wrong(self, identity):
        result, edges = original(self, identity)
        return result, (edges[0].model_copy(update={"child_result_id": "wrong"}),) + edges[1:]
    monkeypatch.setattr(AggregationRepository, "get", wrong)
    with pytest.raises(IntegrityError, match="child result identity"):
        ExplanationService(database).for_assessment(assessed[0].assessment_id)


def test_evidence_set_retains_snapshot_coverage_and_exact_members(database, assessed):
    from risk_intelligence.persistence.validated_members import load_validated_members
    explanation = ExplanationService(database).for_assessment(assessed[0].assessment_id)
    variable = next(v for v in explanation.variables if v.leaf.result.variable_code == 'G2.2')
    assert variable.inputs
    item = variable.inputs[0]
    members = load_validated_members(database, item.reference.validated_id)
    assert item.observations == members.facts
    assert set(item.record.snapshot_ids) <= {snapshot.snapshot_id for snapshot in item.snapshots}
    assert item.record.reliability_r == item.reference.reliability_r


def test_absent_reporting_year_is_not_substituted(database, assessed, monkeypatch):
    from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
    monkeypatch.setattr(SqlAssessmentRepository, 'get_financial_reporting_year', lambda *args: None)
    with pytest.raises(IntegrityError, match='financial reporting year'):
        ExplanationService(database).for_assessment(assessed[0].assessment_id)


def test_sql_json_disagreement_rejected_without_recalculation(database, assessed, monkeypatch):
    original = database.query
    def corrupted(sql, parameters=()):
        rows = original(sql, parameters)
        if sql.startswith('SELECT * FROM m5_variable_result'):
            return [dict(row, reliability_r='0') for row in rows]
        return rows
    monkeypatch.setattr(database, 'query', corrupted)
    with pytest.raises(IntegrityError, match='stored columns differ'):
        ExplanationService(database).for_assessment(assessed[0].assessment_id)
