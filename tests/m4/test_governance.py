"""Focused deterministic M4 governance evidence-set validation."""

from datetime import UTC, date, datetime

from risk_intelligence.domain.enums import (
    AvailabilityStatus,
    ExtractionMethod,
)
from risk_intelligence.domain.facts import (
    DateValue,
    StructuredFact,
    TextValue,
)
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.persistence.ingestion_repository import Snapshot
from risk_intelligence.validation.engine import ValidationEngine
from risk_intelligence.validation.governance import (
    FILING_EVENTS_36M,
    GOVERNANCE_RULESET_VERSION,
    OFFICER_EVENTS_24M,
    PSC_EVENTS_36M,
    GovernanceEvidenceSet,
    governance_registry,
)


ASSESSMENT = date(2026, 9, 30)
WINDOW36 = date(2023, 9, 30)
WINDOW24 = date(2024, 9, 30)
COMPANY = "ZZ000003"


def snapshot(
    resource: Resource,
    *,
    complete: bool = True,
    start: date = WINDOW36,
    end: date = ASSESSMENT,
    identity: str | None = None,
) -> Snapshot:
    return Snapshot(
        snapshot_id=identity or f"snap-{resource.name.lower()}",
        processing_run_id="run",
        company_id="company",
        resource=resource,
        checked_at=datetime(2026, 9, 30, 12, tzinfo=UTC),
        coverage_start=start,
        coverage_end=end,
        complete=complete,
        availability_status=(
            AvailabilityStatus.AVAILABLE
            if complete
            else AvailabilityStatus.RETRIEVAL_FAILED
        ),
        page_count=1 if complete else 0,
        item_count=0,
        error_code=None if complete else "HTTP_503",
    )


def fact(
    identity: str,
    subject: str,
    concept: str,
    value,
) -> StructuredFact:
    if isinstance(value, date):
        typed = DateValue(value=value)
    else:
        typed = TextValue(value=value)

    return StructuredFact(
        fact_id=identity,
        company_id="company",
        company_number=COMPANY,
        canonical_concept=concept,
        value=typed,
        availability_status=AvailabilityStatus.AVAILABLE,
        source_id="source",
        evidence_ids=(f"e-{identity}",),
        extraction_method=ExtractionMethod.API_DIRECT,
        processing_run_id="run",
        subject_identifier=subject,
    )


def validate(records: GovernanceEvidenceSet):
    return ValidationEngine(governance_registry()).validate(
        records.analytical_input()
    )


def test_registry_is_frozen_and_deterministic() -> None:
    registry = governance_registry()

    assert registry.ruleset_version == GOVERNANCE_RULESET_VERSION

    assert [
        rule.definition.rule_id
        for rule in registry.applicable(OFFICER_EVENTS_24M)
    ] == [
        "governance.duplicate_event",
        "governance.event_chronology",
        "governance.officer_anchor_coverage",
        "governance.pagination_coverage",
        "governance.window_coverage",
    ]


def test_complete_officer_population_is_admissible() -> None:
    records = GovernanceEvidenceSet(
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW24,
        snapshots=(snapshot(Resource.OFFICERS),),
        facts=(
            fact(
                "a1",
                "officer-a",
                "OFFICERS_APPOINTED_ON",
                date(2020, 1, 1),
            ),
            fact(
                "a2",
                "officer-a",
                "OFFICERS_RESIGNED_ON",
                date(2026, 1, 1),
            ),
            fact(
                "b1",
                "officer-b",
                "OFFICERS_APPOINTED_BEFORE",
                "1992-01-01",
            ),
        ),
    )

    result = validate(records)

    assert result.admissible
    assert all(outcome.result.value == "PASS" for outcome in result.outcomes)


