"""SQL-only six-leaf test workflow over saved Foundation runs; no ingestion or ER."""
from .dashboard_config import CONFIG, VARIABLE_NAMES
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from importlib.resources import files

from risk_intelligence.ingestion.companies_house.client import company_number
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.validated_repository import ValidatedEvidenceRepository
from risk_intelligence.risk_variables.core import ACTIVE_VARIABLES, DEFINITIONS, LeafAssessment, provisional
from risk_intelligence.validation.obligation_service import ObligationValidationService
from .company_assessment import persisted_leaves, run_company_assessment
from .data_foundation import FoundationView, latest_saved_run, load_foundation

WORKFLOW_VERSION = 'saved-foundation-leaf-test-v41'
STANDARD_VERSION = CONFIG['reference_standard_version']
TRANSFORM_METHOD = 'two-anchor-linear-v1; minimum-input-reliability-discount-v1'
NAMES = dict(VARIABLE_NAMES)
VALUE_RULES = {code: metadata['value_rule'] for code, metadata in CONFIG['variables'].items()}


def reference_standard_rows(database: Database) -> list[dict[str, str]]:
    """Read the approved six-row standard used by this workflow from SQL."""
    rows = database.query('SELECT * FROM risk_reference_standard WHERE standard_version=? ORDER BY variable_code', (STANDARD_VERSION,))
    by_code = {row['variable_code']: row for row in rows}
    return [{'Code': code, 'Variable': str(by_code[code]['variable_name']),
             'Domain': str(by_code[code]['domain']),
             'Low risk reference': str(by_code[code]['low_reference']),
             'High risk reference': str(by_code[code]['high_reference']),
             'Unit': str(by_code[code]['unit']),
             'Value definition': str(by_code[code]['value_definition'])} for code in ACTIVE_VARIABLES]


def persist_reference_standard(database: Database) -> None:
    """Store one immutable approved standard; reject same-version configuration drift."""
    for code in ACTIVE_VARIABLES:
        definition = DEFINITIONS[code]
        # Keep the already approved SQL row immutable; only its display alias changes.
        stored_name = 'Net Asset Position' if code == 'F1.1' else NAMES[code]
        expected = (STANDARD_VERSION, code, stored_name,
                    'GOVERNANCE' if code.startswith('G') else 'FINANCIAL',
                    str(definition.low), str(definition.high), definition.unit,
                    VALUE_RULES[code], TRANSFORM_METHOD,
                    'User-approved initial MVP references on 2026-10-04; not empirically calibrated.')
        database.execute('INSERT OR IGNORE INTO risk_reference_standard VALUES (?,?,?,?,?,?,?,?,?,?)', expected)
        rows = database.query('SELECT * FROM risk_reference_standard WHERE standard_version=? AND variable_code=?', (STANDARD_VERSION, code))
        keys = ('standard_version','variable_code','variable_name','domain','low_reference','high_reference','unit','value_definition','transform_method','approval_basis')
        if tuple(rows[0][key] for key in keys) != expected:
            raise IntegrityError('Risk reference standard version drift; create a new approved version')


@dataclass(frozen=True)
class LeafTestView:
    """Persisted leaf results plus the original snapshot; no aggregate risk outputs."""
    company_name: str
    foundation: FoundationView
    assessment_date: date
    assessment_id: str
    leaves: tuple[LeafAssessment, ...]
    reused: bool


def saved_companies(database: Database) -> tuple[tuple[str, str], ...]:
    """List only companies with saved accounts selections, without provider clients."""
    rows = database.query(
        "SELECT DISTINCT p.company_number,c.company_name FROM accounts_run_selection s "
        "JOIN processing_run p USING(processing_run_id) JOIN company c ON c.company_id=p.company_id "
        "WHERE p.status IN ('COMPLETE','PARTIAL') ORDER BY c.company_name,p.company_number")
    return tuple((str(row['company_number']), str(row['company_name'])) for row in rows)


def calculate_saved_leaf_beliefs(database: Database, number: str) -> LeafTestView:
    """Validate saved SQL inputs and persist/replay M5 once per source pair/model.

    The saved as-of date and source-year selection are retained. Missing data never
    invokes ingestion. Existing M4 and M5 services own validation and arithmetic.
    The outer transaction rolls back an incomplete test calculation.
    """
    number = company_number(number)
    with database.transaction():
        persist_reference_standard(database)
        pair = latest_saved_run(database, number)
        if pair is None:
            raise IntegrityError('No saved Foundation result; this test never starts ingestion')
        foundation = load_foundation(database, *pair)
        dates = database.query('SELECT assessment_date FROM ingestion_run WHERE processing_run_id=?', (pair[0],))
        day = date.fromisoformat(str(dates[0]['assessment_date']))
        config = files('risk_intelligence.risk_variables').joinpath('config/risk_model.yaml').read_bytes()
        fingerprint = sha256((WORKFLOW_VERSION + '|' + STANDARD_VERSION + '|' + '|'.join(pair)).encode() + config).hexdigest()
        run_id = 'leaf-test-' + fingerprint
        assessment_id = run_id + '-assessment'
        previous = database.query('SELECT status FROM processing_run WHERE processing_run_id=?', (run_id,))
        if previous:
            if previous[0]['status'] not in ('COMPLETE', 'PARTIAL'):
                raise IntegrityError('An incomplete leaf test exists; review it before retrying')
            leaves = persisted_leaves(database, assessment_id)
        else:
            report = run_company_assessment(database, number=number, assessment_date=day,
                reporting_year=foundation.requested_year, run_id=run_id, calculated_at=datetime.now(UTC),
                reuse_runs=pair)
            leaves = report.leaves
        database.execute('INSERT OR IGNORE INTO leaf_test_reference_standard VALUES (?,?)', (run_id, STANDARD_VERSION))
        if tuple(leaf.result.variable_code for leaf in leaves) != ACTIVE_VARIABLES:
            raise IntegrityError('Saved test does not contain the active model leaves')
        company = SqlCompanyRepository(database).get_by_company_number(number)
        if company is None:
            raise IntegrityError('Saved company identity is missing')
        return LeafTestView(company.company_name, foundation, day, assessment_id, leaves, bool(previous))


