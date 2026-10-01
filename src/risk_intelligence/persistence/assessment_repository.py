"""Processing lifecycle and assessment metadata only, without assessment execution."""

from risk_intelligence.domain.enums import AssessmentStatus, ProcessingStatus, TriggerType
from risk_intelligence.domain.runs import Assessment, ProcessingRun
from .connection import Database, IntegrityError, Row
from .mapping import date_value, encode, text, timestamp_value
from .records import insert_immutable, restore


def _run_row(record: ProcessingRun) -> Row:
    record = ProcessingRun.model_validate(record)
    return {
        "processing_run_id": record.processing_run_id, "company_id": record.company_id,
        "company_number": record.company_number, "started_at": encode(record.started_at),
        "completed_at": encode(record.completed_at), "status": encode(record.status),
        "current_stage": record.current_stage, "trigger_type": encode(record.trigger_type),
        "app_version": record.app_version, "error_code": record.error_code, "error_message": record.error_message,
    }


def _run(row: Row) -> ProcessingRun:
    return ProcessingRun(**(row | {
        "started_at": timestamp_value(row["started_at"]), "completed_at": timestamp_value(row["completed_at"]),
        "status": ProcessingStatus(text(row["status"])), "trigger_type": TriggerType(text(row["trigger_type"])),
    }))


def _assessment_row(record: Assessment) -> Row:
    record = Assessment.model_validate(record)
    return {
        "assessment_id": record.assessment_id, "company_id": record.company_id,
        "company_number": record.company_number, "processing_run_id": record.processing_run_id,
        "assessment_date": encode(record.assessment_date), "data_current_to": encode(record.data_current_to),
        "status": encode(record.status), "risk_model_version": record.risk_model_version,
        "reliability_model_version": record.reliability_model_version, "er_model_version": record.er_model_version,
        "data_dictionary_version": record.data_dictionary_version,
    }


def _assessment(row: Row) -> Assessment:
    return Assessment(**(row | {
        "assessment_date": date_value(row["assessment_date"]), "data_current_to": date_value(row["data_current_to"]),
        "status": AssessmentStatus(text(row["status"])),
    }))


class SqlAssessmentRepository:
    """Store supplied assessment snapshots and explicitly mutable active run status."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        """Return a supplied snapshot, never calculating an assessment."""
        rows = self.database.query("SELECT * FROM assessment WHERE assessment_id=?", (assessment_id,))
        return restore(_assessment, rows[0]) if rows else None

    def list_assessments(self) -> tuple[Assessment, ...]:
        """List persisted contexts deterministically for explicit UI selection."""
        rows = self.database.query(
            "SELECT * FROM assessment ORDER BY company_number, assessment_date DESC, assessment_id")
        return tuple(restore(_assessment, row) for row in rows)

    def save_assessment(self, assessment: Assessment) -> None:
        """Save an immutable supplied assessment; identical retries are accepted."""
        with self.database.transaction():
            insert_immutable(self.database, "assessment", "assessment_id", _assessment_row(assessment))

    def save_financial_reporting_year(self, assessment_id: str, reporting_year: int) -> None:
        """Persist the explicitly selected financial reporting year for MVP v1.1."""
        if not 1900 <= reporting_year <= 9999:
            raise ValueError("reporting_year must be a four-digit year")
        with self.database.transaction():
            insert_immutable(self.database, "assessment_financial_context", "assessment_id",
                             {"assessment_id": assessment_id, "reporting_year": reporting_year})

    def get_financial_reporting_year(self, assessment_id: str) -> int | None:
        """Return the selected reporting year; never infer it from assessment_date."""
        rows = self.database.query("SELECT reporting_year FROM assessment_financial_context WHERE assessment_id=?",
                                   (assessment_id,))
        return int(rows[0]["reporting_year"]) if rows else None

    def get_processing_run(self, processing_run_id: str) -> ProcessingRun | None:
        """Return persisted run metadata for inspection, without running a workflow."""
        rows = self.database.query("SELECT * FROM processing_run WHERE processing_run_id=?", (processing_run_id,))
        return restore(_run, rows[0]) if rows else None

    def save_processing_run(self, run: ProcessingRun) -> None:
        """Update lifecycle fields only while active; retain identity and start context."""
        row = _run_row(run)
        with self.database.transaction():
            existing = self.database.query("SELECT * FROM processing_run WHERE processing_run_id=?",
                                           (run.processing_run_id,))
            if not existing:
                insert_immutable(self.database, "processing_run", "processing_run_id", row)
                return
            previous = existing[0]
            if previous == row:
                return
            lifecycle = ("completed_at", "status", "current_stage", "error_code", "error_message")
            if previous["status"] not in ("PENDING", "RUNNING") or previous["completed_at"] is not None:
                raise IntegrityError("Finalized processing run is immutable")
            if any(previous[key] != value for key, value in row.items() if key not in lifecycle):
                raise IntegrityError("Processing run identity/start/version cannot change")
            if previous["status"] == "RUNNING" and row["status"] == "PENDING":
                raise IntegrityError("Processing run cannot return to pending")
            self.database.execute(
                "UPDATE processing_run SET " + ", ".join(f"{key}=?" for key in lifecycle)
                + " WHERE processing_run_id=?",
                tuple(row[key] for key in lifecycle) + (run.processing_run_id,),
            )
