"""Two typed repository views over a single exact, provenance-linked fact table."""

from typing import Literal

from risk_intelligence.domain.enums import (
    AvailabilityStatus, ComparabilityStatus, ExtractionMethod, FactType, PeriodType,
)
from risk_intelligence.domain.facts import (
    BooleanValue, CodesValue, DateValue, FactValue, FinancialFact, NumericValue,
    ReportingPeriod, StructuredFact, TextValue,
)
from .connection import Database, IntegrityError, Row
from .mapping import boolean_value, codes_value, date_value, decimal_value, encode, text
from .records import insert_immutable, restore

VALUE_COLUMNS = {
    FactType.NUMERIC: "numeric", FactType.DATE: "date", FactType.TEXT: "text",
    FactType.BOOLEAN: "boolean", FactType.CODES: "codes_json",
}


def _value(row: Row, prefix: str) -> FactValue:
    kind = FactType(text(row["fact_type"]))
    raw = row[f"{prefix}_{VALUE_COLUMNS[kind]}"]
    if kind == FactType.NUMERIC:
        return NumericValue(value=decimal_value(raw))
    if kind == FactType.DATE:
        return DateValue(value=date_value(raw))
    if kind == FactType.BOOLEAN:
        return BooleanValue(value=boolean_value(raw))
    if kind == FactType.CODES:
        return CodesValue(value=codes_value(raw))
    return TextValue(value=raw)


def _fact_row(record: StructuredFact | FinancialFact) -> Row:
    financial = isinstance(record, FinancialFact)
    if isinstance(record, FinancialFact):
        record = FinancialFact.model_validate(record)
        value = NumericValue(value=record.value_numeric)
        candidate = None
        if record.candidate_value_numeric is not None:
            candidate = NumericValue(value=record.candidate_value_numeric)
    else:
        record = StructuredFact.model_validate(record)
        value = record.value
        candidate = record.candidate_value
    row: Row = {
        "fact_id": record.financial_fact_id if financial else record.fact_id,
        "record_kind": "FINANCIAL" if financial else "STRUCTURED",
        "company_id": record.company_id, "company_number": record.company_number,
        "canonical_concept": record.canonical_concept, "source_id": record.source_id,
        "document_id": record.document_id, "processing_run_id": record.processing_run_id,
        "extraction_method": encode(record.extraction_method),
        "availability_status": encode(record.availability_status), "fact_type": encode(value.fact_type),
        "subject_identifier": None if financial else record.subject_identifier,
        "source_concept": record.source_concept if financial else None,
        "currency": record.currency if financial else None, "unit": record.unit if financial else None,
        "period_type": None, "period_start": None, "period_end": None,
        "period_length_days": None, "comparability_status": None,
    }
    for prefix in ("value", "candidate"):
        for column in VALUE_COLUMNS.values():
            row[f"{prefix}_{column}"] = None
    row[f"value_{VALUE_COLUMNS[value.fact_type]}"] = encode(value.value)
    if candidate is not None:
        row[f"candidate_{VALUE_COLUMNS[candidate.fact_type]}"] = encode(candidate.value)
    if financial and record.period is not None:
        period = record.period
        row.update(period_type=encode(period.period_type), period_start=encode(period.period_start),
                   period_end=encode(period.period_end), period_length_days=period.period_length_days,
                   comparability_status=encode(period.comparability_status))
    return row


