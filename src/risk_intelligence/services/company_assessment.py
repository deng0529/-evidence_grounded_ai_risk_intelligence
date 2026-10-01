"""Application orchestration for a real-company M5 example; no risk methodology here."""

from datetime import date, datetime
from fractions import Fraction
from hashlib import sha256
from typing import Literal

from risk_intelligence.domain.common import Contract, Text
from risk_intelligence.domain.enums import AssessmentStatus, ProcessingStatus, TriggerType
from risk_intelligence.domain.risk import BELIEF_SUM_TOLERANCE
from risk_intelligence.domain.runs import Assessment, ProcessingRun
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.companies_house.client import company_number
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.risk_variables.core import model_definitions, LeafAssessment, RISK_MODEL_VERSION
from risk_intelligence.risk_variables.governance import months_before
from risk_intelligence.risk_variables.service import RiskVariableService
from risk_intelligence.validation.financial_service import FinancialValidationService
from risk_intelligence.validation.governance import FILING_EVENTS_36M, OFFICER_EVENTS_24M
from risk_intelligence.validation.governance_service import GovernanceValidationService
from risk_intelligence.validation.obligation_service import ObligationValidationService
from risk_intelligence.validation.policy import POLICY_VERSION


class StageIssue(Contract):
    """Visible production-service rejection; not a fabricated M4 validation result."""

    stage: Text
    input_id: Text
    reason: Text


class CompanyGoldenResult(Contract):
    """Audit envelope containing persisted leaves, original ingestion runs and limitations."""

    company_number: Text
    company_name: Text
    assessment_date: date
    reporting_year: int | None = None
    assessment_id: Text
    m2_run_id: Text
    m3_run_id: Text
    application_run_id: Text
    ingestion_mode: Literal["LIVE", "REUSED_PRODUCTION_RUNS", "REUSED_M2_REPROCESSED_M3"]
    leaves: tuple[LeafAssessment, ...]
    stage_issues: tuple[StageIssue, ...]


def _identity(*parts: str) -> str:
    return "golden-" + sha256("|".join(parts).encode()).hexdigest()


def persisted_leaves(database: Database, assessment_id: str) -> tuple[LeafAssessment, ...]:
    """Retrieve all active model leaves in registry order and verify the frozen sum tolerance."""
    repository = VariableRepository(database)
    handoff = repository.for_assessment(assessment_id)
    by_code = {}
    for result in handoff:
        leaf = repository.get(result.variable_result_id)
        if leaf is None:
            raise IntegrityError("Persisted M5 leaf disappeared")
        belief = result.final_belief
        if abs(sum(Fraction(v) for v in (belief.low_belief, belief.high_belief, belief.unknown_belief)) - 1) > BELIEF_SUM_TOLERANCE:
            raise IntegrityError("Persisted belief sum violates the frozen tolerance")
        by_code[result.variable_code] = leaf
    context = SqlAssessmentRepository(database).get_assessment(assessment_id)
    return tuple(by_code[code] for code in model_definitions(context.risk_model_version))


def _check_ingestion(database: Database, number: str, day: date, m2_id: str, m3_id: str) -> None:
    """Do not silently substitute another company's run or historical assessment date."""
    repository = SqlAssessmentRepository(database)
    for run_id, table in ((m2_id, "ingestion_run"), (m3_id, "accounts_run")):
        run = repository.get_processing_run(run_id)
        rows = database.query(f"SELECT assessment_date FROM {table} WHERE processing_run_id=?", (run_id,))
        if run is None or run.company_number != number or len(rows) != 1 or rows[0]["assessment_date"] != day.isoformat():
            raise IntegrityError("Ingestion run company/date does not match the requested assessment")
        if run.status in (ProcessingStatus.PENDING, ProcessingStatus.RUNNING):
            raise IntegrityError("Ingestion run has not reached a terminal state")


