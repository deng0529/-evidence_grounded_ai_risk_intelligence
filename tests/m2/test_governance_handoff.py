"""Real SQLite M2 -> M4 governance handoff and reliability integration."""

from datetime import date
from decimal import Decimal

from risk_intelligence.domain.enums import (
    ConflictLevel,
    ConflictResolution,
    CriticalTransformation,
    SourceType,
)
from risk_intelligence.domain.reliability import ConflictState
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient
from risk_intelligence.ingestion.companies_house.policy import (
    FreshnessPolicy,
    Resource,
)
from risk_intelligence.ingestion.companies_house.service import (
    CompaniesHouseIngestion,
)
from risk_intelligence.persistence.connection import Database
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.validation.engine import ValidationEngine
from risk_intelligence.validation.governance import (
    FILING_EVENTS_36M,
    OFFICER_EVENTS_24M,
    PSC_EVENTS_36M,
    governance_registry,
)
from risk_intelligence.validation.governance_handoff import (
    load_governance_evidence,
)
from risk_intelligence.validation.policy import assess_reliability

from conftest import FakeAPI, NOW, NUMBER


WINDOW36 = date(2023, 9, 29)
WINDOW24 = date(2024, 9, 29)


def ingest(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
    run_id: str,
):
    service = CompaniesHouseIngestion(
        database,
        storage,
        CompaniesHouseClient(api, pause=lambda _: None),
        FreshnessPolicy(page_size=2),
        clock=lambda: api.now,
    )
    return service.ingest(NUMBER, NOW.date(), run_id)


def no_conflict() -> ConflictState:
    return ConflictState(
        level=ConflictLevel.NONE,
        resolution=ConflictResolution.NONE,
        reason="No competing governance population",
    )


def test_sql_handoff_reconstructs_officer_population(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
) -> None:
    ingest(database, storage, api, "first")

    records = load_governance_evidence(
        database,
        processing_run_id="first",
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=NUMBER,
        assessment_date=NOW.date(),
        window_start=WINDOW24,
        resources=(Resource.OFFICERS,),
    )

    assert len(records.snapshots) == 1
    assert records.snapshots[0].resource == Resource.OFFICERS
    assert records.facts
    assert any(
        fact.canonical_concept == "OFFICERS_APPOINTED_ON"
        for fact in records.facts
    )

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assert report.admissible


def test_sql_handoff_reconstructs_joint_psc_population(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
) -> None:
    ingest(database, storage, api, "first")

    records = load_governance_evidence(
        database,
        processing_run_id="first",
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=NUMBER,
        assessment_date=NOW.date(),
        window_start=WINDOW36,
        resources=(Resource.PSC, Resource.STATEMENTS),
    )

    assert {item.resource for item in records.snapshots} == {
        Resource.PSC,
        Resource.STATEMENTS,
    }

    assert any(
        fact.canonical_concept == "PSC_NOTIFIED_ON"
        for fact in records.facts
    )

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assert report.admissible


def test_empty_psc_is_preserved_as_complete_sql_evidence(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
) -> None:
    api.payloads["persons-with-significant-control"] = []
    api.payloads["persons-with-significant-control-statements"] = []

    ingest(database, storage, api, "empty")

    records = load_governance_evidence(
        database,
        processing_run_id="empty",
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=NUMBER,
        assessment_date=NOW.date(),
        window_start=WINDOW36,
        resources=(Resource.PSC, Resource.STATEMENTS),
    )

    assert records.facts == ()

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assert report.admissible
    assert report.context.evidence_ids


def test_reused_snapshot_reconstructs_original_facts_without_r2(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
) -> None:
    ingest(database, storage, api, "first")
    api.calls.clear()

    ingest(database, storage, api, "second")

    assert api.calls == []

    records = load_governance_evidence(
        database,
        processing_run_id="second",
        input_id="filings",
        input_type=FILING_EVENTS_36M,
        company_number=NUMBER,
        assessment_date=NOW.date(),
        window_start=WINDOW36,
        resources=(Resource.FILINGS,),
    )

    assert records.snapshots[0].reused_snapshot_id is not None
    assert records.facts
    assert any(
        fact.canonical_concept == "FILINGS_DATE"
        for fact in records.facts
    )

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assert report.admissible


def test_governance_api_reliability_uses_frozen_policy_without_fake_support(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
) -> None:
    ingest(database, storage, api, "first")

    records = load_governance_evidence(
        database,
        processing_run_id="first",
        input_id="filings",
        input_type=FILING_EVENTS_36M,
        company_number=NUMBER,
        assessment_date=NOW.date(),
        window_start=WINDOW36,
        resources=(Resource.FILINGS,),
    )

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assessment = assess_reliability(
        report,
        SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,
        no_conflict(),
        transformation_chain=("Companies House API", "M2 deterministic parser"),
    )

    assert assessment.support.strength.value == "NONE"
    assert assessment.calculation.components.s == Decimal('0.98')
    assert assessment.calculation.components.e == Decimal('0.99')
    assert assessment.calculation.components.v == Decimal('0.00')
    assert assessment.calculation.components.c == Decimal('0.00')
    assert assessment.calculation.reliability_r == Decimal('0.9702')
    assert assessment.calculation.supported_analytical_evidence


def test_incomplete_resource_hard_failure_forces_reliability_zero(
    database: Database,
    storage: LocalStorage,
    api: FakeAPI,
) -> None:
    api.failures["officers:1"] = 503

    service = CompaniesHouseIngestion(
        database,
        storage,
        CompaniesHouseClient(api, pause=lambda _: None),
        FreshnessPolicy(page_size=1),
        clock=lambda: api.now,
    )

    service.ingest(NUMBER, NOW.date(), "partial")

    records = load_governance_evidence(
        database,
        processing_run_id="partial",
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=NUMBER,
        assessment_date=NOW.date(),
        window_start=WINDOW24,
        resources=(Resource.OFFICERS,),
    )

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assert not report.admissible

    assessment = assess_reliability(
        report,
        SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,
        no_conflict(),
    )

    assert assessment.calculation.reliability_r == Decimal('0')
    assert not assessment.calculation.supported_analytical_evidence