def _fact(row: Row, evidence_ids: tuple[str, ...]) -> StructuredFact | FinancialFact:
    common = {
        "company_id": row["company_id"], "company_number": row["company_number"],
        "canonical_concept": row["canonical_concept"], "source_id": row["source_id"],
        "document_id": row["document_id"], "processing_run_id": row["processing_run_id"],
        "availability_status": AvailabilityStatus(text(row["availability_status"])),
        "extraction_method": ExtractionMethod(text(row["extraction_method"])), "evidence_ids": evidence_ids,
    }
    if row["record_kind"] == "STRUCTURED":
        candidate = _value(row, "candidate")
        record = StructuredFact(
            fact_id=row["fact_id"], value=_value(row, "value"),
            candidate_value=None if candidate.value is None else candidate,
            subject_identifier=row["subject_identifier"], **common,
        )
    elif row["record_kind"] == "FINANCIAL":
        period = None
        if row["period_type"] is not None:
            period = ReportingPeriod(
                period_type=PeriodType(text(row["period_type"])),
                period_start=date_value(row["period_start"]), period_end=date_value(row["period_end"]),
                period_length_days=row["period_length_days"],
                comparability_status=ComparabilityStatus(text(row["comparability_status"])),
            )
        record = FinancialFact(
            financial_fact_id=row["fact_id"], source_concept=row["source_concept"],
            value_numeric=decimal_value(row["value_numeric"]),
            candidate_value_numeric=decimal_value(row["candidate_numeric"]),
            currency=row["currency"], unit=row["unit"], period=period, **common,
        )
    else:
        raise IntegrityError("Unknown stored fact record kind")
    # Reject hidden non-selected fields and malformed representations even if
    # somebody bypassed SQL CHECK constraints when corrupting the database.
    if _fact_row(record) != row:
        raise IntegrityError("Stored fact contains inconsistent typed columns")
    return record


class _FactRepository[Fact: StructuredFact | FinancialFact]:
    """Shared SQL mechanics; public subclasses retain distinct record types."""

    def __init__(self, database: Database, kind: Literal["STRUCTURED", "FINANCIAL"]) -> None:
        self.database = database
        self._kind = kind

    def _links(self, record_id: str) -> tuple[str, ...]:
        rows = self.database.query(
            "SELECT position, evidence_id FROM fact_evidence WHERE fact_id=? ORDER BY position", (record_id,),
        )
        if [row["position"] for row in rows] != list(range(len(rows))):
            raise IntegrityError("Stored evidence ordering contains gaps")
        return tuple(text(row["evidence_id"]) for row in rows)

    def _get(self, record_id: str) -> StructuredFact | FinancialFact | None:
        rows = self.database.query("SELECT * FROM fact WHERE fact_id=?", (record_id,))
        if not rows:
            return None
        if rows[0]["record_kind"] != self._kind:
            raise IntegrityError("Fact identity belongs to a different record kind")
        return restore(lambda row: _fact(row, self._links(record_id)), rows[0])

    def save(self, record_id: str, record: Fact) -> None:
        """Save an immutable fact and ordered evidence edges in one transaction."""
        row = _fact_row(record)
        if row["record_kind"] != self._kind or row["fact_id"] != record_id:
            raise IntegrityError("Fact record kind or explicit ID differs from repository")
        with self.database.transaction():
            inserted = insert_immutable(self.database, "fact", "fact_id", row)
            if not inserted:
                if self._links(record_id) != record.evidence_ids:
                    raise IntegrityError("Immutable fact evidence links differ")
                return
            for position, evidence_id in enumerate(record.evidence_ids):
                self.database.execute("INSERT INTO fact_evidence VALUES (?, ?, ?)",
                                      (record_id, position, evidence_id))

    def fact_ids_for_evidence(self, evidence_id: str) -> tuple[str, ...]:
        """Return deterministic reverse provenance for this typed fact view."""
        rows = self.database.query(
            "SELECT DISTINCT f.fact_id FROM fact f JOIN fact_evidence e USING(fact_id) "
            "WHERE e.evidence_id=? AND f.record_kind=? ORDER BY f.fact_id", (evidence_id, self._kind),
        )
        return tuple(text(row["fact_id"]) for row in rows)


class SqlStructuredFactRepository(_FactRepository[StructuredFact]):
    """Typed persistence for governance/source observations, without interpretation."""

    def __init__(self, database: Database) -> None:
        super().__init__(database, "STRUCTURED")

    def get(self, record_id: str) -> StructuredFact | None:
        """Restore a structured fact; a financial identity is an explicit error."""
        record = self._get(record_id)
        if record is not None and not isinstance(record, StructuredFact):
            raise IntegrityError("Expected a structured fact")
        return record


class SqlFinancialFactRepository(_FactRepository[FinancialFact]):
    """Typed persistence for exact financial observations, without extraction."""

    def __init__(self, database: Database) -> None:
        super().__init__(database, "FINANCIAL")

    def get(self, record_id: str) -> FinancialFact | None:
        """Restore a financial fact and reporting context with exact Decimal values."""
        record = self._get(record_id)
        if record is not None and not isinstance(record, FinancialFact):
            raise IntegrityError("Expected a financial fact")
        return record
