"""Human-readable input coverage only; never calculate a risk variable."""

from decimal import Decimal

from risk_intelligence.persistence.connection import Database, IntegrityError

GOVERNANCE = (
    ('G1.1 Accounts Filing Lateness', ('PROFILE_ACCOUNTS_', 'FILINGS_DATE'), 'Due/filing dates need period linkage; no lateness calculated.'),
    ('G1.2 Confirmation Statement Lateness', ('PROFILE_CONFIRMATION_STATEMENT_', 'FILINGS_DATE'), 'Due/filing dates need statement linkage; no lateness calculated.'),
    ('G2.1 Director Turnover — 24 Months', ('OFFICERS_APPOINTED_ON', 'OFFICERS_RESIGNED_ON', 'OFFICERS_OFFICER_ROLE'), 'Director population and 24-month coverage require review; no turnover calculated.'),
    ('G2.2 Median Tenure of Active Directors', ('OFFICERS_APPOINTED_ON', 'OFFICERS_APPOINTED_BEFORE', 'OFFICERS_RESIGNED_ON'), 'Exact dates and active status require review; no median calculated.'),
    ('G2.3 Director Change Concentration — 90 Days', ('OFFICERS_APPOINTED_ON', 'OFFICERS_RESIGNED_ON'), 'Rolling-window population anchors require review; no concentration calculated.'),
    ('G3.1 PSC / Control Change Frequency — 36 Months', ('PSC_NOTIFIED_ON', 'PSC_CEASED_ON', 'PSC_NATURES_OF_CONTROL'), 'Control-event history and statements coverage require review; no substantive-change count calculated.'),
)
FINANCIAL = (
    ('F1.1 Net Asset Position — Equity / Total Assets', ('NET_ASSETS', 'TOTAL_ASSETS')),
    ('F1.2 Net Asset Trend', ('NET_ASSETS',)),
    ('F2.2 Current Ratio', ('CURRENT_ASSETS', 'CURRENT_LIABILITIES')),
    ('F2.3 Quick Ratio', ('CURRENT_ASSETS', 'INVENTORY', 'CURRENT_LIABILITIES')),
    ('F3.1 Debt Burden — Interest-Bearing Debt / Total Assets', ('INTEREST_BEARING_DEBT', 'TOTAL_ASSETS')),
)


def _cell(value: object) -> str:
    return ('NULL' if value is None else str(value)).replace('|', '\\|').replace('\n', ' ')


