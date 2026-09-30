"""Offline M2 -> additive obligation -> M5 -> immutable M6 leaf handoff."""

from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import AssessmentStatus
from risk_intelligence.domain.runs import Assessment
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.connection import IntegrityError, PersistenceError
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.risk_variables.core import DEFINITIONS
from risk_intelligence.risk_variables.service import RiskVariableService
from tests.m2.conftest import NOW, NUMBER
from tests.m5.test_obligations import prepare


def context(database, obligation):
    SqlAssessmentRepository(database).save_assessment(Assessment(
        assessment_id="m5", company_id=obligation.company_id, company_number=NUMBER,
        processing_run_id="obligation-run", assessment_date=NOW.date(), status=AssessmentStatus.PARTIAL,
        risk_model_version="1", reliability_model_version="m4-reliability-v1", er_model_version="1",
        data_dictionary_version="1",
    ))


def test_sql_handoff_all_eleven_leaves_immutable_retry_and_no_r2(database, storage, api, monkeypatch):
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
    with pytest.raises(IntegrityError, match="eleven"):
        repository.for_assessment("m5")
    leaves = RiskVariableService(database).calculate_and_persist(assessment_id="m5", scope="COMPANY", calculated_at=NOW)
    original = leaves[0]
    forged = original.model_copy(update={"result": original.result.model_copy(update={"reliability_r": Decimal('.99')})})
    with pytest.raises(IntegrityError, match="reproduce"):
        repository.save(forged)
