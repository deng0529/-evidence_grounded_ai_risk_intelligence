"""Small shared SQL mechanics for explicit record mappings, not an ORM."""

from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from risk_intelligence.domain.common import Contract
from .connection import Database, IntegrityError, Row

Record = TypeVar("Record", bound=Contract)


def restore(decoder: Callable[[Row], Record], row: Row) -> Record:
    """Translate invalid stored shapes without exposing source data in errors."""
    try:
        return decoder(row)
    except (ValidationError, ValueError, TypeError, KeyError):
        raise IntegrityError("Malformed stored domain record") from None


def insert_immutable(database: Database, table: str, key: str, row: Row) -> bool:
    """Insert explicit mapped columns, or accept an exactly identical retry.

    Table/column names come only from internal mappings, never external input.
    Returns true only for a new row. Caller owns the transaction.
    """
    existing = database.query(f"SELECT * FROM {table} WHERE {key}=?", (row[key],))
    if existing:
        if existing[0] != row:
            raise IntegrityError(f"Conflicting immutable {table} identity")
        return False
    columns = ", ".join(row)
    parameters = ", ".join("?" for _ in row)
    database.execute(f"INSERT INTO {table} ({columns}) VALUES ({parameters})", tuple(row.values()))
    return True


class SqlRecordRepository[Record: Contract]:
    """Typed get/save mechanics configured by explicit per-record mappings.

    This private infrastructure receives only trusted table names and codecs.
    Concrete public repositories provide their own types and provenance checks.
    """

    def __init__(self, database: Database, table: str, key: str,
                 encoder: Callable[[Record], Row], decoder: Callable[[Row], Record]) -> None:
        self.database = database
        self._table = table
        self._key = key
        self._encoder = encoder
        self._decoder = decoder

    def get(self, record_id: str) -> Record | None:
        """Restore a validated record, return None if absent, or fail on corruption."""
        rows = self.database.query(f"SELECT * FROM {self._table} WHERE {self._key}=?", (record_id,))
        return restore(self._decoder, rows[0]) if rows else None

    def save(self, record_id: str, record: Record) -> None:
        """Save an immutable record after ID agreement and provenance checks."""
        row = self._encoder(record)
        # Revalidate at the boundary even if a caller used unchecked model construction.
        restore(self._decoder, row)
        if row[self._key] != record_id:
            raise IntegrityError("Explicit repository ID differs from record ID")
        with self.database.transaction():
            self._check(record)
            insert_immutable(self.database, self._table, self._key, row)

    def _check(self, record: Record) -> None:
        """Concrete repositories add cross-record checks; SQL always enforces FKs."""
