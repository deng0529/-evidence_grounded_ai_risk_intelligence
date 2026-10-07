"""Director and control calculations over actual M4 validation results."""

from datetime import date, timedelta
from decimal import Decimal

from risk_intelligence.domain.enums import ConflictLevel, ConflictResolution, CriticalTransformation, ExtractionMethod, SourceType
from risk_intelligence.domain.facts import StructuredFact
from risk_intelligence.domain.reliability import ConflictState
from risk_intelligence.ingestion.companies_house.parsing import observations
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.persistence.validated_members import ValidatedMembers
from risk_intelligence.persistence.validated_repository import PersistedValidatedEvidenceSet
from risk_intelligence.risk_variables.core import Reason
from risk_intelligence.risk_variables.governance import calculate_population, months_before
from risk_intelligence.validation.governance import GovernanceEvidenceSet
from risk_intelligence.validation.policy import assess_reliability
from tests.m4.test_governance import ASSESSMENT, COMPANY, snapshot, validate


def director(identity, appointed="2020-01-01", resigned=None, **changes):
    item = {"name": "SYNTHETIC", "officer_role": "director", "appointed_on": appointed,
            "links": {"self": "/appointment/" + identity, "officer": {"appointments": "/person/" + identity}}}
    if resigned is not None:
        item["resigned_on"] = resigned
    return item | changes


def members(items=(), *, psc=False, complete=True):
    resource = Resource.PSC if psc else Resource.OFFICERS
    facts = []
    for index, item in enumerate(items):
        for number, observation in enumerate(observations(resource, item, COMPANY)):
            identity = f"{index}-{number}"
            facts.append(StructuredFact(fact_id=identity, company_id="company", company_number=COMPANY,
                canonical_concept=observation.concept, value=observation.value, availability_status=observation.status,
                source_id="source", evidence_ids=("e-" + identity,), extraction_method=ExtractionMethod.API_DIRECT,
                processing_run_id="run", subject_identifier=observation.subject))
    snapshots = (snapshot(resource, complete=complete),) + ((snapshot(Resource.STATEMENTS),) if psc else ())
    records = GovernanceEvidenceSet(input_id="set", input_type="PSC_EVENTS_36M" if psc else "OFFICER_EVENTS_24M",
        company_number=COMPANY, assessment_date=ASSESSMENT, window_start=months_before(ASSESSMENT, 36 if psc else 24),
        snapshots=snapshots, facts=tuple(facts))
    assessment = assess_reliability(validate(records), SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,
        ConflictState(level=ConflictLevel.NONE, resolution=ConflictResolution.NONE, reason="No conflict"))
    components = assessment.calculation.components
    persisted = PersistedValidatedEvidenceSet(validated_evidence_set_id="set", company_id="company", company_number=COMPANY,
        processing_run_id="run", assessment_date=ASSESSMENT, evidence_set_type=records.input_type,
        analytical_window_start=records.window_start, analytical_window_end=ASSESSMENT,
        source_resources=tuple(s.resource.value for s in snapshots), snapshot_ids=tuple(s.snapshot_id for s in snapshots),
        availability_status=assessment.validation.context.availability_status, validation_report=assessment.validation,
        conflict_state=assessment.conflict, source_quality_s=components.s, extraction_quality_e=components.e,
        validation_factor_v=components.v, conflict_factor_c=components.c, reliability_r=assessment.calculation.reliability_r,
        validation_status=assessment.validation.outcomes[0].result, validation_ruleset_version=assessment.validation.ruleset_version,
        reliability_policy_version=assessment.calculation.policy_version)
    return ValidatedMembers(persisted, tuple(facts))


def test_departure_counts_identities_and_initial_population():
    population = members((director("a", resigned="2025-01-01"), director("b"),
                          director("new", appointed="2025-02-01", resigned="2025-03-01")))
    result = calculate_population("G2.1", population, assessment_date=ASSESSMENT)
    assert result.value == 1  # two distinct departures / two pre-window directors
    assert result.inputs[0].validated_id == "set"
    assert result.inputs[0].reliability_r == Decimal('.9702')
    assert result.trace[-1].operation == "departure_rate"


