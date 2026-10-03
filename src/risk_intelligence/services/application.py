"""M8 application orchestration and exact presentation data; no risk formulas."""

from datetime import UTC, date, datetime
from dataclasses import dataclass

from risk_intelligence.domain.common import Contract, Text
from .model_config import RuntimeConfigurationError
from risk_intelligence.ingestion.companies_house.client import company_number, RetrievalError, ParseError
from risk_intelligence.domain.risk import BeliefDistribution
from risk_intelligence.domain.runs import Assessment
from risk_intelligence.explanation import AssessmentExplanation, VariableExplanation
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError, PersistenceError
from risk_intelligence.services.aggregation import AggregationService
from risk_intelligence.services.company_assessment import run_company_assessment
from risk_intelligence.services.explanation import ExplanationService


class AssessmentChoice(Contract):
    """Persisted selection metadata; dates and financial years remain distinct."""

    assessment: Assessment
    company_name: Text | None
    reporting_year: int | None


class AssessmentView(Contract):
    """M7 remains the sole owner of the resolved traceability tree."""

    company_name: Text | None
    explanation: AssessmentExplanation


@dataclass(frozen=True)
class ApplicationMessage:
    """Safe actionable UI error, never an interpolated provider exception."""

    code: str
    message: str


def error_message(error: Exception) -> ApplicationMessage:
    """Translate failures without leaking paths, credentials, source data or tracebacks."""
    if isinstance(error, RuntimeConfigurationError):
        return ApplicationMessage("CONFIGURATION", "The service configuration needs attention. Contact the administrator before retrying.")
    if isinstance(error, RetrievalError):
        return ApplicationMessage("RETRIEVAL", "Source retrieval failed. The recorded diagnostic identifies the failed operation; no missing source was treated as a zero value.")
    if isinstance(error, ParseError):
        return ApplicationMessage("EXTRACTION", "The source could not be extracted or verified. Supported evidence remains recorded.")
    if isinstance(error, IntegrityError):
        detail = str(error)
        for fragment, code, message in (
            ('v1.2 only', 'UNSUPPORTED_MODEL', 'This view supports model v1.2. Historical assessments remain available through their audit replay.'),
            ('missing persisted assessment', 'NOT_FOUND', 'Assessment not found. Refresh the list and select an existing assessment.'),
            ('persisted M6', 'MISSING_AGGREGATION', 'This assessment has no complete aggregation result. Complete the production M6 workflow before loading it.'),
            ('active M5 leaves', 'INCOMPLETE_VARIABLES', 'The persisted variable set is incomplete. Review the assessment pipeline run.'),
            ('validated fact', 'MISSING_FACT', 'A required validated fact is missing. Review the persisted M4 handoff.'),
            ('reporting year', 'MISSING_YEAR', 'The selected reporting year is missing. Review the assessment context.'),
            ('evidence', 'MISSING_PROVENANCE', 'Required evidence provenance is missing or inconsistent. Review the source handoff.'),
        ):
            if fragment in detail:
                return ApplicationMessage(code, message)
        return ApplicationMessage('INTEGRITY', 'Stored assessment lineage is incomplete or inconsistent. Review the pipeline audit; no replacement values were generated.')
    if isinstance(error, (PersistenceError, OSError)):
        return ApplicationMessage('DATABASE', 'Cannot access the configured database. Check the server configuration and apply the existing migrations before retrying.')
    if isinstance(error, ValueError):
        return ApplicationMessage('INVALID_INPUT', 'Check the company number, explicit reporting year, assessment date and server configuration.')
    return ApplicationMessage('SERVICE', 'The assessment service could not complete this operation. Review the processing run before retrying; partial ingestion may remain recorded.')


def display_value(value: object | None) -> str:
    """Render exact persisted scalar values; None never becomes numeric zero."""
    return 'Unavailable' if value is None else str(value)


