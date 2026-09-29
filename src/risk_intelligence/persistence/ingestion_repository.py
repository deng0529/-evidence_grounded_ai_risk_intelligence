"""Relational M2 coverage/reuse and response metadata; never object/network I/O."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.domain.evidence import EvidenceReference
from risk_intelligence.domain.facts import StructuredFact
from risk_intelligence.ingestion.companies_house.policy import Resource
from .connection import Database, IntegrityError, Row
from .evidence_repositories import _reference_row
from .fact_repositories import _fact_row
from .mapping import encode, text, timestamp_value
from .records import insert_immutable

PARSER_VERSION = "ch-m2-v1"


@dataclass(frozen=True)
class Snapshot:
    """Explicit dataset completeness and scope, including links to reused evidence."""

    snapshot_id: str
    processing_run_id: str
    company_id: str
    resource: Resource
    checked_at: datetime
    coverage_start: date
    coverage_end: date
    complete: bool
    availability_status: AvailabilityStatus
    page_count: int
    item_count: int
    reused_snapshot_id: str | None = None
    error_code: str | None = None


class SqlIngestionRepository:
    """Persist operational ingestion metadata without storing raw responses in SQL."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_context(self, run_id: str, assessment_date: date, start: date) -> None:
        """Freeze run scope once, separate from any future risk assessment record."""
        with self.database.transaction():
            insert_immutable(self.database, "ingestion_run", "processing_run_id", {
                "processing_run_id": run_id, "assessment_date": encode(assessment_date),
                "horizon_start": encode(start), "parser_version": PARSER_VERSION})

    def save_page_facts(self, source_id: str, references: list[EvidenceReference],
                        facts: list[StructuredFact]) -> None:
        """Atomically publish a page using M1 scalar mappings and exact retry checks.

        JSON is a transient SQL parameter for bulk insertion, not a persisted
        record/blob format. This avoids thousands of remote round trips while
        retaining the same typed columns, foreign keys and immutable semantics.
        """
        reference_rows = [_reference_row(reference) for reference in references]
        fact_rows = [_fact_row(fact) for fact in facts]
        reference_ids = {reference.evidence_id for reference in references}
        if (len(reference_ids) != len(references) or len({fact.fact_id for fact in facts}) != len(facts)
                or any(reference.source_id != source_id or reference.document_id is not None for reference in references)
                or any(fact.source_id != source_id or fact.document_id is not None
                       or any(evidence_id not in reference_ids for evidence_id in fact.evidence_ids) for fact in facts)):
            raise IntegrityError("Page facts must have unique identities and matching API evidence")
        link_rows: list[Row] = [{"fact_id": fact.fact_id, "position": position, "evidence_id": evidence_id}
                               for fact in facts for position, evidence_id in enumerate(fact.evidence_ids)]
        with self.database.transaction():
            if not self.database.query("SELECT source_id FROM raw_evidence WHERE source_id=?", (source_id,)):
                raise IntegrityError("Page facts require published raw evidence")
            previous_refs = self.database.query("SELECT * FROM evidence_reference WHERE source_id=?", (source_id,))
            previous_facts = self.database.query("SELECT * FROM fact WHERE source_id=?", (source_id,))
            previous_links = self.database.query(
                "SELECT fe.* FROM fact_evidence fe JOIN fact f USING(fact_id) WHERE f.source_id=?", (source_id,))
            if previous_refs or previous_facts or previous_links:
                def canonical(rows: list[Row]) -> str:
                    return json.dumps(sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)), sort_keys=True)
                if (canonical(previous_refs) != canonical(reference_rows)
                        or canonical(previous_facts) != canonical(fact_rows)
                        or canonical(previous_links) != canonical(link_rows)):
                    raise IntegrityError("Conflicting immutable page observations")
                return
            for table, rows in (("evidence_reference", reference_rows), ("fact", fact_rows), ("fact_evidence", link_rows)):
                if not rows:
                    continue
                columns = tuple(rows[0])
                selections = ",".join(f"json_extract(value,'$.{column}')" for column in columns)
                self.database.execute(f"INSERT INTO {table} ({','.join(columns)}) SELECT {selections} FROM json_each(?)",
                                      (json.dumps(rows, separators=(",", ":")),))

    def save_snapshot(self, snapshot: Snapshot) -> None:
        """Append a terminal resource result; failed retrievals cannot claim completeness."""
        if snapshot.complete and (snapshot.availability_status != AvailabilityStatus.AVAILABLE or snapshot.error_code):
            raise IntegrityError("Complete snapshot must be structurally available")
        row = {key: encode(value) for key, value in vars(snapshot).items()}
        with self.database.transaction():
            if snapshot.reused_snapshot_id:
                previous = self.database.query("SELECT * FROM resource_snapshot WHERE snapshot_id=?",
                                               (snapshot.reused_snapshot_id,))
                if not previous or previous[0]["company_id"] != snapshot.company_id or previous[0]["resource"] != snapshot.resource:
                    raise IntegrityError("Reuse must reference the same company/resource")
            insert_immutable(self.database, "resource_snapshot", "snapshot_id", row)

    def reusable(self, company_id: str, resource: Resource, now: datetime, start: date,
                 end: date, max_age: timedelta) -> Snapshot | None:
        """Reuse only the latest attempt if complete, in scope and fresh; never mask failure."""
        rows = self.database.query(
            "SELECT s.* FROM resource_snapshot s JOIN ingestion_run i USING(processing_run_id) "
            "WHERE s.company_id=? AND s.resource=? AND i.parser_version=? "
            "ORDER BY s.checked_at DESC, s.rowid DESC LIMIT 1", (company_id, resource.value, PARSER_VERSION))
        if not rows:
            return None
        row = rows[0]
        checked = timestamp_value(row["checked_at"])
        if (not row["complete"] or checked is None or not timedelta(0) <= now - checked < max_age
                or text(row["coverage_start"]) > start.isoformat() or text(row["coverage_end"]) < end.isoformat()):
            return None
        return Snapshot(text(row["snapshot_id"]), text(row["processing_run_id"]), company_id, resource, checked,
                        date.fromisoformat(text(row["coverage_start"])), date.fromisoformat(text(row["coverage_end"])),
                        True, AvailabilityStatus.AVAILABLE, int(row["page_count"]), int(row["item_count"]),
                        row["reused_snapshot_id"], row["error_code"])

    def save_response(self, source_id: str, resource: Resource, path: str, content_type: str,
                      etag: str | None, index: int, page_size: int) -> None:
        """Attach allowlisted HTTP metadata to an already published raw response."""
        with self.database.transaction():
            insert_immutable(self.database, "api_response", "source_id", {
                "source_id": source_id, "resource": resource.value, "request_path": path,
                "content_type": content_type, "etag": etag, "start_index": index,
                "requested_page_size": page_size})

    def save_search(self, search_id: str, path: str, retrieved_at: datetime, object_path: str,
                    checksum: str, content_type: str, etag: str | None) -> None:
        """Low-level metadata; search coordinator must verify object bytes first."""
        with self.database.transaction():
            insert_immutable(self.database, "company_search_evidence", "search_id", {
                "search_id": search_id, "request_path": path, "retrieved_at": encode(retrieved_at),
                "http_status": 200, "object_path": object_path, "checksum": checksum,
                "content_type": content_type, "etag": etag})
