"""Read-only structured-data snapshot for an isolated, reproducible local assessment."""

from hashlib import sha256
from pathlib import Path
import re

from risk_intelligence.persistence.connection import Database, IntegrityError, open_sqlite
from risk_intelligence.persistence.migrations import MIGRATIONS_DIRECTORY, migrate
from risk_intelligence.domain.evidence import RawEvidence
from risk_intelligence.interfaces import EvidenceStorage
from risk_intelligence.persistence.evidence_repositories import SqlRawEvidenceRepository
from risk_intelligence.storage.objects import verify_checksum


def recover_company_evidence(database: Database, number: str, source: EvidenceStorage,
                             destination: EvidenceStorage) -> tuple[RawEvidence, ...]:
    """Copy checksum-verified company objects under their original immutable identities.

    Include processing artifacts so unchanged OCR/provider fingerprints can replay.
    No relational records or remote objects are written. Missing/corrupt objects
    fail explicitly; an incomplete bundle must not be advertised as recovered.
    """
    repository = SqlRawEvidenceRepository(database)
    records = []
    for row in database.query(
        "SELECT r.raw_evidence_id FROM raw_evidence r JOIN source s USING(source_id) "
        "WHERE s.company_number=? ORDER BY r.raw_evidence_id", (number,)
    ):
        evidence = repository.get(str(row["raw_evidence_id"]))
        if evidence is None:
            raise IntegrityError("Evidence inventory changed during recovery")
        content = source.read(evidence.object_path)
        verify_checksum(content, evidence.checksum)
        destination.put(evidence, content)
        verify_checksum(destination.read(evidence.object_path), evidence.checksum)
        records.append(evidence)
    if not records:
        raise IntegrityError("No persisted raw evidence for this company")
    return tuple(records)


def verify_company_bundle(database: Database, number: str, storage: EvidenceStorage) -> tuple[RawEvidence, ...]:
    """Verify every original/derived company object referenced by the local snapshot."""
    repository = SqlRawEvidenceRepository(database)
    records = []
    for row in database.query(
        "SELECT r.raw_evidence_id FROM raw_evidence r JOIN source s USING(source_id) "
        "WHERE s.company_number=? ORDER BY r.raw_evidence_id", (number,)
    ):
        evidence = repository.get(str(row["raw_evidence_id"]))
        if evidence is None:
            raise IntegrityError("Bundle evidence identity is missing")
        verify_checksum(storage.read(evidence.object_path), evidence.checksum)
        records.append(evidence)
    return tuple(records)


def snapshot_database(source: Database, destination: Path) -> dict[str, int]:
    """Copy exact SQL rows into a new local database, then apply existing migrations.

    The source is held in a read transaction and receives no DDL/DML. Raw object
    bytes and credentials are not copied. Refuse an existing destination rather
    than overwrite an assessment. Migration checksums establish schema provenance.
    """
    if destination.exists():
        raise FileExistsError("Snapshot destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    source.execute("BEGIN")
    try:
        history = source.query("SELECT * FROM schema_migration ORDER BY version")
        paths = sorted(MIGRATIONS_DIRECTORY.glob("*.sql"))
        if not history or len(history) > len(paths):
            raise IntegrityError("Unsupported source migration history")
        for version, row in enumerate(history, 1):
            path = paths[version - 1]
            checksum = sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            if row["version"] != version or row["name"] != path.name or row["checksum"] != checksum:
                raise IntegrityError("Source migration checksum/name drift")
        objects = source.query("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL "
                               "AND name NOT LIKE 'sqlite_%' ORDER BY type,name")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", str(item["name"])) for item in objects):
            raise IntegrityError("Unexpected source schema identifier")
        with open_sqlite(destination) as target:
            with target.transaction():
                target.execute("PRAGMA defer_foreign_keys = ON")
                tables = [item for item in objects if item["type"] == "table"]
                for item in tables:
                    target.execute(str(item["sql"]))
                for item in tables:
                    name = str(item["name"])
                    rows = source.query(f'SELECT * FROM "{name}"')
                    counts[name] = len(rows)
                    for row in rows:
                        columns = ','.join('"' + column.replace('"', '""') + '"' for column in row)
                        marks = ','.join('?' for _ in row)
                        target.execute(f'INSERT INTO "{name}" ({columns}) VALUES ({marks})', tuple(row.values()))
                for item in objects:
                    if item["type"] != "table":
                        target.execute(str(item["sql"]))
                if target.query("PRAGMA foreign_key_check"):
                    raise IntegrityError("Source snapshot has foreign-key violations")
            migrate(target)
            if target.query("PRAGMA integrity_check") != [{"integrity_check": "ok"}]:
                raise IntegrityError("Local snapshot integrity check failed")
    finally:
        source.execute("ROLLBACK")
    return counts
