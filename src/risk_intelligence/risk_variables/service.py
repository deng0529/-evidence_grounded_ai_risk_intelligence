"""SQL-only M5 orchestration, ending at the model-registry leaf handoff."""

from datetime import datetime
from typing import Literal

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.validated_members import load_validated_members
from risk_intelligence.persistence.validated_repository import ValidatedEvidenceRepository
from risk_intelligence.persistence.variable_repository import VariableRepository
from risk_intelligence.validation.obligation_service import ObligationValidationService
from .core import MODEL_DEFINITIONS, model_definitions, LeafAssessment, Reason, make_leaf, unavailable
from .financial import calculate_financial
from .governance import calculate_lateness, calculate_population, set_input


class RiskVariableService:
    """Use an explicit immutable assessment context and saved M4 records only."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def calculate_and_persist(self, *, assessment_id: str, scope: Literal["COMPANY", "GROUP"],
                              calculated_at: datetime, financial_validated_ids: tuple[str, ...] | None = None) -> tuple[LeafAssessment, ...]:
        """Atomically publish every active model leaf; failure cannot leave a partial handoff."""
        with self.database.transaction():
            context = SqlAssessmentRepository(self.database).get_assessment(assessment_id)
            if context is None or context.risk_model_version not in MODEL_DEFINITIONS or context.reliability_model_version != "m4-reliability-v1":
                raise IntegrityError("M5 requires an existing compatible assessment context")
            assessment_repository = SqlAssessmentRepository(self.database)
            reporting_year = (assessment_repository.get_financial_reporting_year(assessment_id)
                              if context.risk_model_version in ("1.1", "1.2") else None)
            evidence_reporting_year = (assessment_repository.get_financial_evidence_year(assessment_id)
                                       if context.risk_model_version in ("1.1", "1.2") else None)
            if context.risk_model_version in ("1.1", "1.2") and reporting_year is None:
                raise IntegrityError("MVP v1.1/v1.2 requires an explicit financial reporting year")
            # Historical assessments predate explicit evidence-year provenance; they
            # retain their original exact-year semantics. New runs always persist it.
            if evidence_reporting_year is None:
                evidence_reporting_year = reporting_year
            parameters = (context.company_id, context.assessment_date.isoformat())
            repository = ValidatedEvidenceRepository(self.database)
            if financial_validated_ids is not None:
                # An explicit source-run handoff must not mix historical validation versions.
                facts = tuple(repository.get_fact(identity) for identity in financial_validated_ids)
                if any(fact is None or fact.company_id != context.company_id
                       or fact.assessment_date > context.assessment_date for fact in facts):
                    raise IntegrityError("Selected financial validation handoff is missing or incompatible")
            else:
                facts = tuple(repository.get_fact(str(row["validated_fact_id"])) for row in self.database.query(
                    "SELECT validated_fact_id FROM validated_fact WHERE company_id=? AND assessment_date<=? ORDER BY validated_fact_id", parameters))
            sets = tuple(load_validated_members(self.database, str(row["validated_evidence_set_id"])) for row in self.database.query(
                "SELECT validated_evidence_set_id FROM validated_evidence_set WHERE company_id=? AND assessment_date=? ORDER BY validated_evidence_set_id", parameters))
            obligations = tuple(ObligationValidationService(self.database).get(str(row["validated_obligation_id"])) for row in self.database.query(
                "SELECT validated_obligation_id FROM validated_obligation WHERE company_id=? AND assessment_date=? ORDER BY validated_obligation_id", parameters))
            leaves = []
            for code in model_definitions(context.risk_model_version):
                if code.startswith("F"):
                    calculation = calculate_financial(code, facts, company_id=context.company_id,
                        company_number=context.company_number, scope=scope, assessment_date=context.assessment_date, reporting_year=evidence_reporting_year)
                elif code in ("G1.1", "G1.2"):
                    calculation = calculate_lateness("ACCOUNTS" if code == "G1.1" else "CONFIRMATION_STATEMENT",
                        obligations, company_id=context.company_id, company_number=context.company_number,
                        assessment_date=context.assessment_date)
                else:
                    population_type = "PSC_EVENTS_36M" if code == "G3.1" else "OFFICER_EVENTS_24M"
                    candidates = [item for item in sets if item.validated.evidence_set_type == population_type]
                    if len(candidates) != 1:
                        calculation = unavailable(Reason.AMBIGUOUS_SELECTION if candidates else Reason.MISSING_INPUT,
                            tuple(set_input(item) for item in candidates), availability=None
                            if candidates else AvailabilityStatus.NOT_DISCLOSED)
                    else:
                        calculation = calculate_population(code, candidates[0], assessment_date=context.assessment_date)
                leaf = make_leaf(code=code, calculation=calculation, assessment_id=assessment_id,
                    company_id=context.company_id, company_number=context.company_number,
                    assessment_date=context.assessment_date, scope=scope, calculated_at=calculated_at,
                    model_version=context.risk_model_version)
                VariableRepository(self.database).save(leaf)
                leaves.append(leaf)
            return tuple(leaves)
