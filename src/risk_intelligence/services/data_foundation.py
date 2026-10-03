"""A-D data-foundation read model: raw evidence -> canonical facts -> deterministic ratios.

This module deliberately stops before M4/M5 risk validation.  It is used by the
Streamlit foundation workflow to prove ingestion, R2 persistence, extraction and
Turso persistence independently of the downstream risk engine.
"""
from dataclasses import dataclass
from datetime import date
import json
from statistics import median
from decimal import Decimal, localcontext

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.connection import Database
from risk_intelligence.risk_variables.core import DECIMAL_CONTEXT

FINANCIAL_INPUTS = ("NET_ASSETS", "TOTAL_ASSETS", "CURRENT_ASSETS", "CURRENT_LIABILITIES", "INVENTORY")


def latest_saved_run(database: Database, number: str) -> tuple[str, str] | None:
    """Select a saved Foundation pair independently of today's date; never acquire data."""
    rows = database.query(
        "SELECT s.processing_run_id FROM accounts_run_selection s JOIN processing_run p USING(processing_run_id) "
        "WHERE p.company_number=? AND p.status IN ('COMPLETE','PARTIAL') "
        "ORDER BY p.started_at DESC,p.processing_run_id DESC LIMIT 1", (number,))
    if not rows:
        return None
    m3 = str(rows[0]['processing_run_id'])
    m2 = m3[:-3] + '-m2' if m3.endswith('-m3') else ''
    if not m2 or not database.query("SELECT 1 present FROM ingestion_run i JOIN processing_run p USING(processing_run_id) "
        "WHERE i.processing_run_id=? AND p.company_number=? AND p.status IN ('COMPLETE','PARTIAL')", (m2, number)):
        raise ValueError('Saved Foundation result has no matching governance run')
    return m2, m3


@dataclass(frozen=True)
class FoundationFact:
    concept: str
    value: Decimal | None
    availability: str
    extraction_method: str | None
    document_id: str | None
    period_end: str | None
    fact_id: str | None
    reason: str | None = None


@dataclass(frozen=True)
class FoundationView:
    company_number: str
    m2_run_id: str
    m3_run_id: str
    requested_year: int
    evidence_year: int
    period_end: str
    selection_mode: str
    api_resources: tuple[dict[str, object], ...]
    documents: tuple[dict[str, object], ...]
    facts: tuple[FoundationFact, ...]
    variables: tuple[tuple[str, Decimal | None, str], ...]
    governance_inputs: tuple[dict[str, object], ...]
    governance_variables: tuple[tuple[str, Decimal | None, str], ...]
    raw_evidence: tuple[dict[str, object], ...]
    llm_processing: tuple[dict[str, object], ...]


def existing_run(database: Database, number: str, day: date, year: int) -> tuple[str, str] | None:
    """Latest compatible M2/M3 pair; never substitutes another date/year."""
    rows = database.query(
        "SELECT s.processing_run_id m3_run_id,p.started_at FROM accounts_run_selection s "
        "JOIN accounts_run a USING(processing_run_id) JOIN processing_run p USING(processing_run_id) "
        "WHERE p.company_number=? AND a.assessment_date=? AND s.requested_reporting_year=? "
        "AND p.status IN ('COMPLETE','PARTIAL') ORDER BY p.started_at DESC LIMIT 1",
        (number, day.isoformat(), year),
    )
    if not rows:
        return None
    m3 = str(rows[0]["m3_run_id"])
    # M3 is created as <application-id>-m3 in the live UI.  Prefer the matching
    # M2 identity, but verify it exists rather than silently fabricating lineage.
    candidate = m3[:-3] + "-m2" if m3.endswith("-m3") else ""
    if candidate and database.query("SELECT 1 ok FROM ingestion_run WHERE processing_run_id=?", (candidate,)):
        return candidate, m3
    m2rows = database.query(
        "SELECT i.processing_run_id FROM ingestion_run i JOIN processing_run p USING(processing_run_id) "
        "WHERE p.company_number=? AND i.assessment_date=? AND p.status IN ('COMPLETE','PARTIAL') "
        "ORDER BY p.started_at DESC LIMIT 1", (number, day.isoformat()))
    return (str(m2rows[0]["processing_run_id"]), m3) if m2rows else None