def test_officer_reverse_chronology_is_hard_failure() -> None:
    records = GovernanceEvidenceSet(
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW24,
        snapshots=(snapshot(Resource.OFFICERS),),
        facts=(
            fact(
                "a1",
                "officer-a",
                "OFFICERS_APPOINTED_ON",
                date(2026, 6, 1),
            ),
            fact(
                "a2",
                "officer-a",
                "OFFICERS_RESIGNED_ON",
                date(2025, 6, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.event_chronology"
    )

    assert outcome.result.value == "FAIL"
    assert outcome.hard_fail
    assert not result.admissible


def test_officer_without_appointment_anchor_is_hard_failure() -> None:
    records = GovernanceEvidenceSet(
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW24,
        snapshots=(snapshot(Resource.OFFICERS),),
        facts=(
            fact(
                "a1",
                "officer-a",
                "OFFICERS_RESIGNED_ON",
                date(2026, 1, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.officer_anchor_coverage"
    )

    assert outcome.result.value == "FAIL"
    assert outcome.hard_fail
    assert not result.admissible


def test_duplicate_event_observation_is_hard_failure() -> None:
    records = GovernanceEvidenceSet(
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW24,
        snapshots=(snapshot(Resource.OFFICERS),),
        facts=(
            fact(
                "a1",
                "officer-a",
                "OFFICERS_APPOINTED_ON",
                date(2020, 1, 1),
            ),
            fact(
                "a2",
                "officer-a",
                "OFFICERS_APPOINTED_ON",
                date(2020, 1, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.duplicate_event"
    )

    assert outcome.result.value == "FAIL"
    assert not result.admissible


def test_incomplete_pagination_is_not_hidden_by_available_events() -> None:
    records = GovernanceEvidenceSet(
        input_id="filings",
        input_type=FILING_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(
            snapshot(Resource.FILINGS, complete=False),
        ),
        facts=(
            fact(
                "f1",
                "filing-a",
                "FILINGS_DATE",
                date(2026, 1, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.pagination_coverage"
    )

    assert outcome.result.value == "FAIL"
    assert not result.admissible


def test_insufficient_window_coverage_is_hard_failure() -> None:
    records = GovernanceEvidenceSet(
        input_id="filings",
        input_type=FILING_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(
            snapshot(
                Resource.FILINGS,
                start=date(2024, 1, 1),
            ),
        ),
        facts=(),
    )

    result = validate(records)
    outcome = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.window_coverage"
    )

    assert outcome.result.value == "FAIL"
    assert not result.admissible


def test_empty_psc_population_can_be_valid_when_both_resources_complete() -> None:
    records = GovernanceEvidenceSet(
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(
            snapshot(Resource.PSC),
            snapshot(Resource.STATEMENTS),
        ),
        facts=(),
    )

    result = validate(records)

    assert result.admissible
    assert result.context.evidence_ids
    assert all(outcome.result.value == "PASS" for outcome in result.outcomes)


def test_psc_statements_failure_makes_only_psc_population_inadmissible() -> None:
    records = GovernanceEvidenceSet(
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(
            snapshot(Resource.PSC),
            snapshot(Resource.STATEMENTS, complete=False),
        ),
        facts=(),
    )

    result = validate(records)

    psc = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.psc_coverage"
    )

    assert psc.result.value == "FAIL"
    assert not result.admissible

    # This failure is local to the PSC evidence set. It does not invalidate
    # unrelated filing/officer populations.
    filings = GovernanceEvidenceSet(
        input_id="filings",
        input_type=FILING_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(snapshot(Resource.FILINGS),),
        facts=(),
    )

    assert validate(filings).admissible


def test_psc_reverse_chronology_is_hard_failure() -> None:
    records = GovernanceEvidenceSet(
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(
            snapshot(Resource.PSC),
            snapshot(Resource.STATEMENTS),
        ),
        facts=(
            fact(
                "p1",
                "psc-a",
                "PSC_NOTIFIED_ON",
                date(2026, 5, 1),
            ),
            fact(
                "p2",
                "psc-a",
                "PSC_CEASED_ON",
                date(2025, 5, 1),
            ),
        ),
    )

    result = validate(records)

    chronology = next(
        item
        for item in result.outcomes
        if item.rule_id == "governance.event_chronology"
    )

    assert chronology.result.value == "FAIL"
    assert not result.admissible


def test_missing_required_resource_is_explicit_failure() -> None:
    records = GovernanceEvidenceSet(
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(snapshot(Resource.PSC),),
        facts=(),
    )

    result = validate(records)

    assert not result.admissible
    assert (
        result.context.availability_status
        == AvailabilityStatus.RETRIEVAL_FAILED
    )

def test_future_officer_event_fails_assessment_boundary() -> None:
    records = GovernanceEvidenceSet(
        input_id="officers",
        input_type=OFFICER_EVENTS_24M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW24,
        snapshots=(snapshot(Resource.OFFICERS),),
        facts=(
            fact(
                "future-officer",
                "officer-a",
                "OFFICERS_APPOINTED_ON",
                date(2026, 10, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item for item in result.outcomes
        if item.rule_id == "governance.window_coverage"
    )

    assert outcome.result.value == "FAIL"
    assert outcome.hard_fail
    assert not result.admissible


def test_future_psc_event_fails_assessment_boundary() -> None:
    records = GovernanceEvidenceSet(
        input_id="psc",
        input_type=PSC_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(
            snapshot(Resource.PSC),
            snapshot(Resource.STATEMENTS),
        ),
        facts=(
            fact(
                "future-psc",
                "psc-a",
                "PSC_NOTIFIED_ON",
                date(2026, 10, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item for item in result.outcomes
        if item.rule_id == "governance.window_coverage"
    )

    assert outcome.result.value == "FAIL"
    assert not result.admissible


def test_future_filing_event_fails_assessment_boundary() -> None:
    records = GovernanceEvidenceSet(
        input_id="filings",
        input_type=FILING_EVENTS_36M,
        company_number=COMPANY,
        assessment_date=ASSESSMENT,
        window_start=WINDOW36,
        snapshots=(snapshot(Resource.FILINGS),),
        facts=(
            fact(
                "future-filing",
                "filing-a",
                "FILINGS_DATE",
                date(2026, 10, 1),
            ),
        ),
    )

    result = validate(records)
    outcome = next(
        item for item in result.outcomes
        if item.rule_id == "governance.window_coverage"
    )

    assert outcome.result.value == "FAIL"
    assert outcome.hard_fail
    assert not result.admissible
