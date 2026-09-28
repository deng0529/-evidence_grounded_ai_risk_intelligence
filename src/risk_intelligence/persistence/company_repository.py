"""Canonical company identity and an explicitly mutable current profile."""

from risk_intelligence.domain.evidence import Company
from .connection import Database, IntegrityError, Row
from .mapping import codes_value, date_value, encode
from .records import insert_immutable, restore


def _row(company: Company) -> Row:
    company = Company.model_validate(company)
    return {
        "company_id": company.company_id, "company_number": company.company_number,
        "company_name": company.company_name, "company_status": company.company_status,
        "company_type": company.company_type, "incorporation_date": encode(company.incorporation_date),
        "registered_office": company.registered_office, "sic_codes_json": encode(company.sic_codes),
    }


def _company(row: Row) -> Company:
    return Company(
        company_id=row["company_id"], company_number=row["company_number"],
        company_name=row["company_name"], company_status=row["company_status"],
        company_type=row["company_type"], incorporation_date=date_value(row["incorporation_date"]),
        registered_office=row["registered_office"], sic_codes=codes_value(row["sic_codes_json"]),
    )


class SqlCompanyRepository:
    """Store company profiles without changing their canonical identity.

    Historical reasoning must use preserved evidence/facts, not this projection.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_by_company_number(self, company_number: str) -> Company | None:
        """Read an exact canonical company number without resolution or inference."""
        rows = self.database.query("SELECT * FROM company WHERE company_number=?", (company_number,))
        return restore(_company, rows[0]) if rows else None

    def save(self, company: Company) -> None:
        """Insert/update the current profile; refuse any identity reassignment."""
        row = _row(company)
        with self.database.transaction():
            existing = self.database.query("SELECT * FROM company WHERE company_id=?", (company.company_id,))
            if not existing:
                insert_immutable(self.database, "company", "company_id", row)
                return
            if existing[0]["company_number"] != company.company_number:
                raise IntegrityError("Company identity cannot be reassigned")
            columns = [key for key in row if key not in ("company_id", "company_number")]
            self.database.execute(
                "UPDATE company SET " + ", ".join(f"{key}=?" for key in columns) + " WHERE company_id=?",
                tuple(row[key] for key in columns) + (company.company_id,),
            )
