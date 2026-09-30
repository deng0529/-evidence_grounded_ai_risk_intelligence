"""SQL-only M2 -> M4 governance evidence reconstruction."""

from datetime import date

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.domain.facts import StructuredFact
from risk_intelligence.ingestion.companies_house.policy import Resource
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.fact_repositories import SqlStructuredFactRepository
from risk_intelligence.persistence.ingestion_repository import Snapshot
from risk_intelligence.persistence.mapping import text, timestamp_value
from risk_intelligence.validation.governance import GovernanceEvidenceSet


def _snapshot_from_row(row) -> Snapshot:
    checked = timestamp_value(row["checked_at"])
    if checked is None:
        raise IntegrityError("Governance snapshot lacks checked_at")

    return Snapshot(
        snapshot_id=text(row["snapshot_id"]),
        processing_run_id=text(row["processing_run_id"]),
        company_id=text(row["company_id"]),
        resource=Resource(text(row["resource"])),
        checked_at=checked,
        coverage_start=date.fromisoformat(text(row["coverage_start"])),
        coverage_end=date.fromisoformat(text(row["coverage_end"])),
        complete=bool(row["complete"]),
        availability_status=AvailabilityStatus(
            text(row["availability_status"])
        ),
        page_count=int(row["page_count"]),
        item_count=int(row["item_count"]),
        reused_snapshot_id=row["reused_snapshot_id"],
        error_code=row["error_code"],
    )


def _origin_snapshot(database: Database, snapshot: Snapshot) -> Snapshot:
    """Follow immutable reuse lineage to the snapshot that owns source pages."""
    current = snapshot
    seen = {current.snapshot_id}

    while current.reused_snapshot_id is not None:
        if current.reused_snapshot_id in seen:
            raise IntegrityError("Governance snapshot reuse lineage contains a cycle")

        seen.add(current.reused_snapshot_id)

        rows = database.query(
            "SELECT * FROM resource_snapshot WHERE snapshot_id=?",
            (current.reused_snapshot_id,),
        )

        if len(rows) != 1:
            raise IntegrityError("Governance snapshot reuse origin is missing")

        parent = _snapshot_from_row(rows[0])

        if (
            parent.company_id != current.company_id
            or parent.resource != current.resource
        ):
            raise IntegrityError(
                "Governance snapshot reuse crosses company/resource identity"
            )

        current = parent

    return current


def _facts_for_snapshot(
    database: Database,
    snapshot: Snapshot,
) -> tuple[StructuredFact, ...]:
    """Restore typed structured facts from source pages belonging to snapshot origin."""
    origin = _origin_snapshot(database, snapshot)

    rows = database.query(
        """
        SELECT DISTINCT f.fact_id
        FROM fact f
        JOIN api_response a ON a.source_id=f.source_id
        JOIN source s ON s.source_id=f.source_id
        WHERE f.record_kind='STRUCTURED'
          AND f.company_id=?
          AND f.processing_run_id=?
          AND a.resource=?
          AND s.processing_run_id=?
        ORDER BY f.fact_id
        """,
        (
            origin.company_id,
            origin.processing_run_id,
            origin.resource.value,
            origin.processing_run_id,
        ),
    )

    repository = SqlStructuredFactRepository(database)
    restored = []

    for row in rows:
        record = repository.get(text(row["fact_id"]))

        if record is None:
            raise IntegrityError(
                "Governance fact disappeared during SQL reconstruction"
            )

        restored.append(record)

    return tuple(restored)


def load_governance_evidence(
    database: Database,
    *,
    processing_run_id: str,
    input_id: str,
    input_type: str,
    company_number: str,
    assessment_date: date,
    window_start: date,
    resources: tuple[Resource, ...],
) -> GovernanceEvidenceSet:
    """Reconstruct one M4 governance population from immutable M2 SQL only."""
    if not resources or len(set(resources)) != len(resources):
        raise ValueError("Governance handoff requires distinct resources")

    placeholders = ",".join("?" for _ in resources)

    rows = database.query(
        f"""
        SELECT *
        FROM resource_snapshot
        WHERE processing_run_id=?
          AND resource IN ({placeholders})
        ORDER BY resource
        """,
        (processing_run_id, *(resource.value for resource in resources)),
    )

    snapshots = tuple(_snapshot_from_row(row) for row in rows)

    if len(snapshots) != len(resources):
        raise IntegrityError(
            "Governance handoff is missing required resource snapshots"
        )

    if {snapshot.resource for snapshot in snapshots} != set(resources):
        raise IntegrityError(
            "Governance handoff restored unexpected resource snapshots"
        )

    company_ids = {snapshot.company_id for snapshot in snapshots}

    if len(company_ids) != 1:
        raise IntegrityError(
            "Governance handoff spans more than one company"
        )

    facts_by_id: dict[str, StructuredFact] = {}

    for snapshot in snapshots:
        for fact in _facts_for_snapshot(database, snapshot):
            previous = facts_by_id.get(fact.fact_id)

            if previous is not None and previous != fact:
                raise IntegrityError(
                    "Governance fact identity has conflicting SQL content"
                )

            facts_by_id[fact.fact_id] = fact

    facts = tuple(facts_by_id[key] for key in sorted(facts_by_id))

    if any(fact.company_number != company_number for fact in facts):
        raise IntegrityError(
            "Governance SQL facts do not match requested company number"
        )

    return GovernanceEvidenceSet(
        input_id=input_id,
        input_type=input_type,
        company_number=company_number,
        assessment_date=assessment_date,
        window_start=window_start,
        snapshots=snapshots,
        facts=facts,
    )