def _one_value(rows: list[FoundationFact], concept: str) -> FoundationFact:
    candidates = [r for r in rows if r.concept == concept and r.availability == 'AVAILABLE' and r.value is not None]
    values = {r.value for r in candidates}
    if len(values) == 1:
        # Multiple source occurrences with the same value are not a numerical conflict.
        return sorted(candidates, key=lambda r: (r.fact_id or ''))[0]
    if len(values) > 1:
        return FoundationFact(concept, None, 'CONFLICT_UNRESOLVED', None, None,
                              candidates[0].period_end if candidates else None, None,
                              'Different supported values exist within the selected statement; review source observations.')
    missing = [r for r in rows if r.concept == concept]
    if missing:
        chosen = sorted(missing, key=lambda r: (r.fact_id or ''))[0]
        return FoundationFact(concept, None, chosen.availability, chosen.extraction_method,
                              chosen.document_id, chosen.period_end, chosen.fact_id, chosen.reason)
    return FoundationFact(concept, None, 'NOT_DISCLOSED', None, None, None, None)



def _structured_rows(database: Database, run_id: str) -> list[dict[str, object]]:
    return database.query(
        "SELECT fact_id,canonical_concept,fact_type,value_date,value_text,subject_identifier,"
        "availability_status,extraction_method,source_id FROM fact "
        "WHERE processing_run_id=? AND record_kind='STRUCTURED' ORDER BY fact_id", (run_id,))


