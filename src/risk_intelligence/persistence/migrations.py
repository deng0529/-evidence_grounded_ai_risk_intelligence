"""Explicit numbered forward migrations with transactional, checksummed history."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
import re
import sqlite3

from .connection import Database, IntegrityError
from .mapping import encode

MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")


def _statements(script: str) -> list[str]:
    # complete_statement understands trigger bodies and quoted semicolons;
    # executescript would implicitly commit, breaking migration atomicity.
    statements: list[str] = []
    pending = ""
    for character in script:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            statements.append(pending.strip())
            pending = ""
    if pending.strip():
        raise IntegrityError("Migration ends with an incomplete SQL statement")
    return statements


def migrate(database: Database, directory: Path = MIGRATIONS_DIRECTORY,
            *, applied_at: datetime | None = None) -> None:
    """Apply ordered migrations explicitly; reject drift, gaps and future history.

    All pending migrations and their ledger entries share one transaction.
    The optional audit timestamp makes tests reproducible; it never names objects.
    """
    paths = sorted(directory.glob("*.sql"))
    versions: list[int] = []
    scripts: list[tuple[Path, str, str]] = []
    for path in paths:
        match = re.fullmatch(r"([0-9]{3})_[a-z0-9_]+\.sql", path.name)
        if match is None:
            raise IntegrityError("Invalid migration filename")
        versions.append(int(match[1]))
        # Git checkouts may use CRLF on Windows and LF on Linux. Hash logical
        # UTF-8 SQL with LF endings so that checkout policy is not schema drift.
        script = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        scripts.append((path, script, sha256(script.encode("utf-8")).hexdigest()))
    if not versions or versions != list(range(1, len(versions) + 1)):
        raise IntegrityError("Migration versions must be contiguous starting at 001")
    timestamp = encode(applied_at if applied_at is not None else datetime.now(UTC))
    with database.transaction():
        database.execute("""CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            checksum TEXT NOT NULL, applied_at TEXT NOT NULL
        ) STRICT""")
        history = database.query("SELECT * FROM schema_migration ORDER BY version")
        if [row["version"] for row in history] != list(range(1, len(history) + 1)):
            raise IntegrityError("Migration ledger has gaps")
        if len(history) > len(scripts):
            raise IntegrityError("Database schema is newer than this application")
        for version, (path, script, checksum) in zip(versions, scripts, strict=True):
            if version <= len(history):
                row = history[version - 1]
                if row["name"] != path.name or row["checksum"] != checksum:
                    raise IntegrityError("Applied migration checksum/name drift")
                continue
            for statement in _statements(script):
                database.execute(statement)
            database.execute(
                "INSERT INTO schema_migration VALUES (?, ?, ?, ?)",
                (version, path.name, checksum, timestamp),
            )


def main() -> None:
    """Apply migrations to the explicitly configured backend, then close it."""
    from risk_intelligence.config import load_settings
    from .connection import open_database

    with open_database(load_settings()) as database:
        migrate(database)


if __name__ == "__main__":
    main()
