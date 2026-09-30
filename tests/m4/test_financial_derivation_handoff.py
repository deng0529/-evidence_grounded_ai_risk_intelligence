"""M4.2b migration protects the SQL-only derivation-proof handoff."""

from risk_intelligence.persistence.connection import open_sqlite
from risk_intelligence.persistence.migrations import migrate


def test_derivation_proof_handoff_schema_is_present() -> None:
    with open_sqlite() as database:
        migrate(database)
        tables = {row["name"] for row in database.query(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "financial_derivation_proof" in tables
        assert "financial_derivation_cross_check" in tables


def test_derivation_proof_tables_are_immutable() -> None:
    with open_sqlite() as database:
        migrate(database)
        triggers = {row["name"] for row in database.query(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        assert "financial_derivation_proof_no_update" in triggers
        assert "financial_derivation_proof_no_delete" in triggers
        assert "financial_derivation_cross_check_no_update" in triggers
        assert "financial_derivation_cross_check_no_delete" in triggers