def _validate_financial(database: Database, m3_id: str, day: date, scope: Literal["COMPANY", "GROUP"]) -> list[StageIssue]:
    repository = AccountsRepository(database)
    ids = [str(row["fact_id"]) for row in database.query(
        "SELECT fact_id FROM accounts_run_fact WHERE processing_run_id=? ORDER BY fact_id", (m3_id,))]
    facts = [repository.canonical.get(identity) for identity in ids]
    if any(fact is None for fact in facts):
        raise IntegrityError("M3 run references a missing canonical observation")
    service = FinancialValidationService(database)
    issues = []
    for fact in facts:
        # Same-concept observations are passed to the existing conflict classifier;
        # the runner never chooses a winner or suppresses a disagreeing value.
        competitors = tuple(other.financial_fact_id for other in facts
                            if other.canonical_concept == fact.canonical_concept
                            and other.financial_fact_id != fact.financial_fact_id)
        service.evaluate_and_persist(
            validated_fact_id=_identity("financial", fact.financial_fact_id, day.isoformat(), scope),
            fact_id=fact.financial_fact_id, assessment_date=day, analytical_scope=scope,
            competing_fact_ids=competitors,
        )
    return issues


def run_company_assessment(database: Database, *, number: str, assessment_date: date, reporting_year: int,
                           run_id: str, calculated_at: datetime, scope: Literal["COMPANY", "GROUP"] = "COMPANY",
                           m2: CompaniesHouseIngestion | None = None, m3: AccountsIngestion | None = None,
                           reuse_runs: tuple[str, str] | None = None, reuse_m2_run: str | None = None, max_documents: int = 5) -> CompanyGoldenResult:
    """Call existing production services, or reuse explicitly named production ingestion runs.

    All M4/M4.5 output is persisted before M5 is called. Typed unavailable
    evidence can yield genuine Unknown leaves; broken handoff contracts raise.
    A unique application run/assessment is required; use persisted_leaves to replay.
    """
    number = company_number(number)
    if type(reporting_year) is not int or not 1900 <= reporting_year <= 9999:
        raise ValueError("An explicit valid financial reporting year is required")
    if reuse_runs is not None and reuse_m2_run is not None:
        raise ValueError("Choose full run reuse or M2-only reuse, not both")
    if reuse_runs is not None:
        if m2 is not None or m3 is not None:
            raise ValueError("Full run reuse does not accept ingestion services")
        m2_id, m3_id = reuse_runs
        mode = "REUSED_PRODUCTION_RUNS"
    elif reuse_m2_run is not None:
        if m2 is not None or m3 is None:
            raise ValueError("M2-only reuse requires only the M3 production service")
        m2_id, m3_id = reuse_m2_run, run_id + "-m3"
        # Re-run M3 against immutable raw evidence with the current parser/admission
        # versions.  An offline M3 service fails explicitly if any filing lacks
        # reusable raw bytes; it never silently falls back to network retrieval.
        m3.ingest(number, assessment_date, m3_id, max_documents=max_documents)
        mode = "REUSED_M2_REPROCESSED_M3"
    else:
        if m2 is None or m3 is None:
            raise ValueError("Live mode requires both production ingestion services")
        m2_id, m3_id = run_id + "-m2", run_id + "-m3"
        m2.ingest(number, assessment_date, m2_id)
        m3.ingest(number, assessment_date, m3_id, max_documents=max_documents)
        mode = "LIVE"
    _check_ingestion(database, number, assessment_date, m2_id, m3_id)
    company = SqlCompanyRepository(database).get_by_company_number(number)
    if company is None:
        raise IntegrityError("Production ingestion did not establish company identity")
    runs = SqlAssessmentRepository(database)
    if runs.get_processing_run(run_id) is not None:
        raise IntegrityError("Application run already exists; replay the persisted result")
    run = ProcessingRun(processing_run_id=run_id, company_id=company.company_id, company_number=number,
        started_at=calculated_at, status=ProcessingStatus.RUNNING, current_stage="M4_TO_M5_GOLDEN",
        trigger_type=TriggerType.DEMO_PRECOMPUTE, app_version="company-golden-v1")
    runs.save_processing_run(run)
    issues = _validate_financial(database, m3_id, assessment_date, scope)
    governance = GovernanceValidationService(database)
    set_ids = {}
    for kind, months, resources in (
        (OFFICER_EVENTS_24M, 24, (Resource.OFFICERS,)),
        (FILING_EVENTS_36M, 36, (Resource.FILINGS,)),
    ):
        identity = _identity("governance", m2_id, kind, assessment_date.isoformat())
        governance.evaluate_and_persist(validated_evidence_set_id=identity, processing_run_id=m2_id,
            input_id=identity, input_type=kind, company_number=number, assessment_date=assessment_date,
            window_start=months_before(assessment_date, months), resources=resources)
        set_ids[kind] = identity
    profiles = database.query("SELECT snapshot_id FROM resource_snapshot WHERE processing_run_id=? AND resource='profile'", (m2_id,))
    if len(profiles) != 1:
        raise IntegrityError("Selected production M2 run lacks exactly one profile snapshot")
    for kind in ("ACCOUNTS", "CONFIRMATION_STATEMENT"):
        ObligationValidationService(database).evaluate_and_persist(
            validated_id=_identity("obligation", m2_id, kind, assessment_date.isoformat()), kind=kind,
            profile_snapshot_id=str(profiles[0]["snapshot_id"]),
            validated_filing_set_id=set_ids[FILING_EVENTS_36M], assessment_date=assessment_date)
    assessment_id = run_id + "-assessment"
    runs.save_assessment(Assessment(assessment_id=assessment_id, company_id=company.company_id,
        company_number=number, processing_run_id=run_id, assessment_date=assessment_date,
        # M5 leaf output is not a completed M6 company assessment.
        status=AssessmentStatus.PARTIAL, risk_model_version=RISK_MODEL_VERSION,
        reliability_model_version=POLICY_VERSION, er_model_version=RISK_MODEL_VERSION, data_dictionary_version="1"))
    runs.save_financial_reporting_year(assessment_id, reporting_year)
    RiskVariableService(database).calculate_and_persist(assessment_id=assessment_id, scope=scope, calculated_at=calculated_at)
    leaves = persisted_leaves(database, assessment_id)
    if database.query("PRAGMA foreign_key_check"):
        raise IntegrityError("Assessment database has foreign-key violations")
    status = ProcessingStatus.PARTIAL if issues or any(leaf.calculation.reasons for leaf in leaves) else ProcessingStatus.COMPLETE
    runs.save_processing_run(run.model_copy(update={"completed_at": calculated_at, "status": status}))
    return CompanyGoldenResult(company_number=number, company_name=company.company_name,
        assessment_date=assessment_date, reporting_year=reporting_year, assessment_id=assessment_id, m2_run_id=m2_id, m3_run_id=m3_id,
        application_run_id=run_id, ingestion_mode=mode, leaves=leaves, stage_issues=tuple(issues))


def render_table(report: CompanyGoldenResult) -> str:
    """Format saved Decimal values without calculating another belief distribution."""
    lines = ["M5 REAL COMPANY GOLDEN RESULT", f"Company: {report.company_name}",
             f"Company number: {report.company_number}", f"Assessment date: {report.assessment_date}",
             f"Selected financial reporting year: {report.reporting_year}", "",
             "Variable | Raw Value | Reliability | Low Risk | High Risk | Unknown | Availability | Reason | Evidence",
             "---|---|---|---|---|---|---|---|---"]
    for leaf in report.leaves:
        result = leaf.result
        belief = result.final_belief
        reasons = ", ".join(reason.value for reason in leaf.calculation.reasons)
        status = result.availability_status.value
        evidence = ", ".join(item.kind + ":" + item.validated_id for item in leaf.calculation.inputs if item.mandatory) or "No usable mandatory inputs; see audit trace"
        values = (result.variable_code, str(result.raw_value) if result.raw_value is not None else "NULL",
                  str(result.reliability_r), str(belief.low_belief), str(belief.high_belief), str(belief.unknown_belief), status, reasons or "-", evidence)
        lines.append(" | ".join(values))
    return "\n".join(lines)