def _governance(database: Database, run_id: str, assessment_date: date) -> tuple[tuple[dict[str, object], ...], tuple[tuple[str, Decimal | None, str], ...]]:
    """Compute the three v1.2 governance inputs directly from persisted M2 facts.

    This is a foundation diagnostic, not M4 validation.  It is deliberately
    fail-closed: ambiguous/missing period linkage produces Unknown.
    """
    rows = _structured_rows(database, run_id)
    groups: dict[str, dict[str, object]] = {}
    for r in rows:
        subject = str(r.get('subject_identifier') or r['fact_id'])
        groups.setdefault(subject, {})[str(r['canonical_concept'])] = r

    def d(row: object) -> date | None:
        if not isinstance(row, dict) or row.get('availability_status') != 'AVAILABLE' or not row.get('value_date'):
            return None
        try: return date.fromisoformat(str(row['value_date']))
        except ValueError: return None
    def t(row: object) -> str | None:
        return str(row['value_text']) if isinstance(row, dict) and row.get('availability_status') == 'AVAILABLE' and row.get('value_text') is not None else None

    # Filing receipt dates keyed by the reporting/made-up date stated by the filing.
    filings: dict[tuple[str, date], list[date]] = {}
    for event in groups.values():
        category=t(event.get('FILINGS_CATEGORY')); receipt=d(event.get('FILINGS_DATE'))
        raw=t(event.get('FILINGS_DESCRIPTION_VALUES_JSON'))
        made=None
        if raw:
            try:
                obj=json.loads(raw); value=obj.get('made_up_date') if isinstance(obj,dict) else None
                made=date.fromisoformat(value) if isinstance(value,str) else None
            except (ValueError,TypeError,json.JSONDecodeError): pass
        if category in {'accounts','confirmation-statement'} and receipt and made and receipt <= assessment_date:
            filings.setdefault((category,made),[]).append(receipt)

    profile = {}
    for r in rows:
        c=str(r['canonical_concept'])
        if c.startswith('PROFILE_'): profile[c]=r

    filing_snapshot = database.query(
        "SELECT availability_status,complete FROM resource_snapshot "
        "WHERE processing_run_id=? AND resource='filing-history' ORDER BY rowid DESC LIMIT 1",
        (run_id,),
    )
    filing_history_complete = bool(
        filing_snapshot
        and str(filing_snapshot[0].get('availability_status')) == 'AVAILABLE'
        and int(filing_snapshot[0].get('complete') or 0) == 1
    )

    def lateness(kind: str, period_concept: str, due_concept: str) -> tuple[dict[str, object], tuple[str, Decimal | None, str]]:
        """Evaluate the current explicit Companies House obligation fail-closed.

        The profile's NEXT_* fields describe the current/next obligation, not the
        most recent historical filing.  A missing filing is therefore *not* a
        missing input when its due date is still in the future: lateness is
        deterministically zero at the assessment date.  Once due, absence is
        treated as outstanding only when the persisted filing-history population
        is complete; otherwise the result remains Unknown.
        """
        code = 'G1.1' if kind == 'accounts' else 'G1.2'
        period = d(profile.get(period_concept))
        due = d(profile.get(due_concept))
        matches = sorted(filings.get((kind, period), [])) if period else []
        receipt: date | None = matches[0] if len(matches) == 1 else None
        state = 'UNRESOLVED'
        value: Decimal | None = None
        status = 'UNKNOWN_MISSING_INPUT'

        if period is not None and due is not None:
            if len(matches) > 1:
                status = 'CONFLICT_UNRESOLVED'
            elif receipt is not None:
                # A filing after the assessment date is never admitted above.
                value = Decimal(max(0, (receipt - due).days))
                status = 'AVAILABLE'
                state = 'FILED'
            elif assessment_date < due:
                # The obligation is not due yet.  No filing receipt is required
                # to establish zero lateness at the assessment date.
                value = Decimal(0)
                status = 'AVAILABLE'
                state = 'NOT_YET_DUE'
            elif filing_history_complete:
                value = Decimal(max(0, (assessment_date - due).days))
                status = 'AVAILABLE'
                state = 'OUTSTANDING'
            else:
                status = 'UNKNOWN_INCOMPLETE_FILING_HISTORY'

        info = {
            'Variable': code,
            'Obligation period / made up to': period.isoformat() if period else 'Unknown',
            'Due date': due.isoformat() if due else 'Unknown',
            'Filed date': receipt.isoformat() if receipt else '—',
            'Obligation state': state,
            'Days late at assessment': str(value) if value is not None else 'Unknown',
            'Status': status,
            'Method': 'COMPANIES_HOUSE_API + deterministic date arithmetic',
        }
        return info, (code, value, status)

    g11i,g11=lateness('accounts','PROFILE_ACCOUNTS_NEXT_ACCOUNTS_PERIOD_END_ON','PROFILE_ACCOUNTS_NEXT_ACCOUNTS_DUE_ON')
    g12i,g12=lateness('confirmation-statement','PROFILE_CONFIRMATION_STATEMENT_NEXT_MADE_UP_TO','PROFILE_CONFIRMATION_STATEMENT_NEXT_DUE')

    directors=[]
    for subject,event in groups.items():
        role=t(event.get('OFFICERS_OFFICER_ROLE')); appointed=d(event.get('OFFICERS_APPOINTED_ON')); resigned=d(event.get('OFFICERS_RESIGNED_ON'))
        if role == 'director' and appointed and appointed <= assessment_date and (resigned is None or resigned > assessment_date):
            directors.append((subject,appointed))
    tenures=[Decimal((assessment_date-a).days)/Decimal('365.2425') for _,a in directors]
    g22v=Decimal(str(median(tenures))) if tenures else None
    g22status='AVAILABLE' if g22v is not None else 'UNKNOWN_MISSING_INPUT'
    g22i={'Variable':'G2.2','Active directors':len(directors),
          'Appointment dates':', '.join(a.isoformat() for _,a in sorted(directors,key=lambda x:x[1])) or 'Unknown',
          'Assessment date':assessment_date.isoformat(),'Status':g22status,'Method':'API_DIRECT + deterministic median tenure'}
    return (g11i,g12i,g22i),(g11,g12,('G2.2',g22v,g22status))


