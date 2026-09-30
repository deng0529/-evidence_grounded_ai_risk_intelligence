"""Immutable persistence for final M4 validated analytical evidence."""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from risk_intelligence.domain.enums import (
    AvailabilityStatus,
    ComparabilityStatus,
    PeriodType,
    ValidationStatus,
)
from risk_intelligence.domain.reliability import ConflictState, ReliabilityAssessment
from risk_intelligence.domain.validation import ValidationReport
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.records import insert_immutable


@dataclass(frozen=True)
class PersistedValidatedFact:
    validated_fact_id: str
    fact_id: str
    company_id: str
    company_number: str
    processing_run_id: str
    assessment_date: date
    canonical_concept: str
    value_numeric: Decimal | None
    currency: str | None
    unit: str | None
    period_type: PeriodType | None
    period_start: date | None
    period_end: date | None
    period_length_days: int | None
    comparability_status: ComparabilityStatus | None
    source_id: str
    document_id: str | None
    evidence_ids: tuple[str, ...]
    availability_status: AvailabilityStatus
    provenance_type: str
    normalization_method: str | None
    derivation_method: str | None
    transformation_chain: tuple[str, ...]
    critical_transformation: str
    validation_report: ValidationReport
    conflict_state: ConflictState
    source_quality_s: Decimal
    extraction_quality_e: Decimal
    validation_factor_v: Decimal
    conflict_factor_c: Decimal
    reliability_r: Decimal
    validation_status: ValidationStatus
    validation_ruleset_version: str
    reliability_policy_version: str


@dataclass(frozen=True)
class PersistedValidatedEvidenceSet:
    validated_evidence_set_id: str
    company_id: str
    company_number: str
    processing_run_id: str
    assessment_date: date
    evidence_set_type: str
    analytical_window_start: date
    analytical_window_end: date
    source_resources: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    availability_status: AvailabilityStatus
    validation_report: ValidationReport
    conflict_state: ConflictState
    source_quality_s: Decimal
    extraction_quality_e: Decimal
    validation_factor_v: Decimal
    conflict_factor_c: Decimal
    reliability_r: Decimal
    validation_status: ValidationStatus
    validation_ruleset_version: str
    reliability_policy_version: str


def _json_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), separators=(",", ":"), ensure_ascii=False)


def _status(assessment: ReliabilityAssessment) -> ValidationStatus:
    if assessment.validation.failures:
        return ValidationStatus.FAIL
    if any(
        item.result == ValidationStatus.INCONCLUSIVE
        for item in assessment.validation.outcomes
    ):
        return ValidationStatus.INCONCLUSIVE
    return ValidationStatus.PASS


def _common(assessment: ReliabilityAssessment) -> dict[str, object]:
    calculation = assessment.calculation
    return {
        "validation_report_json": assessment.validation.model_dump_json(),
        "conflict_state_json": assessment.conflict.model_dump_json(),
        "source_quality_s": str(calculation.components.s),
        "extraction_quality_e": str(calculation.components.e),
        "validation_factor_v": str(calculation.components.v),
        "conflict_factor_c": str(calculation.components.c),
        "reliability_r": str(calculation.reliability_r),
        "validation_status": _status(assessment).value,
        "validation_ruleset_version": assessment.validation.ruleset_version,
        "reliability_policy_version": calculation.policy_version,
    }


