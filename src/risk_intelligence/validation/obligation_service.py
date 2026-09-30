"""SQL-only obligation validation and immutable publication through M4 policy."""

from datetime import date

from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.records import insert_immutable
from risk_intelligence.persistence.validated_members import load_validated_members
from risk_intelligence.validation.governance_handoff import _facts_for_snapshot, _snapshot_from_row
from risk_intelligence.validation.obligations import ObligationKind, ValidatedObligation, validate_obligation


class ObligationValidationService:
    """Additive entry point anchored to explicit SQL snapshot and validated-set IDs."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def evaluate_and_persist(
        self, *, validated_id: str, kind: ObligationKind, profile_snapshot_id: str,
        validated_filing_set_id: str, assessment_date: date,
    ) -> ValidatedObligation:
        """Read exact source lineage, validate once, then append an immutable result."""
        with self.database.transaction():
            rows = self.database.query("SELECT * FROM resource_snapshot WHERE snapshot_id=?", (profile_snapshot_id,))
            if len(rows) != 1:
                raise IntegrityError("Profile snapshot is missing")
            profile = _snapshot_from_row(rows[0])
            filings = load_validated_members(self.database, validated_filing_set_id)
            if profile.company_id != filings.validated.company_id or profile.resource.value != "profile":
                raise IntegrityError("Obligation snapshot identity/resource mismatch")
            result = validate_obligation(
                validated_id=validated_id, kind=kind, profile=profile,
                profile_facts=_facts_for_snapshot(self.database, profile), filings=filings,
                assessment_date=assessment_date,
            )
            row = {name: getattr(result, name) for name in (
                "validated_obligation_id", "company_id", "company_number", "processing_run_id",
                "obligation_kind", "profile_snapshot_id", "validated_filing_set_id",
            )}
            row.update(assessment_date=assessment_date.isoformat(), record_json=result.model_dump_json())
            inserted = insert_immutable(self.database, "validated_obligation", "validated_obligation_id", row)
            if inserted:
                for fact_id in result.fact_ids:
                    self.database.execute("INSERT INTO validated_obligation_fact VALUES (?, ?)", (validated_id, fact_id))
            else:
                self.get(validated_id)  # Verify complete existing lineage on retry.
            return result

    def get(self, validated_id: str) -> ValidatedObligation | None:
        """Restore the persisted result, not a fresh view of the profile or filings."""
        rows = self.database.query("SELECT * FROM validated_obligation WHERE validated_obligation_id=?", (validated_id,))
        if not rows:
            return None
        row = rows[0]
        result = ValidatedObligation.model_validate_json(str(row["record_json"]))
        for name in ("validated_obligation_id", "company_id", "company_number", "processing_run_id",
                     "obligation_kind", "profile_snapshot_id", "validated_filing_set_id"):
            if row[name] != getattr(result, name):
                raise IntegrityError("Obligation relational and typed identity differ")
        if row["assessment_date"] != result.assessment_date.isoformat():
            raise IntegrityError("Obligation assessment date differs")
        links = self.database.query("SELECT fact_id FROM validated_obligation_fact WHERE validated_obligation_id=? ORDER BY fact_id", (validated_id,))
        if tuple(item["fact_id"] for item in links) != result.fact_ids:
            raise IntegrityError("Obligation member lineage differs")
        return result