def leaf_explanation(leaf: LeafAssessment) -> str:
    """Explain the stored reference transform and reliable/unknown shares exactly."""
    result = leaf.result
    belief = result.final_belief
    if result.raw_value is None:
        reasons = ', '.join(reason.value for reason in leaf.calculation.reasons)
        return (f'No usable validated value: {reasons}. Low=0, High=0, Unknown=1. '
                'Missing, conflicting or inadmissible inputs cannot be replaced with zero.')
    prior = result.provisional_belief
    direction = 'increases' if result.high_reference > result.low_reference else 'decreases'
    return (f'High-risk support {direction} as the value increases. '
            f'clip(({result.raw_value} - {result.low_reference}) / '
            f'({result.high_reference} - {result.low_reference}), 0, 1) = {prior.high_belief}. '
            f'Provisional Low = 1 - {prior.high_belief} = {prior.low_belief}. '
            f'r = minimum mandatory input reliability = {result.reliability_r}. '
            f'Final High = r × provisional High = {belief.high_belief}; '
            f'Final Low = r × provisional Low = {belief.low_belief}; '
            f'Unknown = 1 - r = {belief.unknown_belief}. '
            'The unknown share represents unresolved evidence reliability, not medium risk.')


def reliability_rows(database: Database, leaf: LeafAssessment) -> list[dict[str, str]]:
    """Read the actual M4 factors and hard failures behind each M5 input."""
    repository = ValidatedEvidenceRepository(database)
    rows = []
    for item in leaf.calculation.inputs:
        if item.kind == 'OBLIGATION':
            record = ObligationValidationService(database).get(item.validated_id)
            if record is None:
                raise IntegrityError('Leaf input obligation is missing')
            assessment = record.assessment
            components = assessment.calculation.components
            factors = (components.s, components.e, components.v, components.c)
            failures = assessment.calculation.failures
            source = record.obligation_kind
            status = record.filing_state
            conflict = assessment.conflict.reason
        else:
            record = (repository.get_fact(item.validated_id) if item.kind == 'FACT'
                      else repository.get_evidence_set(item.validated_id))
            if record is None:
                raise IntegrityError('Leaf validated input is missing')
            factors = (record.source_quality_s, record.extraction_quality_e,
                       record.validation_factor_v, record.conflict_factor_c)
            failures = record.validation_report.failures
            source = record.canonical_concept if item.kind == 'FACT' else record.evidence_set_type
            status = record.availability_status.value
            conflict = record.conflict_state.reason
        rows.append({'Input': source, 'Validated ID': item.validated_id,
            'Mandatory': str(item.mandatory), 'S': str(factors[0]), 'E': str(factors[1]),
            'V': str(factors[2]), 'C': str(factors[3]), 'Input reliability r': str(item.reliability_r),
            'Input status': status, 'Conflict reason': conflict,
            'Validation failures': '; '.join(f'{f.code.value}: {f.reason}' for f in failures) or 'None'})
    return rows


def value_reference_comparison(code: str, value: Decimal | None) -> str:
    """Show a source-value diagnostic, explicitly separate from validated final beliefs."""
    if value is None:
        return 'The saved value is unavailable; a value-only reference comparison cannot be computed.'
    comparison = provisional(code, value)
    return (f'Value-only reference comparison before evidence validation: '
            f'High={comparison.high_belief}, Low={comparison.low_belief}. '
            'These are reference memberships, not the final evidence-adjusted beliefs shown above.')


def reliability_explanation(leaf: LeafAssessment, inputs: list[dict[str, str]]) -> str:
    """Explain the actual persisted reliability without displaying internal traces."""
    result = leaf.result
    details = []
    for item in inputs:
        if item['Mandatory'] != 'True':
            continue
        factors = ', '.join(f'{key}={Decimal(item[key]):.2f}' for key in ('S','E','V','C'))
        detail = f"{item['Input']}: {factors}, input reliability={Decimal(item['Input reliability r']):.2f}"
        if item['Validation failures'] != 'None':
            codes = item['Validation failures']
            detail += f'; validation exclusions: {codes}'
        details.append(detail)
    if result.raw_value is None:
        reasons = ', '.join(reason.value for reason in leaf.calculation.reasons)
        conclusion = f'Reliability={result.reliability_r:.2f}: no admissible value ({reasons}); High=0.00, Low=0.00, Unknown=1.00.'
    else:
        conclusion = f'Reliability={result.reliability_r:.2f}: the minimum reliability of the required usable inputs.'
    return NAMES[result.variable_code] + ' — ' + conclusion + (' Inputs: ' + '; '.join(details) + '.' if details else ' No usable validated mandatory input is available.')
