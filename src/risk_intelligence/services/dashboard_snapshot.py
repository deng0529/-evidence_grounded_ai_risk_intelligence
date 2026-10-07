"""Prepare one complete display snapshot per company; viewing only reads saved JSON."""
from hashlib import sha256
from pydantic import BaseModel, ConfigDict
from risk_intelligence.persistence.connection import Database, IntegrityError
from .dashboard_config import configuration_fingerprint, CONFIG
from .data_foundation import latest_saved_run
from .leaf_belief_test import saved_companies, NAMES
from .reference_er import calculate_saved_reference_er, chart_rows, node_rows, child_rows, node_explanation, source_input_rows
from .reference_presentation import summary_rows, standards_rows, calculation_explanation


class SnapshotUnavailable(ValueError):
    """A missing, stale or damaged published result requires maintenance preparation."""


class DashboardSnapshot(BaseModel):
    """Versioned display data with no live providers or calculations in the UI."""
    model_config = ConfigDict(extra='forbid')
    version: str
    company_number: str
    company_name: str
    assessment_date: str
    evidence_year: int | None
    chart: list[dict]
    domain_rows: list[dict[str, str]]
    overall_inputs: list[dict[str, str]]
    overall_explanation: str
    domains: list[dict]
    variables: list[dict[str, str]]
    standards: list[dict[str, str]]
    explanations: list[dict[str, str]]
    reference_id: str
    overall_id: str


def prepare_dashboard_snapshot(database: Database, number: str) -> DashboardSnapshot:
    """Compute through accepted services once; atomically upsert the current display."""
    with database.transaction():
        view = calculate_saved_reference_er(database, number)
        reference = view.reference
        pair = latest_saved_run(database, number)
        if pair is None:
            raise SnapshotUnavailable('No saved company evidence is available.')
        snapshot = DashboardSnapshot(version=CONFIG['version'], company_number=number,
            company_name=reference.company_name, assessment_date=str(reference.assessment_date),
            evidence_year=reference.foundation.evidence_year, chart=chart_rows(view),
            domain_rows=node_rows(view.domains), overall_inputs=child_rows(view.overall),
            overall_explanation=node_explanation(view.overall),
            domains=[{'name':node.code.title(), 'result':node_rows((node,)),
                      'inputs':child_rows(node), 'explanation':node_explanation(node),
                      'sources':source_input_rows(view,node)} for node in view.domains],
            variables=summary_rows(reference), standards=standards_rows(reference),
            explanations=[{'name':NAMES[b.code], 'text':calculation_explanation(reference,b)} for b in reference.beliefs],
            reference_id=reference.assessment_id, overall_id=view.overall.result_id)
        payload=snapshot.model_dump_json()
        digest=sha256(payload.encode()).hexdigest()
        database.execute('INSERT INTO dashboard_snapshot VALUES (?,?,?,?,?,?) '
            'ON CONFLICT(company_number) DO UPDATE SET m2_run_id=excluded.m2_run_id, '
            'm3_run_id=excluded.m3_run_id, config_fingerprint=excluded.config_fingerprint, '
            'payload_hash=excluded.payload_hash, payload=excluded.payload',
            (number,*pair,configuration_fingerprint(),digest,payload))
    return snapshot


def load_dashboard_snapshot(database: Database, number: str) -> DashboardSnapshot:
    """Read saved results, refusing stale lineage/configuration without recalculation."""
    rows=database.query('SELECT * FROM dashboard_snapshot WHERE company_number=?',(number,))
    if not rows:
        raise SnapshotUnavailable('This company has no published risk result yet. Please ask the maintainer to prepare its saved results.')
    row=rows[0]
    if row['config_fingerprint']!=configuration_fingerprint():
        raise SnapshotUnavailable('The saved result uses an earlier configuration. Updated results need to be prepared by the maintainer.')
    if latest_saved_run(database,number)!=(row['m2_run_id'],row['m3_run_id']):
        raise SnapshotUnavailable('Newer saved evidence is available. Please ask the maintainer to refresh this result.')
    payload=str(row['payload'])
    if sha256(payload.encode()).hexdigest()!=row['payload_hash']:
        raise IntegrityError('Saved dashboard result integrity check failed')
    snapshot=DashboardSnapshot.model_validate_json(payload)
    if snapshot.company_number!=number or snapshot.version!=CONFIG['version']:
        raise IntegrityError('Saved dashboard result identity/version mismatch')
    return snapshot


def prepare_all_dashboard_snapshots(database: Database) -> tuple[str, ...]:
    """Prepare the existing company set atomically, with no ingestion or cleanup."""
    with database.transaction():
        numbers=tuple(number for number,_ in saved_companies(database))
        for number in numbers:
            prepare_dashboard_snapshot(database,number)
    return numbers
