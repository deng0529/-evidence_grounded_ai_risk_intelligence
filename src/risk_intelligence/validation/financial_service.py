"""SQL-backed orchestration for M4 financial validation.

This service composes the frozen M4 financial rules and reliability policy.
It performs no M5 risk-variable, belief or ER calculation.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from risk_intelligence.domain.enums import (
    CriticalTransformation,
    ExtractionMethod,
    SourceType,
)
from risk_intelligence.domain.facts import FinancialFact
from risk_intelligence.domain.reliability import ReliabilityAssessment
from risk_intelligence.domain.validation import ValidationReport
from risk_intelligence.ingestion.accounts.mapping import default_registry
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.evidence_repositories import (
    SqlDocumentRepository,
    SqlEvidenceReferenceRepository,
    SqlSourceRepository,
)
from risk_intelligence.persistence.validated_repository import (
    ValidatedEvidenceRepository,
)
from risk_intelligence.validation.engine import ValidationEngine
from risk_intelligence.validation.financial import FinancialProvenance
from risk_intelligence.validation.financial_conflict import (
    classify_financial_conflict,
)
from risk_intelligence.validation.financial_derivation import (
    financial_derivation_registry,
    load_derivation_evidence,
)
from risk_intelligence.validation.financial_period import FinancialPeriodEvidence
from risk_intelligence.validation.financial_scope import FinancialScopeEvidence
from risk_intelligence.validation.financial_semantic import (
    FinancialSemanticEvidence,
    SemanticAdmission,
)
from risk_intelligence.validation.financial_units import (
    FinancialMonetaryEvidence,
    MonetarySource,
)
from risk_intelligence.validation.policy import (
    assess_reliability,
    transformation_quality,
)


AnalyticalScope = Literal["COMPANY", "GROUP"]


@dataclass(frozen=True)
class FinancialValidationResult:
    fact: FinancialFact
    assessment: ReliabilityAssessment


def _critical_for_method(
    method: ExtractionMethod,
) -> CriticalTransformation:
    mapping = {
        ExtractionMethod.API_DIRECT:
            CriticalTransformation.STRUCTURED_DETERMINISTIC,
        ExtractionMethod.IXBRL_DIRECT:
            CriticalTransformation.TAGGED_IXBRL_DETERMINISTIC,
        ExtractionMethod.PDF_NATIVE_DETERMINISTIC:
            CriticalTransformation.NATIVE_PDF_DETERMINISTIC,
        ExtractionMethod.PDF_OCR_DETERMINISTIC:
            CriticalTransformation.OCR_DETERMINISTIC,
        ExtractionMethod.LLM_NATIVE_TEXT:
            CriticalTransformation.GROUNDED_LLM_SEMANTIC,
        ExtractionMethod.LLM_OCR_TEXT:
            CriticalTransformation.GROUNDED_LLM_SEMANTIC,
    }
    try:
        return mapping[method]
    except KeyError:
        raise IntegrityError(
            f"No direct M4 transformation class for {method.value}"
        ) from None


class FinancialValidationService:
    """M3 SQL -> frozen M4 rules -> reliability -> immutable M4 handoff."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.accounts = AccountsRepository(database)
        self.sources = SqlSourceRepository(database)
        self.documents = SqlDocumentRepository(database)
        self.evidence = SqlEvidenceReferenceRepository(database)
        self.validated = ValidatedEvidenceRepository(database)

    def _fact(self, fact_id: str) -> FinancialFact:
        fact = self.accounts.canonical.get(fact_id)
        if fact is None:
            raise IntegrityError(
                "Financial validation requires a persisted canonical fact"
            )
        return fact

    def _provenance(self, fact: FinancialFact) -> FinancialProvenance:
        source = self.sources.get(fact.source_id)
        document = (
            self.documents.get(fact.document_id)
            if fact.document_id is not None
            else None
        )

        evidence = tuple(
            self.evidence.get(identity)
            for identity in fact.evidence_ids
        )

        if source is None or document is None:
            raise IntegrityError(
                "Financial source/document provenance is incomplete"
            )
        if any(item is None for item in evidence):
            raise IntegrityError(
                "Financial fact references missing evidence"
            )

        return FinancialProvenance(
            fact=fact,
            source=source,
            document=document,
            evidence=tuple(item for item in evidence if item is not None),
        )

    def _lineage(
        self,
        fact: FinancialFact,
    ) -> tuple[dict[str, object], tuple]:
        restored = self.accounts.get_observation_lineage(
            fact.financial_fact_id
        )
        if restored is None:
            raise IntegrityError(
                "Canonical financial observation has no persisted lineage"
            )
        return restored

    def _semantic(
        self,
        fact: FinancialFact,
        lineage: dict[str, object],
        components: tuple,
    ) -> FinancialSemanticEvidence:
        if not components:
            raise IntegrityError(
                "Financial semantic validation requires source lineage"
            )

        # A direct deterministic mapping has an explicit reviewed registry
        # version.  No concept is inferred here.
        registry = default_registry()
        mapping_version = str(lineage["mapping_version"])

        if mapping_version == registry.version:
            if len(components) != 1:
                raise IntegrityError(
                    "Direct deterministic normalization requires one source"
                )
            return FinancialSemanticEvidence(
                canonical_fact_id=fact.financial_fact_id,
                source=components[0],
                method="DETERMINISTIC_MAPPING",
                mapping_version=mapping_version,
            )

        # Otherwise only an explicitly persisted accepted interpretation may
        # establish semantic normalization.
        rows = self.database.query(
            """
            SELECT *
            FROM financial_interpretation
            WHERE canonical_fact_id=?
            ORDER BY interpretation_id
            """,
            (fact.financial_fact_id,),
        )

        accepted = [
            row for row in rows
            if row["status"] == "AVAILABLE"
        ]
        if len(accepted) != 1:
            return FinancialSemanticEvidence(
                canonical_fact_id=fact.financial_fact_id,
                source=components[0] if len(components) == 1 else None,
                mapping_version=mapping_version,
            )

        row = accepted[0]
        source = self.accounts.get_source(row["source_fact_id"])
        support = self.accounts.get_semantic_support(
            row["interpretation_id"]
        )

        admission = SemanticAdmission(
            interpretation_id=row["interpretation_id"],
            canonical_fact_id=row["canonical_fact_id"],
            source_fact_id=row["source_fact_id"],
            document_id=row["document_id"],
            target_concept=row["target_concept"],
            method=row["method"],
            status=row["status"],
            rule_version=row["rule_version"],
            artifact_raw_id=row["artifact_raw_id"],
            llm_artifact_raw_id=row["llm_artifact_raw_id"],
        )

        return FinancialSemanticEvidence(
            canonical_fact_id=fact.financial_fact_id,
            source=source,
            method=row["method"],
            mapping_version=row["rule_version"],
            admission=admission,
            support=support,
        )

    def _analytical_input(
        self,
        fact: FinancialFact,
        assessment_date: date,
        analytical_scope: AnalyticalScope,
    ):
        provenance = self._provenance(fact)
        lineage, components = self._lineage(fact)

        context = provenance.analytical_input(
            fact.company_number,
            assessment_date,
        )

        context = FinancialPeriodEvidence(
            source_facts=components,
        ).attach(context)

        context = FinancialScopeEvidence(
            analytical_scope=analytical_scope,
            source_facts=components,
        ).attach(context)

        context = FinancialMonetaryEvidence(
            sources=tuple(
                MonetarySource.from_source(source)
                for source in components
            ),
        ).attach(context)

        context = self._semantic(
            fact,
            lineage,
            components,
        ).attach(context)

        context = load_derivation_evidence(
            self.accounts,
            fact.financial_fact_id,
        ).attach(context)

        return context

    def _source_type(self, fact: FinancialFact) -> SourceType:
        source = self.sources.get(fact.source_id)
        if source is None:
            raise IntegrityError("Financial source is missing")
        return source.source_type

    def _critical_transformation(
        self,
        fact: FinancialFact,
    ) -> CriticalTransformation:
        if fact.extraction_method != ExtractionMethod.DERIVED:
            return _critical_for_method(fact.extraction_method)

        _, components = self._lineage(fact)
        if not components:
            raise IntegrityError(
                "Derived fact has no persisted source components"
            )

        transformations = tuple(
            _critical_for_method(component.extraction_method)
            for component in components
        )

        # A derivation cannot receive a better E than its weakest material
        # extraction stage.  The stages are not multiplied.
        return min(
            transformations,
            key=transformation_quality,
        )

    def evaluate(
        self,
        *,
        fact_id: str,
        assessment_date: date,
        analytical_scope: AnalyticalScope,
        competing_fact_ids: tuple[str, ...] = (),
    ) -> FinancialValidationResult:
        fact = self._fact(fact_id)

        context = self._analytical_input(
            fact,
            assessment_date,
            analytical_scope,
        )

        report = ValidationEngine(
            financial_derivation_registry()
        ).validate(context)

        competitors = tuple(
            self._fact(identity)
            for identity in competing_fact_ids
        )

        conflict = classify_financial_conflict(
            fact,
            competitors,
        )

        # Conflict evidence can legitimately include a competing observation
        # that was not construction evidence for the selected fact.  Extend
        # only the final reliability context; do not rerun admissibility with
        # those competing IDs as if they grounded the selected observation.
        extra_conflict_evidence = tuple(
            sorted(
                set(conflict.evidence_ids)
                - set(report.context.evidence_ids)
            )
        )
        if extra_conflict_evidence:
            expanded_context = report.context.model_copy(
                update={
                    "evidence_ids": tuple(
                        sorted(
                            set(report.context.evidence_ids)
                            | set(extra_conflict_evidence)
                        )
                    )
                }
            )
            report = ValidationReport(
                context=expanded_context,
                ruleset_version=report.ruleset_version,
                outcomes=report.outcomes,
                failures=report.failures,
            )

        transformation = self._critical_transformation(fact)

        assessment = assess_reliability(
            report,
            self._source_type(fact),
            transformation,
            conflict,
            transformation_chain=(
                fact.extraction_method.value,
                transformation.value,
            ),
        )

        return FinancialValidationResult(
            fact=fact,
            assessment=assessment,
        )

    def evaluate_and_persist(
        self,
        *,
        validated_fact_id: str,
        fact_id: str,
        assessment_date: date,
        analytical_scope: AnalyticalScope,
        competing_fact_ids: tuple[str, ...] = (),
    ) -> FinancialValidationResult:
        result = self.evaluate(
            fact_id=fact_id,
            assessment_date=assessment_date,
            analytical_scope=analytical_scope,
            competing_fact_ids=competing_fact_ids,
        )

        fact = result.fact
        lineage, _ = self._lineage(fact)

        self.validated.save_fact(
            validated_fact_id=validated_fact_id,
            fact_id=fact.financial_fact_id,
            company_id=fact.company_id,
            company_number=fact.company_number,
            processing_run_id=fact.processing_run_id,
            assessment_date=assessment_date,
            canonical_concept=fact.canonical_concept,
            analytical_scope=analytical_scope,
            availability_status=fact.availability_status,
            provenance_type=str(lineage["origin"]),
            normalization_method=str(lineage["mapping_version"]),
            derivation_method=(
                str(lineage["derivation_version"])
                if lineage["derivation_version"] is not None
                else None
            ),
            assessment=result.assessment,
        )

        return result