def readiness_report(database: Database, run_id: str) -> str:
    """Render all 11 future-variable inputs, exact financial values and provenance.

    Reports retain competing observations and explicitly distinguish input presence
    from M4 suitability. Historical M2 provenance is identified rather than treated
    as freshly retrieved evidence.
    """
    runs = database.query('SELECT a.*,p.company_id,p.company_number,p.status,c.company_name '
        'FROM accounts_run a JOIN processing_run p USING(processing_run_id) '
        'JOIN company c USING(company_id) WHERE a.processing_run_id=?', (run_id,))
    if not runs:
        raise IntegrityError('M3 run does not exist')
    run = runs[0]
    output = ['# Data Readiness Report', '', f"Company: {run['company_name']} ({run['company_number']})",
        f"Assessment date: {run['assessment_date']}; M3 run: {run_id}; status: {run['status']}",
        f"Mapping: {run['mapping_version']}; stopping condition: {run['stopping_reason']}", '',
        'Input coverage only. No reliability, risk-variable, belief or ER calculations.', '',
        '## Governance inputs', '', '| Future variable | Input coverage | Limitation |', '| --- | --- | --- |']
    governance = database.query("SELECT fact_id,canonical_concept,subject_identifier,value_date,value_text,value_boolean,"
        "availability_status,source_id,processing_run_id FROM fact WHERE company_id=? AND record_kind='STRUCTURED'",
        (run['company_id'],))
    for name, prefixes, reason in GOVERNANCE:
        matched = [f for f in governance if any(str(f['canonical_concept']).startswith(p) for p in prefixes)]
        available = [f for f in matched if f['availability_status'] == 'AVAILABLE']
        output.append(f'| {name} | {len(available)} available input records; REVIEW REQUIRED | {reason} |')
    output += ['', '### M2 source coverage', '', '| Resource | Checked at | Complete | Availability | Snapshot |', '| --- | --- | --- | --- | --- |']
    snapshots = database.query('SELECT resource,checked_at,complete,availability_status,snapshot_id '
        'FROM resource_snapshot WHERE company_id=? ORDER BY checked_at,resource', (run['company_id'],))
    for row in snapshots:
        output.append('| ' + ' | '.join(_cell(v) for v in row.values()) + ' |')
    output += ['', 'PSC Statements retrieval failure is not evidence of zero control changes.', '',
        '### Governance date/event evidence', '', '| Fact | Subject | Value | Availability | Source |', '| --- | --- | --- | --- | --- |']
    prefixes = tuple(p for _, items, _ in GOVERNANCE for p in items)
    for fact in governance:
        if any(str(fact['canonical_concept']).startswith(p) for p in prefixes):
            value = fact['value_date'] if fact['value_date'] is not None else fact['value_text']
            output.append('| ' + ' | '.join(_cell(v) for v in (fact['fact_id'], fact['subject_identifier'],
                value, fact['availability_status'], fact['source_id'])) + ' |')
    facts = database.query("SELECT DISTINCT f.*,l.origin,l.mapping_version,l.derivation_version,d.filing_id "
        "FROM accounts_run_fact rf JOIN fact f ON f.fact_id=rf.fact_id "
        "JOIN document d ON d.document_id=f.document_id LEFT JOIN financial_observation_lineage l ON l.fact_id=f.fact_id "
        "WHERE rf.processing_run_id=? AND f.record_kind='FINANCIAL' ORDER BY f.period_end DESC,f.canonical_concept,f.fact_id", (run_id,))
    output += ['', '## Financial input readiness', '', '| Future variable | Input coverage |', '| --- | --- |']
    for name, concepts in FINANCIAL:
        available = {f['canonical_concept'] for f in facts if f['availability_status'] == 'AVAILABLE'}
        missing = [c for c in concepts if c not in available]
        note = 'Missing/unresolved: ' + ', '.join(missing) if missing else 'Inputs present; period/entity/conflict suitability requires M4 review'
        if name.startswith('F1.2'):
            count = len({f['period_end'] for f in facts if f['canonical_concept'] == 'NET_ASSETS' and f['availability_status'] == 'AVAILABLE'})
            note += f'; {count} candidate periods, comparability not decided'
        output.append(f'| {name} | {note} |')
    output += ['', '### Financial coverage by reporting period', '',
        '| Period | Variable | Input coverage |', '| --- | --- | --- |']
    for period in sorted({f['period_end'] for f in facts}, reverse=True):
        available = {f['canonical_concept'] for f in facts
                     if f['period_end'] == period and f['availability_status'] == 'AVAILABLE'}
        for name, concepts in FINANCIAL:
            if name.startswith('F1.2'):
                continue  # Trend coverage is multi-period and is described above.
            missing = [concept for concept in concepts if concept not in available]
            note = 'Missing/unresolved: '+', '.join(missing) if missing else 'Inputs present; M4 review required'
            output.append('| '+ ' | '.join(_cell(v) for v in (period,name,note))+' |')
    output += ['', '## Financial observations', '',
        '| Concept | Period | Value | Currency/unit | Availability | Origin | Filing/document | Locator | Method |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for fact in facts:
        locators = database.query('SELECT e.page,e.label,e.concept,e.context_id FROM evidence_reference e '
            'JOIN fact_evidence fe USING(evidence_id) WHERE fe.fact_id=? ORDER BY fe.position', (fact['fact_id'],))
        locator = '; '.join(' '.join(str(v) for v in row.values() if v is not None) for row in locators) or 'Source document; value unavailable'
        output.append('| ' + ' | '.join(_cell(v) for v in (fact['canonical_concept'], fact['period_end'],
            format(Decimal(fact['value_numeric']), 'f') if fact['value_numeric'] is not None else None,
            f"{fact['currency'] or ''}/{fact['unit'] or ''}", fact['availability_status'],
            fact['origin'] or 'unavailable', f"{fact['filing_id']}/{fact['document_id']}", locator, fact['extraction_method'])) + ' |')
    if not facts:
        output += ['', 'No canonical observations were published; no reporting periods are invented.']
    output += ['', '## Document outcomes', '', '| Filing fact | Status | Availability | Reason | Raw reused | Parse reused |',
        '| --- | --- | --- | --- | --- | --- |']
    for row in database.query('SELECT filing_fact_id,status,availability_status,reason,reused_raw,reused_parse '
            'FROM accounts_run_document WHERE processing_run_id=?', (run_id,)):
        output.append('| ' + ' | '.join(_cell(v) for v in row.values()) + ' |')
    return '\n'.join(output) + '\n'