def load_foundation(database: Database, m2_run_id: str, m3_run_id: str) -> FoundationView:
    selection = database.query("SELECT * FROM accounts_run_selection WHERE processing_run_id=?", (m3_run_id,))
    if len(selection) != 1:
        raise ValueError('Foundation run has no unique reporting-year selection')
    selected = selection[0]
    period_end = str(selected['selected_period_end'])
    repository = AccountsRepository(database)
    links = database.query("SELECT fact_id FROM accounts_run_fact WHERE processing_run_id=? ORDER BY fact_id", (m3_run_id,))
    observed: list[FoundationFact] = []
    for row in links:
        fact = repository.canonical.get(str(row['fact_id']))
        if fact is None or fact.canonical_concept not in FINANCIAL_INPUTS:
            continue
        # Extraction selected one coherent source statement. Read only that period;
        # never pool different statements because their dates share a calendar year.
        if fact.period is not None and fact.period.period_end.isoformat() != period_end:
            continue
        reason_rows = database.query(
            'SELECT reason FROM financial_fact_missing_reason WHERE fact_id=?',
            (fact.financial_fact_id,))
        missing_reason = str(reason_rows[0]['reason']) if len(reason_rows) == 1 else None
        observed.append(FoundationFact(
            fact.canonical_concept, fact.value_numeric, fact.availability_status.value,
            fact.extraction_method.value if fact.extraction_method else None, fact.document_id,
            fact.period.period_end.isoformat() if fact.period else None, fact.financial_fact_id, missing_reason))
    facts = tuple(_one_value(observed, concept) for concept in FINANCIAL_INPUTS)
    values = {f.concept: f.value for f in facts}

    def ratio(code: str, numerator: Decimal | None, denominator: Decimal | None) -> tuple[str, Decimal | None, str]:
        if numerator is None or denominator is None:
            return code, None, 'UNKNOWN_MISSING_INPUT'
        if denominator == 0:
            return code, None, 'UNKNOWN_ZERO_DENOMINATOR'
        with localcontext(DECIMAL_CONTEXT):
            return code, numerator / denominator, 'AVAILABLE'

    f11 = ratio('F1.1', values['NET_ASSETS'], values['TOTAL_ASSETS'])
    f22 = ratio('F2.2', values['CURRENT_ASSETS'], values['CURRENT_LIABILITIES'])
    quick_num = None if values['CURRENT_ASSETS'] is None or values['INVENTORY'] is None else values['CURRENT_ASSETS'] - values['INVENTORY']
    f23 = ratio('F2.3', quick_num, values['CURRENT_LIABILITIES'])
    resources = tuple(database.query(
        "SELECT resource,availability_status,complete,page_count,item_count,reused_snapshot_id "
        "FROM resource_snapshot WHERE processing_run_id=? ORDER BY resource", (m2_run_id,)))
    documents = tuple(database.query(
        "SELECT filing_fact_id,document_id,status,availability_status,reason,reused_raw,reused_parse "
        "FROM accounts_run_document WHERE processing_run_id=? ORDER BY rowid", (m3_run_id,)))
    run = database.query("SELECT company_number FROM processing_run WHERE processing_run_id=?", (m3_run_id,))
    governance_inputs, governance_variables = _governance(database, m2_run_id, date.fromisoformat(str(database.query("SELECT assessment_date FROM ingestion_run WHERE processing_run_id=?", (m2_run_id,))[0]['assessment_date'])))
    raw_evidence = tuple(database.query("SELECT raw_evidence_id,object_path,checksum,media_type,processing_run_id FROM raw_evidence WHERE processing_run_id IN (?,?) ORDER BY processing_run_id,raw_evidence_id", (m2_run_id,m3_run_id)))
    llm_processing = tuple(database.query(
        "SELECT p.status,p.version,p.output_raw_id,p.error_code FROM accounts_run_processing rp "
        "JOIN accounts_processing p USING(fingerprint) WHERE rp.processing_run_id=? AND p.stage='LLM' ORDER BY p.created_at",
        (m3_run_id,)))
    return FoundationView(
        company_number=str(run[0]['company_number']), m2_run_id=m2_run_id, m3_run_id=m3_run_id,
        requested_year=int(selected['requested_reporting_year']), evidence_year=int(selected['evidence_reporting_year']),
        period_end=period_end, selection_mode=str(selected['selection_mode']), api_resources=resources,
        documents=documents, facts=facts, variables=(f11, f22, f23), governance_inputs=governance_inputs,
        governance_variables=governance_variables, raw_evidence=raw_evidence, llm_processing=llm_processing)