def test_distinct_identity_not_appointment_rows_and_half_open_boundary():
    first = director("a", resigned="2024-09-30")
    second = director("a", resigned="2025-03-01")
    second["links"] = {"self": "/appointment/a2", "officer": {"appointments": "/person/a"}}
    population = members((first, second, director("b")))
    assert calculate_population("G2.1", population, assessment_date=ASSESSMENT).value == Decimal('.5')


def test_tenure_uses_exact_dates_median_and_no_appointed_before_substitution():
    population = members((director("a", appointed="2021-09-30"), director("b", appointed="2023-09-30")))
    result = calculate_population("G2.2", population, assessment_date=ASSESSMENT)
    assert abs(result.value - Decimal('4.000082137210209655228')) < Decimal('0.001')
    incomplete = members((director("a", appointed=None, appointed_before="1992-01-01"),))
    assert calculate_population("G2.2", incomplete, assessment_date=ASSESSMENT).reasons == (Reason.MISSING_APPOINTMENT,)


def test_missing_person_identity_is_not_inferred_from_name_or_event_id():
    item = director("a")
    item["links"] = {"self": "/appointment/a"}
    assert calculate_population("G2.1", members((item,)), assessment_date=ASSESSMENT).reasons == (Reason.AMBIGUOUS_IDENTITY,)


def test_concentration_uses_deterministic_windows_and_empty_is_unknown():
    population = members((director("a", resigned="2025-01-01"), director("b", resigned="2025-02-01"), director("c")))
    result = calculate_population("G2.3", population, assessment_date=ASSESSMENT)
    assert abs(result.value - Decimal(2) / Decimal(3)) < Decimal('1e-27')
    assert result.selected_dates[1] - result.selected_dates[0] == timedelta(days=90)
    assert calculate_population("G2.3", members((director("a"),)), assessment_date=ASSESSMENT).reasons == (Reason.NO_COMPUTABLE_WINDOW,)


def test_incomplete_population_zero_denominator_and_empty_tenure():
    assert calculate_population("G2.1", members((director("a"),), complete=False), assessment_date=ASSESSMENT).value is None
    assert calculate_population("G2.1", members((director("a", appointed="2025-01-01"),)), assessment_date=ASSESSMENT).reasons == (Reason.ZERO_DENOMINATOR,)
    assert calculate_population("G2.2", members(), assessment_date=ASSESSMENT).reasons == (Reason.EMPTY_POPULATION,)


def test_psc_complete_empty_zero_explicit_exit_and_ambiguous_notification():
    assert calculate_population("G3.1", members(psc=True), assessment_date=ASSESSMENT).value == 0
    item = {"kind": "individual-person-with-significant-control", "name": "SYNTHETIC",
            "notified_on": "2020-01-01", "ceased_on": "2025-01-01", "links": {"self": "/psc/a"}}
    assert calculate_population("G3.1", members((item,), psc=True), assessment_date=ASSESSMENT).value == 1
    ambiguous = item | {"notified_on": "2024-01-01"}
    assert calculate_population("G3.1", members((ambiguous,), psc=True), assessment_date=ASSESSMENT).reasons == (Reason.AMBIGUOUS_CONTROL,)


def test_calendar_months_clamp_leap_boundary():
    assert months_before(date(2024, 2, 29), 24) == date(2022, 2, 28)


def test_active_tenure_excludes_retired_director_with_legacy_unknown_start_date():
    active = director('active', appointed='2021-09-30')
    retired = director('retired', appointed=None, appointed_before='1992-01-01', resigned='2000-01-01')
    expected = calculate_population('G2.2', members((active,)), assessment_date=ASSESSMENT)
    actual = calculate_population('G2.2', members((active, retired)), assessment_date=ASSESSMENT)
    assert actual.value == expected.value and actual.value is not None
    assert actual.inputs[0].reliability_r == expected.inputs[0].reliability_r
    # History-dependent variables must still require that retired start date.
    assert calculate_population('G2.1', members((active, retired)), assessment_date=ASSESSMENT).reasons == (Reason.MISSING_APPOINTMENT,)
