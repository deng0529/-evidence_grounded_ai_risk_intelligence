pytest_plugins = ("tests.m2.conftest",)

from decimal import Decimal

from risk_intelligence.persistence.aggregation_repository import AggregationRepository
from risk_intelligence.risk_variables.core import model_aggregation_config
from risk_intelligence.risk_variables.service import RiskVariableService
from risk_intelligence.services.aggregation import AggregationService
from tests.m2.conftest import NOW
from tests.m5.test_obligations import prepare
from risk_intelligence.domain.enums import AssessmentStatus
from risk_intelligence.domain.runs import Assessment
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from tests.m2.conftest import NUMBER


def context(database, obligation, version="1.2"):
    SqlAssessmentRepository(database).save_assessment(Assessment(
        assessment_id="m5", company_id=obligation.company_id, company_number=NUMBER,
        processing_run_id="obligation-run", assessment_date=NOW.date(), status=AssessmentStatus.PARTIAL,
        risk_model_version=version, reliability_model_version="m4-reliability-v1", er_model_version=version,
        data_dictionary_version="1",
    ))
    SqlAssessmentRepository(database).save_financial_reporting_year("m5", 2025)


def test_registry_config_is_exact_v12_partition():
    cfg = model_aggregation_config("1.2")
    assert cfg["GOVERNANCE"]["variables"] == ("G1.1", "G1.2", "G2.2")
    assert cfg["FINANCIAL"]["variables"] == ("F1.1", "F2.2", "F2.3")
    assert cfg["GOVERNANCE"]["weight"] == Decimal(".40")
    assert cfg["FINANCIAL"]["weight"] == Decimal(".60")


def test_m6_consumes_exact_m5_handoff_and_persists_three_parents(database, storage, api):
    obligation = prepare(database, storage, api, due="2027-09-30", period="2026-12-31")
    context(database, obligation, "1.2")
    RiskVariableService(database).calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)

    results = AggregationService(database).calculate_and_persist(assessment_id="m5", calculated_at=NOW)
    assert tuple(result.node_code for result in results) == ("GOVERNANCE", "FINANCIAL", "OVERALL")
    assert all(abs(result.belief.low_belief + result.belief.high_belief + result.belief.unknown_belief - 1) <= Decimal("1e-8") for result in results)
    saved = AggregationRepository(database).for_assessment("m5")
    assert {result.node_code for result in saved} == {"GOVERNANCE", "FINANCIAL", "OVERALL"}
    overall = next(result for result in results if result.node_code == "OVERALL")
    stored = AggregationRepository(database).get(overall.aggregation_result_id)
    assert stored is not None
    _, edges = stored
    assert [(edge.child_code, edge.importance_weight) for edge in edges] == [("GOVERNANCE", Decimal(".40")), ("FINANCIAL", Decimal(".60"))]
    assert database.query("PRAGMA foreign_key_check") == []


def test_m6_retry_is_idempotent(database, storage, api):
    obligation = prepare(database, storage, api, due="2027-09-30", period="2026-12-31")
    context(database, obligation, "1.2")
    RiskVariableService(database).calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)
    first = AggregationService(database).calculate_and_persist(assessment_id="m5", calculated_at=NOW)
    second = AggregationService(database).calculate_and_persist(assessment_id="m5", calculated_at=NOW)
    assert second == first
    assert len(AggregationRepository(database).for_assessment("m5")) == 3
