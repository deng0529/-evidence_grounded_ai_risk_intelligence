"""Offline schema, ledger, transaction and driver-boundary checks."""

from datetime import UTC, datetime
from pathlib import Path

import libsql
import pytest

from risk_intelligence.persistence.connection import Database, IntegrityError, PersistenceError, open_sqlite
from risk_intelligence.persistence.migrations import MIGRATIONS_DIRECTORY, migrate


def _m1_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "m1-only"
    directory.mkdir(exist_ok=True)
    path = MIGRATIONS_DIRECTORY / "001_storage.sql"
    (directory / path.name).write_bytes(path.read_bytes())
    return directory

def test_schema_contains_only_m1_tables_and_foreign_keys(database: Database) -> None:
    tables = {row["name"] for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"company", "processing_run", "source", "document", "raw_evidence",
                      "evidence_reference", "fact", "fact_evidence", "assessment", "schema_migration"}
    assert database.query("PRAGMA foreign_keys") == [{"foreign_keys": 1}]
    with pytest.raises(PersistenceError):
        database.execute("INSERT INTO fact_evidence VALUES ('missing', 0, 'missing')")


def test_rerun_preserves_ledger_and_detects_checksum_drift(database: Database, tmp_path: Path) -> None:
    before = database.query("SELECT * FROM schema_migration")
    migrate(database, _m1_directory(tmp_path))
    assert database.query("SELECT * FROM schema_migration") == before
    migration = tmp_path / "001_storage.sql"
    migration.write_bytes((MIGRATIONS_DIRECTORY / migration.name).read_bytes() + b"\n")
    with pytest.raises(IntegrityError, match="drift"):
        migrate(database, tmp_path)
    assert database.query("SELECT * FROM schema_migration") == before


def test_numbered_order_and_all_pending_rollback(tmp_path: Path) -> None:
    (tmp_path / "002_second.sql").write_text("INSERT INTO example VALUES (2);", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("CREATE TABLE example (number INTEGER); INSERT INTO example VALUES (1);",
                                         encoding="utf-8")
    with open_sqlite() as database:
        migrate(database, tmp_path, applied_at=datetime(2026, 1, 1, tzinfo=UTC))
        assert database.query("SELECT number FROM example ORDER BY number") == [{"number": 1}, {"number": 2}]
        assert [r["version"] for r in database.query("SELECT * FROM schema_migration ORDER BY version")] == [1, 2]
    (tmp_path / "002_second.sql").write_text("CREATE TABLE temporary_success (id INTEGER); INVALID SQL;", encoding="utf-8")
    with open_sqlite() as database:
        with pytest.raises(PersistenceError):
            migrate(database, tmp_path)
        assert database.query("SELECT name FROM sqlite_master WHERE type='table'") == []


def test_future_schema_and_gaps_are_rejected(database: Database, tmp_path: Path) -> None:
    database.execute("INSERT INTO schema_migration VALUES (2, '002_future.sql', 'synthetic', '2026')")
    with pytest.raises(IntegrityError, match="newer"):
        migrate(database, _m1_directory(tmp_path))
    (tmp_path / "002_gap.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(IntegrityError, match="contiguous"):
        migrate(database, tmp_path)


def test_nested_failure_cannot_be_committed_after_catching(database: Database) -> None:
    with pytest.raises(PersistenceError, match="failed operation"):
        with database.transaction():
            database.execute("CREATE TABLE should_rollback (id INTEGER)")
            try:
                with database.transaction():
                    raise ValueError("synthetic failure")
            except ValueError:
                pass
    assert not database.query("SELECT name FROM sqlite_master WHERE name='should_rollback'")


def test_pinned_libsql_driver_supports_schema_and_transactions_offline(tmp_path: Path) -> None:
    # Real libSQL driver, in-memory only: verifies API and dialect without Turso.
    with Database(libsql.connect(":memory:", isolation_level=None)) as database:
        migrate(database, _m1_directory(tmp_path))
        assert database.query("PRAGMA foreign_keys") == [{"foreign_keys": 1}]
        assert database.query("SELECT version FROM schema_migration") == [{"version": 1}]
        with pytest.raises(PersistenceError):
            with database.transaction():
                database.execute("CREATE TABLE rolled_back (id INTEGER)")
                database.execute("INVALID SQL")
        assert not database.query("SELECT name FROM sqlite_master WHERE name='rolled_back'")


def test_migration_checksum_survives_windows_linux_line_endings(database: Database, tmp_path: Path) -> None:
    path = MIGRATIONS_DIRECTORY / "001_storage.sql"
    (tmp_path / path.name).write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    migrate(database, tmp_path)
    assert database.query("SELECT version FROM schema_migration") == [{"version": 1}]


def test_database_rejects_implicit_float_parameters(database: Database) -> None:
    with pytest.raises(IntegrityError, match="exact scalar"):
        database.execute("SELECT ?", (1.25,))
