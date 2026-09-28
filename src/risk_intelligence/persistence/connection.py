"""Explicit SQLite/libSQL connections and transaction ownership."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Protocol, Self

from risk_intelligence.config import Settings

SqlValue = str | int | bytes | None
Row = dict[str, SqlValue]


class PersistenceError(RuntimeError):
    """A relational operation failed; provider messages and secrets are suppressed."""


class IntegrityError(PersistenceError):
    """Stored content or a requested write violates identity/provenance integrity."""


class Cursor(Protocol):
    """DB-API cursor subset shared by SQLite and the pinned libSQL driver."""

    @property
    def description(self) -> Sequence[Sequence[object]] | None:
        """Column metadata for named result restoration."""
        ...

    def fetchall(self) -> Sequence[Sequence[SqlValue]]:
        """Read all rows from this small metadata query."""
        ...


class Connection(Protocol):
    """Small synchronous DB-API boundary; no replication or pooling."""

    def execute(self, sql: str, parameters: Sequence[SqlValue] = ()) -> Cursor:
        """Execute one parameterized statement."""
        ...

    def close(self) -> None:
        """Release the underlying connection."""
        ...


class Database:
    """One explicitly owned connection; use from one thread and close after use.

    Nested repository transactions join the outer transaction. Any failed nested
    operation marks it rollback-only, even if a caller catches the exception.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._depth = 0
        self._rollback_only = False
        self.execute("PRAGMA foreign_keys = ON")
        if self.query("PRAGMA foreign_keys") != [{"foreign_keys": 1}]:
            self.close()
            raise PersistenceError("Foreign-key enforcement is unavailable")

    def execute(self, sql: str, parameters: Sequence[SqlValue] = ()) -> None:
        """Execute SQL without exposing provider errors, SQL values or credentials."""
        self._execute(sql, parameters)

    def _execute(self, sql: str, parameters: Sequence[SqlValue]) -> Cursor:
        if any(value is not None and type(value) not in (str, int, bytes) for value in parameters):
            raise IntegrityError("SQL parameters must use explicit exact scalar mappings")
        try:
            return self._connection.execute(sql, parameters)
        except Exception:
            # Driver exceptions may embed connection URLs, tokens or parameters.
            # This is an error translation boundary, never catch-and-ignore.
            if self._depth:
                self._rollback_only = True
            raise PersistenceError("Database statement failed; transaction or constraint was rejected") from None

    def query(self, sql: str, parameters: Sequence[SqlValue] = ()) -> list[Row]:
        """Return named scalar rows; callers must validate domain types explicitly."""
        cursor = self._execute(sql, parameters)
        try:
            names = [str(column[0]) for column in (cursor.description or ())]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        except Exception:
            raise PersistenceError("Database result could not be read") from None

    @property
    def in_transaction(self) -> bool:
        """Whether this connection has an active managed transaction."""
        return self._depth > 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit all participating writes together, or roll back on any failure."""
        outer = self._depth == 0
        if outer:
            self.execute("BEGIN IMMEDIATE")
            self._rollback_only = False
        self._depth += 1
        try:
            yield
            if outer:
                if self._rollback_only:
                    raise PersistenceError("Transaction contains a failed operation")
                self.execute("COMMIT")
        except BaseException:
            self._rollback_only = True
            if outer:
                self.execute("ROLLBACK")
            raise
        finally:
            self._depth -= 1

    def close(self) -> None:
        """Close the database explicitly, without starting any new work."""
        try:
            self._connection.close()
        except Exception:
            raise PersistenceError("Database close failed") from None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_sqlite(path: str | Path = ":memory:") -> Database:
    """Open local SQLite with explicit transactions; never create parent folders."""
    return Database(sqlite3.connect(str(path), isolation_level=None))


def open_database(settings: Settings) -> Database:
    """Open the selected backend only when called; no silent cloud fallback."""
    if settings.database_backend == "sqlite":
        settings.local_data_directory.mkdir(parents=True, exist_ok=True)
        return open_sqlite(settings.local_data_directory / "metadata.sqlite3")
    import libsql

    if settings.turso_database_url is None or settings.turso_auth_token is None:
        raise PersistenceError("Turso configuration is incomplete")
    try:
        connection = libsql.connect(
            settings.turso_database_url.get_secret_value(),
            auth_token=settings.turso_auth_token.get_secret_value(),
            isolation_level=None,
        )
    except Exception:
        raise PersistenceError("Turso connection failed") from None
    return Database(connection)
