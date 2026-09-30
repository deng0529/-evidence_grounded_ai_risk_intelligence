"""Read exact SQL members of persisted M4 governance populations, without validation."""

from dataclasses import dataclass

from risk_intelligence.domain.facts import StructuredFact
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.validated_repository import (
    PersistedValidatedEvidenceSet, ValidatedEvidenceRepository,
)
from risk_intelligence.validation.governance_handoff import _facts_for_snapshot, _snapshot_from_row


@dataclass(frozen=True)
class ValidatedMembers:
    """Original M4 result and its exact source observations; reliability is not rerun."""

    validated: PersistedValidatedEvidenceSet
    facts: tuple[StructuredFact, ...]


def load_validated_members(database: Database, validated_id: str) -> ValidatedMembers:
    """Follow the saved snapshot IDs, including immutable reuse origins, using SQL only."""
    record = ValidatedEvidenceRepository(database).get_evidence_set(validated_id)
    if record is None:
        raise IntegrityError("Validated evidence set is missing")
    facts: dict[str, StructuredFact] = {}
    for snapshot_id, resource in zip(record.snapshot_ids, record.source_resources, strict=True):
        rows = database.query("SELECT * FROM resource_snapshot WHERE snapshot_id=?", (snapshot_id,))
        if len(rows) != 1:
            raise IntegrityError("Validated snapshot lineage is missing")
        snapshot = _snapshot_from_row(rows[0])
        if (snapshot.company_id != record.company_id or snapshot.resource.value != resource
                or snapshot.processing_run_id != record.processing_run_id):
            raise IntegrityError("Validated snapshot lineage identity differs")
        for fact in _facts_for_snapshot(database, snapshot):
            if fact.company_id != record.company_id or fact.company_number != record.company_number:
                raise IntegrityError("Validated member company differs")
            if fact.fact_id in facts and facts[fact.fact_id] != fact:
                raise IntegrityError("Validated member identity has conflicting content")
            facts[fact.fact_id] = fact
    return ValidatedMembers(record, tuple(facts[key] for key in sorted(facts)))
