"""Source-grounded obligation validation; no variable calculation occurs in M4."""

from datetime import date
from decimal import Decimal

import pytest

from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient
from risk_intelligence.ingestion.companies_house.policy import FreshnessPolicy, Resource
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import PersistenceError
from risk_intelligence.persistence.validated_members import load_validated_members
from risk_intelligence.validation.governance import FILING_EVENTS_36M, GOVERNANCE_RULESET_VERSION
from risk_intelligence.validation.governance_service import GovernanceValidationService
from risk_intelligence.validation.obligation_service import ObligationValidationService
from tests.m2.conftest import NOW, NUMBER


def prepare(database, storage, api, *, kind="ACCOUNTS", due="2026-09-20", filed=None,
            period="2025-12-31", duplicate=False, missing_key=False):
    """Persist real M2 facts and a real M4 filing population from synthetic wire data."""
    profile = api.payloads["profile"]
    profile["accounts"] = {"next_accounts": {"period_end_on": period, "due_on": due}}
    profile["confirmation_statement"] = {"next_made_up_to": period, "next_due": due}
    api.payloads["filing-history"] = [] if filed is None else [{
        "transaction_id": "test-filing", "category": "accounts" if kind == "ACCOUNTS" else "confirmation-statement",
        "type": "AA" if kind == "ACCOUNTS" else "CS01", "date": filed,
        "description_values": {} if missing_key else {"made_up_date": period},
    }]
    if duplicate:
        api.payloads["filing-history"].append(api.payloads["filing-history"][0] | {"transaction_id": "competing"})
    CompaniesHouseIngestion(database, storage, CompaniesHouseClient(api, pause=lambda _: None),
                           FreshnessPolicy(), clock=lambda: NOW).ingest(NUMBER, NOW.date(), "obligation-run")
    GovernanceValidationService(database).evaluate_and_persist(
        validated_evidence_set_id="filings-set", processing_run_id="obligation-run",
        input_id="filings", input_type=FILING_EVENTS_36M, company_number=NUMBER,
        assessment_date=NOW.date(), window_start=date(2023, 9, 29), resources=(Resource.FILINGS,),
    )
    snapshot = database.query("SELECT snapshot_id FROM resource_snapshot WHERE resource='profile'")[0]["snapshot_id"]
    return ObligationValidationService(database).evaluate_and_persist(
        validated_id="obligation", kind=kind, profile_snapshot_id=snapshot,
        validated_filing_set_id="filings-set", assessment_date=NOW.date(),
    )


@pytest.mark.parametrize("kind", ["ACCOUNTS", "CONFIRMATION_STATEMENT"])
@pytest.mark.parametrize("due,filed,period,state", [
    ("2026-09-20", "2026-09-19", "2025-12-31", "FILED"),
    ("2026-09-20", "2026-09-25", "2025-12-31", "FILED"),
    ("2026-09-20", None, "2025-12-31", "OUTSTANDING"),
    ("2027-09-30", None, "2026-12-31", "OUTSTANDING"),
])
def test_supported_obligation_states(database, storage, api, kind, due, filed, period, state):
    result = prepare(database, storage, api, kind=kind, due=due, filed=filed, period=period)
    assert result.filing_state == state
    assert result.due_date == date.fromisoformat(due)
    assert result.obligation_period == date.fromisoformat(period)
    assert result.filing_date == (date.fromisoformat(filed) if filed else None)
    assert result.snapshot_observed_at == NOW
    assert result.assessment.validation.admissible
    assert result.assessment.calculation.reliability_r == Decimal("0.9702")
    assert result.assessment.calculation.policy_version == "m4-reliability-v1"
    assert result.assessment.validation.ruleset_version == "obligation-validation-v1"
    assert GOVERNANCE_RULESET_VERSION == "governance-validation-v1"
    assert ObligationValidationService(database).get("obligation") == result
    actual = database.query("SELECT fact_id FROM validated_obligation_fact ORDER BY fact_id")
    assert tuple(row["fact_id"] for row in actual) == result.fact_ids
    assert result.evidence_ids and result.source_ids
    assert database.query("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize("changes", [
    {"duplicate": True, "filed": "2026-09-20"},
    {"missing_key": True, "filed": "2026-09-20"},
    {"due": None}, {"period": None},
])
def test_unresolved_obligation_never_becomes_a_validated_deadline(database, storage, api, changes):
    result = prepare(database, storage, api, **changes)
    assert result.filing_state == "UNRESOLVED"
    assert not result.assessment.validation.admissible
    assert result.assessment.calculation.reliability_r == 0
    assert any(item.result.value == "INCONCLUSIVE" for item in result.assessment.validation.outcomes)


def test_current_deadline_does_not_attach_to_historical_filing(database, storage, api):
    # An older filing without a deterministically identified period cannot be
    # assigned the current profile deadline or treated as proven absence.
    result = prepare(database, storage, api, due="2027-09-30", period="2026-12-31",
                     filed="2026-09-20", missing_key=True)
    assert result.filing_date is None
    assert result.filing_state == "UNRESOLVED"


def test_immutable_obligation_and_member_adapter(database, storage, api):
    result = prepare(database, storage, api, filed="2026-09-20")
    service = ObligationValidationService(database)
    assert service.evaluate_and_persist(
        validated_id="obligation", kind="ACCOUNTS", profile_snapshot_id=result.profile_snapshot_id,
        validated_filing_set_id="filings-set", assessment_date=NOW.date(),
    ) == result
    members = load_validated_members(database, "filings-set")
    assert {fact.fact_id for fact in members.facts} <= set(result.fact_ids)
    assert members.validated.reliability_r == Decimal("0.9702")
    with pytest.raises(PersistenceError):
        database.execute("UPDATE validated_obligation SET obligation_kind='CONFIRMATION_STATEMENT'")
