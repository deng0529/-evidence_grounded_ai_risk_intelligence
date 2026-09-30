"""SQL-backed orchestration for M4 governance evidence-set validation.

M2 structured evidence is reconstructed from relational persistence, validated
by the frozen governance registry, assessed under the frozen M4 reliability
policy, and optionally persisted as an immutable ValidatedEvidenceSet.
"""

from dataclasses import dataclass
from datetime import date

from risk_intelligence.domain.enums import (
    ConflictLevel,
    ConflictResolution,
    CriticalTransformation,
    SourceType,
)
from risk_intelligence.domain.reliability import (
    ConflictState,
    ReliabilityAssessment,
)
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.validated_repository import (
    ValidatedEvidenceRepository,
)
from risk_intelligence.validation.engine import ValidationEngine
from risk_intelligence.validation.governance import (
    GovernanceEvidenceSet,
    governance_registry,
)
from risk_intelligence.validation.governance_handoff import (
    load_governance_evidence,
)
from risk_intelligence.validation.policy import assess_reliability


@dataclass(frozen=True)
class GovernanceValidationResult:
    evidence_set: GovernanceEvidenceSet
    assessment: ReliabilityAssessment


def _no_conflict() -> ConflictState:
    """M4 v1 has no competing governance-population resolution policy."""
    return ConflictState(
        level=ConflictLevel.NONE,
        resolution=ConflictResolution.NONE,
        reason="No competing governance population",
    )


class GovernanceValidationService:
    """M2 SQL -> governance rules -> reliability -> immutable M4 handoff."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.validated = ValidatedEvidenceRepository(database)

    def evaluate(
        self,
        *,
        processing_run_id: str,
        input_id: str,
        input_type: str,
        company_number: str,
        assessment_date: date,
        window_start: date,
        resources: tuple[Resource, ...],
    ) -> GovernanceValidationResult:
        records = load_governance_evidence(
            self.database,
            processing_run_id=processing_run_id,
            input_id=input_id,
            input_type=input_type,
            company_number=company_number,
            assessment_date=assessment_date,
            window_start=window_start,
            resources=resources,
        )

        report = ValidationEngine(
            governance_registry()
        ).validate(records.analytical_input())

        assessment = assess_reliability(
            report,
            SourceType.COMPANIES_HOUSE_API,
            CriticalTransformation.STRUCTURED_DETERMINISTIC,
            _no_conflict(),
            transformation_chain=(
                "Companies House API",
                "M2 deterministic parser",
            ),
        )

        return GovernanceValidationResult(
            evidence_set=records,
            assessment=assessment,
        )

    def evaluate_and_persist(
        self,
        *,
        validated_evidence_set_id: str,
        processing_run_id: str,
        input_id: str,
        input_type: str,
        company_number: str,
        assessment_date: date,
        window_start: date,
        resources: tuple[Resource, ...],
    ) -> GovernanceValidationResult:
        result = self.evaluate(
            processing_run_id=processing_run_id,
            input_id=input_id,
            input_type=input_type,
            company_number=company_number,
            assessment_date=assessment_date,
            window_start=window_start,
            resources=resources,
        )

        records = result.evidence_set

        if not records.snapshots:
            raise IntegrityError(
                "Validated governance evidence set has no snapshots"
            )

        company_ids = {
            snapshot.company_id
            for snapshot in records.snapshots
        }

        run_ids = {
            snapshot.processing_run_id
            for snapshot in records.snapshots
        }

        if len(company_ids) != 1 or run_ids != {processing_run_id}:
            raise IntegrityError(
                "Governance snapshot identity is inconsistent"
            )

        # Keep the ordering identical across resources and snapshot IDs.
        # ValidatedEvidenceRepository independently verifies this lineage.
        ordered = tuple(
            sorted(
                records.snapshots,
                key=lambda snapshot: snapshot.resource.value,
            )
        )

        self.validated.save_evidence_set(
            validated_evidence_set_id=validated_evidence_set_id,
            company_id=next(iter(company_ids)),
            company_number=company_number,
            processing_run_id=processing_run_id,
            assessment_date=assessment_date,
            evidence_set_type=input_type,
            analytical_window_start=window_start,
            analytical_window_end=assessment_date,
            source_resources=tuple(
                snapshot.resource.value
                for snapshot in ordered
            ),
            snapshot_ids=tuple(
                snapshot.snapshot_id
                for snapshot in ordered
            ),
            availability_status=(
                result.assessment.validation.context.availability_status
            ),
            assessment=result.assessment,
        )

        return result
