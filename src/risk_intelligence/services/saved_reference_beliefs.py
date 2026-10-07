"""Direct reference transformation of accepted saved Foundation values.

This user-approved test workflow does not rerun M4, discount by reliability,
or replace historical evidence-adjusted M5 assessments.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from risk_intelligence.ingestion.companies_house.client import company_number
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.risk_variables.core import ACTIVE_VARIABLES, DEFINITIONS, provisional
from .data_foundation import FoundationView, latest_saved_run, load_foundation
from .leaf_belief_test import STANDARD_VERSION, persist_reference_standard

METHOD_VERSION = 'saved-value-linear-no-discount-v42'


@dataclass(frozen=True)
class ReferenceBelief:
    """Exact numeric membership; absent values retain full Unknown."""
    code: str
    value: Decimal | None
    unit: str
    high: Decimal
    low: Decimal
    unknown: Decimal


def transform_saved_value(code: str, value: Decimal | None) -> ReferenceBelief:
    """Apply the approved two anchors once, without evidence revalidation."""
    definition = DEFINITIONS[code]
    if value is None:
        return ReferenceBelief(code, None, definition.unit, Decimal(0), Decimal(0), Decimal(1))
    prior = provisional(code, value)
    return ReferenceBelief(code, value, definition.unit, prior.high_belief, prior.low_belief, Decimal(0))


@dataclass(frozen=True)
class ReferenceView:
    """Saved source lineage and six memberships, separate from M5 assessments."""
    company_name: str
    foundation: FoundationView
    assessment_date: date
    assessment_id: str
    beliefs: tuple[ReferenceBelief, ...]
    reused: bool


def calculate_saved_reference_beliefs(database: Database, number: str, *, persist: bool = True) -> ReferenceView:
    """Read accepted Foundation values, transform and persist once per fingerprint.

    With persist=False, no standards or result rows are written (public viewing).
    No provider, M4 validation, M5 assessment or ER aggregation is called.
    Numeric precision and source runs are retained; reliability is not fabricated.
    """
    number = company_number(number)
    with database.transaction():
        if persist:
            persist_reference_standard(database)
        pair = latest_saved_run(database, number)
        if pair is None:
            raise IntegrityError('No saved Foundation result; this test never starts ingestion')
        foundation = load_foundation(database, *pair)
        values = {code: value for code, value, _ in (*foundation.governance_variables, *foundation.variables)}
        beliefs = tuple(transform_saved_value(code, values[code]) for code in ACTIVE_VARIABLES)
        rows = [{'code': b.code, 'value': str(b.value) if b.value is not None else None,
                 'unit': b.unit, 'high': str(b.high), 'low': str(b.low), 'unknown': str(b.unknown),
                 'low_reference': str(DEFINITIONS[b.code].low),
                 'high_reference': str(DEFINITIONS[b.code].high)} for b in beliefs]
        payload = json.dumps(rows, sort_keys=True, separators=(',', ':'))
        fingerprint = sha256(('|'.join((METHOD_VERSION, STANDARD_VERSION, *pair)) + payload).encode()).hexdigest()
        calculation_id = 'reference-' + fingerprint
        previous = database.query('SELECT payload FROM saved_reference_belief WHERE calculation_id=?', (calculation_id,))
        if previous and previous[0]['payload'] != payload:
            raise IntegrityError('Stored reference transformation differs from its fingerprint')
        if persist:
            database.execute('INSERT OR IGNORE INTO saved_reference_belief VALUES (?,?,?,?,?,?,?)',
                             (calculation_id, number, *pair, STANDARD_VERSION, METHOD_VERSION, payload))
        dates = database.query('SELECT assessment_date FROM ingestion_run WHERE processing_run_id=?', (pair[0],))
        company = SqlCompanyRepository(database).get_by_company_number(number)
        if company is None:
            raise IntegrityError('Saved company identity is missing')
        return ReferenceView(company.company_name, foundation, date.fromisoformat(str(dates[0]['assessment_date'])),
                             calculation_id, beliefs, bool(previous))