class ValidatedEvidenceRepository:
    """Persist and restore immutable M4 outputs without recomputing them."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_fact(
        self,
        *,
        validated_fact_id: str,
        fact_id: str,
        company_id: str,
        company_number: str,
        processing_run_id: str,
        assessment_date: date,
        canonical_concept: str,
        availability_status: AvailabilityStatus,
        provenance_type: str,
        normalization_method: str | None,
        derivation_method: str | None,
        assessment: ReliabilityAssessment,
    ) -> None:
        if provenance_type not in ("DIRECT", "DERIVED"):
            raise ValueError("Unsupported validated fact provenance type")

        with self.database.transaction():
            fact = self.database.query(
                """
                SELECT company_id, company_number, processing_run_id,
                       canonical_concept, availability_status,
                       value_numeric, currency, unit,
                       period_type, period_start, period_end,
                       period_length_days, comparability_status,
                       source_id, document_id
                FROM fact WHERE fact_id=?
                """,
                (fact_id,),
            )

            if len(fact) != 1:
                raise IntegrityError(
                    "Validated fact references missing source fact"
                )

            source = fact[0]

            if (
                source["company_id"] != company_id
                or source["company_number"] != company_number
                or source["processing_run_id"] != processing_run_id
                or source["canonical_concept"] != canonical_concept
                or source["availability_status"] != availability_status.value
            ):
                raise IntegrityError(
                    "Validated fact metadata contradicts source fact"
                )

            evidence = self.database.query(
                """
                SELECT evidence_id
                FROM fact_evidence
                WHERE fact_id=?
                ORDER BY position
                """,
                (fact_id,),
            )
            evidence_ids = tuple(
                str(item["evidence_id"]) for item in evidence
            )

            row = {
                "validated_fact_id": validated_fact_id,
                "fact_id": fact_id,
                "company_id": company_id,
                "company_number": company_number,
                "processing_run_id": processing_run_id,
                "assessment_date": assessment_date.isoformat(),
                "canonical_concept": canonical_concept,
                "value_numeric": source["value_numeric"],
                "currency": source["currency"],
                "unit": source["unit"],
                "period_type": source["period_type"],
                "period_start": source["period_start"],
                "period_end": source["period_end"],
                "period_length_days": source["period_length_days"],
                "comparability_status": source["comparability_status"],
                "source_id": source["source_id"],
                "document_id": source["document_id"],
                "evidence_ids_json": _json_tuple(evidence_ids),
                "availability_status": availability_status.value,
                "provenance_type": provenance_type,
                "normalization_method": normalization_method,
                "derivation_method": derivation_method,
                "transformation_chain_json": _json_tuple(
                    assessment.transformation_chain
                ),
                "critical_transformation":
                    assessment.critical_transformation.value,
                **_common(assessment),
            }

            insert_immutable(
                self.database,
                "validated_fact",
                "validated_fact_id",
                row,
            )

    def get_fact(
        self,
        validated_fact_id: str,
    ) -> PersistedValidatedFact | None:
        rows = self.database.query(
            "SELECT * FROM validated_fact WHERE validated_fact_id=?",
            (validated_fact_id,),
        )

        if not rows:
            return None

        row = rows[0]

        return PersistedValidatedFact(
            validated_fact_id=str(row["validated_fact_id"]),
            fact_id=str(row["fact_id"]),
            company_id=str(row["company_id"]),
            company_number=str(row["company_number"]),
            processing_run_id=str(row["processing_run_id"]),
            assessment_date=date.fromisoformat(str(row["assessment_date"])),
            canonical_concept=str(row["canonical_concept"]),
            value_numeric=(
                Decimal(str(row["value_numeric"]))
                if row["value_numeric"] is not None
                else None
            ),
            currency=(
                str(row["currency"])
                if row["currency"] is not None
                else None
            ),
            unit=(
                str(row["unit"])
                if row["unit"] is not None
                else None
            ),
            period_type=(
                PeriodType(str(row["period_type"]))
                if row["period_type"] is not None
                else None
            ),
            period_start=(
                date.fromisoformat(str(row["period_start"]))
                if row["period_start"] is not None
                else None
            ),
            period_end=(
                date.fromisoformat(str(row["period_end"]))
                if row["period_end"] is not None
                else None
            ),
            period_length_days=(
                int(row["period_length_days"])
                if row["period_length_days"] is not None
                else None
            ),
            comparability_status=(
                ComparabilityStatus(str(row["comparability_status"]))
                if row["comparability_status"] is not None
                else None
            ),
            source_id=str(row["source_id"]),
            document_id=(
                str(row["document_id"])
                if row["document_id"] is not None
                else None
            ),
            evidence_ids=tuple(
                json.loads(str(row["evidence_ids_json"]))
            ),
            availability_status=AvailabilityStatus(
                str(row["availability_status"])
            ),
            provenance_type=str(row["provenance_type"]),
            normalization_method=row["normalization_method"],
            derivation_method=row["derivation_method"],
            transformation_chain=tuple(
                json.loads(str(row["transformation_chain_json"]))
            ),
            critical_transformation=str(row["critical_transformation"]),
            validation_report=ValidationReport.model_validate_json(
                str(row["validation_report_json"])
            ),
            conflict_state=ConflictState.model_validate_json(
                str(row["conflict_state_json"])
            ),
            source_quality_s=Decimal(str(row["source_quality_s"])),
            extraction_quality_e=Decimal(
                str(row["extraction_quality_e"])
            ),
            validation_factor_v=Decimal(str(row["validation_factor_v"])),
            conflict_factor_c=Decimal(str(row["conflict_factor_c"])),
            reliability_r=Decimal(str(row["reliability_r"])),
            validation_status=ValidationStatus(
                str(row["validation_status"])
            ),
            validation_ruleset_version=str(
                row["validation_ruleset_version"]
            ),
            reliability_policy_version=str(
                row["reliability_policy_version"]
            ),
        )

    def save_evidence_set(
        self,
        *,
        validated_evidence_set_id: str,
        company_id: str,
        company_number: str,
        processing_run_id: str,
        assessment_date: date,
        evidence_set_type: str,
        analytical_window_start: date,
        analytical_window_end: date,
        source_resources: tuple[str, ...],
        snapshot_ids: tuple[str, ...],
        availability_status: AvailabilityStatus,
        assessment: ReliabilityAssessment,
    ) -> None:
        if not source_resources or not snapshot_ids:
            raise ValueError(
                "Validated evidence set requires resources and snapshots"
            )

        if len(set(source_resources)) != len(source_resources):
            raise ValueError("Duplicate source resource")

        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("Duplicate evidence-set snapshot")

        if analytical_window_start > analytical_window_end:
            raise ValueError("Invalid analytical window")

        row = {
            "validated_evidence_set_id": validated_evidence_set_id,
            "company_id": company_id,
            "company_number": company_number,
            "processing_run_id": processing_run_id,
            "assessment_date": assessment_date.isoformat(),
            "evidence_set_type": evidence_set_type,
            "analytical_window_start":
                analytical_window_start.isoformat(),
            "analytical_window_end":
                analytical_window_end.isoformat(),
            "source_resources_json": _json_tuple(source_resources),
            "availability_status": availability_status.value,
            **_common(assessment),
        }

        with self.database.transaction():
            placeholders = ",".join("?" for _ in snapshot_ids)

            snapshots = self.database.query(
                f"""
                SELECT snapshot_id, company_id, processing_run_id, resource
                FROM resource_snapshot
                WHERE snapshot_id IN ({placeholders})
                ORDER BY snapshot_id
                """,
                snapshot_ids,
            )

            if len(snapshots) != len(snapshot_ids):
                raise IntegrityError(
                    "Validated evidence set references missing snapshot"
                )

            by_id = {
                str(item["snapshot_id"]): item
                for item in snapshots
            }

            ordered_resources = tuple(
                str(by_id[snapshot_id]["resource"])
                for snapshot_id in snapshot_ids
            )

            if ordered_resources != source_resources:
                raise IntegrityError(
                    "Evidence-set resources do not match snapshot lineage"
                )

            if any(
                item["company_id"] != company_id
                or item["processing_run_id"] != processing_run_id
                for item in snapshots
            ):
                raise IntegrityError(
                    "Evidence-set snapshot identity contradicts M4 output"
                )

            inserted = insert_immutable(
                self.database,
                "validated_evidence_set",
                "validated_evidence_set_id",
                row,
            )

            if inserted:
                for position, snapshot_id in enumerate(snapshot_ids):
                    self.database.execute(
                        """
                        INSERT INTO validated_evidence_set_snapshot
                        VALUES (?, ?, ?)
                        """,
                        (
                            validated_evidence_set_id,
                            position,
                            snapshot_id,
                        ),
                    )
            else:
                existing = self.database.query(
                    """
                    SELECT position, snapshot_id
                    FROM validated_evidence_set_snapshot
                    WHERE validated_evidence_set_id=?
                    ORDER BY position
                    """,
                    (validated_evidence_set_id,),
                )

                expected = [
                    {
                        "position": position,
                        "snapshot_id": snapshot_id,
                    }
                    for position, snapshot_id in enumerate(snapshot_ids)
                ]

                if existing != expected:
                    raise IntegrityError(
                        "Immutable evidence-set snapshot lineage differs"
                    )

    def get_evidence_set(
        self,
        validated_evidence_set_id: str,
    ) -> PersistedValidatedEvidenceSet | None:
        rows = self.database.query(
            """
            SELECT *
            FROM validated_evidence_set
            WHERE validated_evidence_set_id=?
            """,
            (validated_evidence_set_id,),
        )

        if not rows:
            return None

        row = rows[0]

        links = self.database.query(
            """
            SELECT position, snapshot_id
            FROM validated_evidence_set_snapshot
            WHERE validated_evidence_set_id=?
            ORDER BY position
            """,
            (validated_evidence_set_id,),
        )

        if [item["position"] for item in links] != list(range(len(links))):
            raise IntegrityError(
                "Stored evidence-set snapshot ordering contains gaps"
            )

        return PersistedValidatedEvidenceSet(
            validated_evidence_set_id=str(
                row["validated_evidence_set_id"]
            ),
            company_id=str(row["company_id"]),
            company_number=str(row["company_number"]),
            processing_run_id=str(row["processing_run_id"]),
            assessment_date=date.fromisoformat(str(row["assessment_date"])),
            evidence_set_type=str(row["evidence_set_type"]),
            analytical_window_start=date.fromisoformat(
                str(row["analytical_window_start"])
            ),
            analytical_window_end=date.fromisoformat(
                str(row["analytical_window_end"])
            ),
            source_resources=tuple(
                json.loads(str(row["source_resources_json"]))
            ),
            snapshot_ids=tuple(
                str(item["snapshot_id"]) for item in links
            ),
            availability_status=AvailabilityStatus(
                str(row["availability_status"])
            ),
            validation_report=ValidationReport.model_validate_json(
                str(row["validation_report_json"])
            ),
            conflict_state=ConflictState.model_validate_json(
                str(row["conflict_state_json"])
            ),
            source_quality_s=Decimal(str(row["source_quality_s"])),
            extraction_quality_e=Decimal(
                str(row["extraction_quality_e"])
            ),
            validation_factor_v=Decimal(str(row["validation_factor_v"])),
            conflict_factor_c=Decimal(str(row["conflict_factor_c"])),
            reliability_r=Decimal(str(row["reliability_r"])),
            validation_status=ValidationStatus(
                str(row["validation_status"])
            ),
            validation_ruleset_version=str(
                row["validation_ruleset_version"]
            ),
            reliability_policy_version=str(
                row["reliability_policy_version"]
            ),
        )