def belief_row(belief: BeliefDistribution) -> dict[str, str]:
    """Use exact decimal strings so dataframe conversion cannot round stored beliefs."""
    return {'Low': str(belief.low_belief), 'High': str(belief.high_belief), 'Unknown': str(belief.unknown_belief)}


def variable_row(variable: VariableExplanation) -> dict[str, str]:
    """Prepare one UI row without arithmetic, thresholds or reliability calculation."""
    result = variable.leaf.result
    return {'Code': result.variable_code, 'Variable': variable.name, 'Domain': variable.domain,
            'Raw value': display_value(result.raw_value), 'Unit': result.unit,
            **belief_row(result.final_belief), 'Reliability': str(result.reliability_r),
            'Availability': result.availability_status.value,
            'Reason': ', '.join(reason.value for reason in variable.leaf.calculation.reasons) or 'No exclusion recorded'}


class AssessmentApplication:
    """Coordinate existing production services; loading never triggers computation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def choices(self) -> tuple[AssessmentChoice, ...]:
        """Read assessment/company/year context without silently selecting another year."""
        assessments = SqlAssessmentRepository(self.database)
        companies = SqlCompanyRepository(self.database)
        choices = []
        for assessment in assessments.list_assessments():
            company = companies.get_by_company_number(assessment.company_number)
            choices.append(AssessmentChoice(assessment=assessment,
                company_name=company.company_name if company else None,
                reporting_year=assessments.get_financial_reporting_year(assessment.assessment_id)))
        # Creation time is an audit field; IDs and assessment dates are not creation order.
        runs = {choice.assessment.processing_run_id: assessments.get_processing_run(choice.assessment.processing_run_id)
                for choice in choices}
        return tuple(sorted(choices, key=lambda choice: (
            runs[choice.assessment.processing_run_id].started_at if runs[choice.assessment.processing_run_id] else datetime.min.replace(tzinfo=UTC),
            choice.assessment.assessment_id), reverse=True))

    def load(self, assessment_id: str) -> AssessmentView:
        """Display only an already-persisted complete M7 tree, preserving all exact values."""
        explanation = ExplanationService(self.database).for_assessment(assessment_id)
        company = SqlCompanyRepository(self.database).get_by_company_number(explanation.assessment.company_number)
        return AssessmentView(company_name=company.company_name if company else None, explanation=explanation)

    def existing(self, *, number: str, reporting_year: int, assessment_date: date) -> AssessmentView | None:
        """Reuse an exact company/year/date v1.2 context; never silently move dates."""
        number = company_number(number)
        for choice in self.choices():
            assessment = choice.assessment
            if (assessment.company_number == number and choice.reporting_year == reporting_year
                    and assessment.assessment_date == assessment_date and assessment.risk_model_version == '1.2'):
                # Broken lineage propagates; it must not be hidden by a silent fresh run.
                return self.load(assessment.assessment_id)
        return None

    def create(self, *, number: str, assessment_date: date, reporting_year: int, run_id: str,
               calculated_at: datetime, m2: CompaniesHouseIngestion | None = None,
               m3: AccountsIngestion | None = None, reuse_runs: tuple[str, str] | None = None,
               max_documents: int = 5) -> AssessmentView:
        """Explicit write action: existing M2–M5 workflow, then M6 and a read-only M7 view.

        Pipeline failures propagate to the UI boundary; no synthetic success or
        blanket rollback of immutable source evidence is attempted.
        """
        if type(max_documents) is not int or not 1 <= max_documents <= 10:
            raise ValueError('max_documents must be between 1 and 10')
        report = run_company_assessment(self.database, number=number, assessment_date=assessment_date,
            reporting_year=reporting_year, run_id=run_id, calculated_at=calculated_at,
            m2=m2, m3=m3, reuse_runs=reuse_runs, max_documents=max_documents)
        AggregationService(self.database).calculate_and_persist(assessment_id=report.assessment_id, calculated_at=calculated_at)
        return self.load(report.assessment_id)
