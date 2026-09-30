"""M4.4 immutable validated-evidence persistence contracts."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import (
    AvailabilityStatus,
    ConflictLevel,
    ConflictResolution,
    CriticalTransformation,
    SourceType,
)
from risk_intelligence.domain.reliability import ConflictState
from risk_intelligence.ingestion.companies_house.client import (
    CompaniesHouseClient,
)
from risk_intelligence.ingestion.companies_house.policy import (
    FreshnessPolicy,
    Resource,
)
from risk_intelligence.ingestion.companies_house.service import (
    CompaniesHouseIngestion,
)
from risk_intelligence.persistence.connection import (
    IntegrityError,
    PersistenceError,
)
from risk_intelligence.persistence.validated_repository import (
    ValidatedEvidenceRepository,
)
from risk_intelligence.validation.engine import ValidationEngine
from risk_intelligence.validation.governance import (
    OFFICER_EVENTS_24M,
    governance_registry,
)
from risk_intelligence.validation.governance_handoff import (
    load_governance_evidence,
)
from risk_intelligence.validation.policy import assess_reliability


def no_conflict() -> ConflictState:
    return ConflictState(
        level=ConflictLevel.NONE,
        resolution=ConflictResolution.NONE,
        reason="No competing governance population",
    )


def _ingest(database, storage, api):
    service = CompaniesHouseIngestion(
        database,
        storage,
        CompaniesHouseClient(api, pause=lambda _: None),
        FreshnessPolicy(page_size=2),
        clock=lambda: api.now,
    )
    return service.ingest(
        "ZZ000002",
        date(2026, 9, 29),
        "m44-run",
    )


def _governance_assessment(database, storage, api):
    result = _ingest(database, storage, api)

    records = load_governance_evidence(
        database,
        processing_run_id="m44-run",
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number="ZZ000002",
        assessment_date=date(2026, 9, 29),
        window_start=date(2024, 9, 29),
        resources=(Resource.OFFICERS,),
    )

    report = ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )

    assessment = assess_reliability(
        report,
        SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,
        no_conflict(),
        transformation_chain=(
            "Companies House API",
            "M2 deterministic parser",
        ),
    )

    return result, records, assessment


def test_migration_008_is_applied(database) -> None:
    rows = database.query(
        """
        SELECT version, name
        FROM schema_migration
        ORDER BY version
        """
    )

    assert rows[-1] == {
        "version": 8,
        "name": "008_validated_analytical_evidence.sql",
    }


def test_governance_validated_set_round_trip(
    database,
    storage,
    api,
) -> None:
    result, records, assessment = _governance_assessment(
        database,
        storage,
        api,
    )

    repository = ValidatedEvidenceRepository(database)

    snapshot_ids = tuple(
        item.snapshot_id for item in records.snapshots
    )

    repository.save_evidence_set(
        validated_evidence_set_id="validated-officers",
        company_id=result.run.company_id,
        company_number="ZZ000002",
        processing_run_id="m44-run",
        assessment_date=date(2026, 9, 29),
        evidence_set_type=OFFICER_EVENTS_24M,
        analytical_window_start=date(2024, 9, 29),
        analytical_window_end=date(2026, 9, 29),
        source_resources=(Resource.OFFICERS.value,),
        snapshot_ids=snapshot_ids,
        availability_status=AvailabilityStatus.AVAILABLE,
        assessment=assessment,
    )

    restored = repository.get_evidence_set(
        "validated-officers"
    )

    assert restored is not None
    assert restored.snapshot_ids == snapshot_ids
    assert restored.source_resources == (
        Resource.OFFICERS.value,
    )
    assert restored.validation_report == assessment.validation
    assert restored.conflict_state == assessment.conflict
    assert restored.source_quality_s == Decimal("0.98")
    assert restored.extraction_quality_e == Decimal("0.99")
    assert restored.validation_factor_v == Decimal("0.00")
    assert restored.conflict_factor_c == Decimal("0.00")
    assert restored.reliability_r == Decimal("0.9702")
    assert restored.validation_ruleset_version == (
        "governance-validation-v1"
    )
    assert restored.reliability_policy_version == (
        "m4-reliability-v1"
    )


def test_exact_retry_is_idempotent(
    database,
    storage,
    api,
) -> None:
    result, records, assessment = _governance_assessment(
        database,
        storage,
        api,
    )

    repository = ValidatedEvidenceRepository(database)

    arguments = dict(
        validated_evidence_set_id="validated-officers",
        company_id=result.run.company_id,
        company_number="ZZ000002",
        processing_run_id="m44-run",
        assessment_date=date(2026, 9, 29),
        evidence_set_type=OFFICER_EVENTS_24M,
        analytical_window_start=date(2024, 9, 29),
        analytical_window_end=date(2026, 9, 29),
        source_resources=(Resource.OFFICERS.value,),
        snapshot_ids=tuple(
            item.snapshot_id for item in records.snapshots
        ),
        availability_status=AvailabilityStatus.AVAILABLE,
        assessment=assessment,
    )

    repository.save_evidence_set(**arguments)
    repository.save_evidence_set(**arguments)

    assert database.query(
        """
        SELECT count(*) AS n
        FROM validated_evidence_set
        """
    )[0]["n"] == 1


def test_conflicting_retry_is_rejected(
    database,
    storage,
    api,
) -> None:
    result, records, assessment = _governance_assessment(
        database,
        storage,
        api,
    )

    repository = ValidatedEvidenceRepository(database)

    arguments = dict(
        validated_evidence_set_id="validated-officers",
        company_id=result.run.company_id,
        company_number="ZZ000002",
        processing_run_id="m44-run",
        assessment_date=date(2026, 9, 29),
        evidence_set_type=OFFICER_EVENTS_24M,
        analytical_window_start=date(2024, 9, 29),
        analytical_window_end=date(2026, 9, 29),
        source_resources=(Resource.OFFICERS.value,),
        snapshot_ids=tuple(
            item.snapshot_id for item in records.snapshots
        ),
        availability_status=AvailabilityStatus.AVAILABLE,
        assessment=assessment,
    )

    repository.save_evidence_set(**arguments)

    with pytest.raises(
        IntegrityError,
        match="Conflicting immutable",
    ):
        repository.save_evidence_set(
            **(
                arguments
                | {
                    "analytical_window_start":
                        date(2025, 1, 1)
                }
            )
        )


def test_sql_trigger_blocks_mutation(
    database,
    storage,
    api,
) -> None:
    result, records, assessment = _governance_assessment(
        database,
        storage,
        api,
    )

    repository = ValidatedEvidenceRepository(database)

    repository.save_evidence_set(
        validated_evidence_set_id="validated-officers",
        company_id=result.run.company_id,
        company_number="ZZ000002",
        processing_run_id="m44-run",
        assessment_date=date(2026, 9, 29),
        evidence_set_type=OFFICER_EVENTS_24M,
        analytical_window_start=date(2024, 9, 29),
        analytical_window_end=date(2026, 9, 29),
        source_resources=(Resource.OFFICERS.value,),
        snapshot_ids=tuple(
            item.snapshot_id for item in records.snapshots
        ),
        availability_status=AvailabilityStatus.AVAILABLE,
        assessment=assessment,
    )

    with pytest.raises(PersistenceError):
        database.execute(
            """
            UPDATE validated_evidence_set
            SET evidence_set_type='OTHER'
            WHERE validated_evidence_set_id='validated-officers'
            """
        )


def test_snapshot_resource_mismatch_is_rejected(
    database,
    storage,
    api,
) -> None:
    result, records, assessment = _governance_assessment(
        database,
        storage,
        api,
    )

    repository = ValidatedEvidenceRepository(database)

    with pytest.raises(
        IntegrityError,
        match="resources do not match",
    ):
        repository.save_evidence_set(
            validated_evidence_set_id="bad-resource",
            company_id=result.run.company_id,
            company_number="ZZ000002",
            processing_run_id="m44-run",
            assessment_date=date(2026, 9, 29),
            evidence_set_type=OFFICER_EVENTS_24M,
            analytical_window_start=date(2024, 9, 29),
            analytical_window_end=date(2026, 9, 29),
            source_resources=(Resource.FILINGS.value,),
            snapshot_ids=tuple(
                item.snapshot_id for item in records.snapshots
            ),
            availability_status=AvailabilityStatus.AVAILABLE,
            assessment=assessment,
        )
