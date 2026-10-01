"""Offline M2 -> additive obligation -> M5 -> immutable M6 leaf handoff."""

from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import AssessmentStatus
from risk_intelligence.domain.runs import Assessment
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.connection import IntegrityError, PersistenceError
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.risk_variables.core import DEFINITIONS, RISK_MODEL_VERSION, model_definitions
from risk_intelligence.risk_variables.service import RiskVariableService
from tests.m2.conftest import NOW, NUMBER
from tests.m5.test_obligations import prepare


def context(database, obligation, version=RISK_MODEL_VERSION):
    SqlAssessmentRepository(database).save_assessment(Assessment(
        assessment_id="m5", company_id=obligation.company_id, company_number=NUMBER,
        processing_run_id="obligation-run", assessment_date=NOW.date(), status=AssessmentStatus.PARTIAL,
        risk_model_version=version, reliability_model_version="m4-reliability-v1", er_model_version="1.1",
        data_dictionary_version="1",
    ))
    SqlAssessmentRepository(database).save_financial_reporting_year("m5", 2025)


def test_sql_handoff_all_active_leaves_immutable_retry_and_no_r2(database, storage, api, monkeypatch):
    obligation = prepare(database, storage, api, due="2027-09-30", period="2026-12-31")
    context(database, obligation)
    def forbidden(*args, **kwargs):
        raise AssertionError("M5 must not access raw storage")
    monkeypatch.setattr(type(storage), "read", forbidden)
    before = database.query("SELECT * FROM validated_evidence_set ORDER BY validated_evidence_set_id")
    service = RiskVariableService(database)
    leaves = service.calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)
    assert {leaf.result.variable_code for leaf in leaves} == set(DEFINITIONS)
    accounts = next(leaf for leaf in leaves if leaf.result.variable_code == "G1.1")
    assert accounts.result.raw_value == 0
    assert accounts.result.final_belief.low_belief == Decimal('.9702')
    assert accounts.result.final_belief.unknown_belief == Decimal('.0298')
    assert accounts.calculation.inputs[0].validated_id == obligation.validated_obligation_id
    assert all(leaf.result.final_belief.unknown_belief == 1 for leaf in leaves if leaf.result.variable_code != "G1.1")
    assert service.calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW) == leaves
    handoff = VariableRepository(database).for_assessment("m5")
    assert set(handoff) == {leaf.result for leaf in leaves}
    assert before == database.query("SELECT * FROM validated_evidence_set ORDER BY validated_evidence_set_id")
    assert database.query("PRAGMA foreign_key_check") == []
    assert database.query("PRAGMA integrity_check") == [{"integrity_check": "ok"}]
    with pytest.raises(PersistenceError):
        database.execute("DELETE FROM m5_variable_result")


def test_incomplete_m6_handoff_and_forged_reliability_are_rejected(database, storage, api):
    obligation = prepare(database, storage, api)
    context(database, obligation)
    repository = VariableRepository(database)
    with pytest.raises(IntegrityError, match="active model leaves"):
        repository.for_assessment("m5")
    leaves = RiskVariableService(database).calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)
    original = leaves[0]
    forged = original.model_copy(update={"result": original.result.model_copy(update={"reliability_r": Decimal('.99')})})
    with pytest.raises(IntegrityError, match="reproduce"):
        repository.save(forged)


def test_historical_model_is_explicit_and_retains_its_own_registry(database, storage, api):
    from risk_intelligence.risk_variables.core import model_definitions
    from risk_intelligence.services.company_assessment import persisted_leaves

    obligation = prepare(database, storage, api, due="2027-09-30", period="2026-12-31")
    SqlAssessmentRepository(database).save_assessment(Assessment(
        assessment_id="historical", company_id=obligation.company_id, company_number=NUMBER,
        processing_run_id="obligation-run", assessment_date=NOW.date(), status=AssessmentStatus.PARTIAL,
        risk_model_version="1", reliability_model_version="m4-reliability-v1", er_model_version="1",
        data_dictionary_version="1",
    ))
    leaves = RiskVariableService(database).calculate_and_persist(
        assessment_id="historical", scope="COMPANY", calculated_at=NOW)
    assert tuple(leaf.result.variable_code for leaf in leaves) == tuple(model_definitions("1"))
    assert {"G2.1", "G2.3", "G3.1", "F1.2"} <= {leaf.result.variable_code for leaf in leaves}
    assert all(leaf.calculation_version == "m5-calculation-v1" for leaf in leaves)
    assert persisted_leaves(database, "historical") == leaves
    with pytest.raises(ValueError, match="Unsupported"):
        model_definitions("future-unregistered")


@pytest.mark.parametrize("version", ["1.1", "1.2"])
def test_selected_year_models_only_calculate_their_registered_leaves(database, storage, api, monkeypatch, version):
    from risk_intelligence.risk_variables import service as module

    obligation = prepare(database, storage, api, due="2027-09-30", period="2026-12-31")
    context(database, obligation, version)
    seen = []
    original = module.calculate_financial
    def financial(code, *args, **kwargs):
        seen.append(code)
        assert kwargs["reporting_year"] == 2025
        return original(code, *args, **kwargs)
    monkeypatch.setattr(module, "calculate_financial", financial)
    leaves = RiskVariableService(database).calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)
    assert seen == [code for code in model_definitions(version) if code.startswith("F")]
    assert {leaf.result.variable_code for leaf in leaves} == set(model_definitions(version))
    from risk_intelligence.services.company_assessment import persisted_leaves
    assert persisted_leaves(database, "m5") == leaves
    assert all(leaf.calculation_version == "m5-calculation-v" + version for leaf in leaves)
    monkeypatch.setattr(SqlAssessmentRepository, "get_financial_reporting_year", lambda *args: None)
    with pytest.raises(IntegrityError, match="reporting year"):
        RiskVariableService(database).calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)
