"""Independent source reliability and traceable explanations for reference beliefs."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.storage.objects import verify_checksum
from .saved_reference_beliefs import ReferenceView, ReferenceBelief
from .leaf_belief_test import calculate_saved_leaf_beliefs, reliability_rows, reliability_explanation, NAMES

DEPENDENCIES = {'F1.1': ('NET_ASSETS', 'TOTAL_ASSETS'),
                'F2.2': ('CURRENT_ASSETS', 'CURRENT_LIABILITIES'),
                'F2.3': ('CURRENT_ASSETS', 'INVENTORY', 'CURRENT_LIABILITIES')}


@dataclass(frozen=True)
class ReliabilityView:
    """Actual audit reliability; never multiplies the reference memberships."""
    values: dict[str, Decimal]
    explanations: dict[str, str]
    error: str | None = None


def source_reliability(database: Database, view: ReferenceView) -> ReliabilityView:
    """Reuse the existing versioned source audit as an independent assessment.

    M4 checks source evidence, not the converted memberships. Zero reliability
    remains visible with its exclusions, while reference beliefs stay unchanged.
    A lineage error is explicit and never replaces the direct numerical result.
    """
    try:
        audit = calculate_saved_leaf_beliefs(database, view.foundation.company_number)
    except IntegrityError:
        return ReliabilityView({}, {}, 'Source reliability audit unavailable: saved evidence lineage is incomplete or inconsistent.')
    if (audit.foundation.m2_run_id, audit.foundation.m3_run_id) != (view.foundation.m2_run_id, view.foundation.m3_run_id):
        return ReliabilityView({}, {}, 'Source reliability audit uses a different saved snapshot; select the company again.')
    database.execute('INSERT OR IGNORE INTO reference_source_audit VALUES (?,?)',
                     (view.assessment_id, audit.assessment_id))
    links = database.query('SELECT assessment_id FROM reference_source_audit WHERE calculation_id=?', (view.assessment_id,))
    if links != [{'assessment_id': audit.assessment_id}]:
        raise IntegrityError('Reference result is linked to a different source reliability audit')
    values = {}
    explanations = {}
    for leaf in audit.leaves:
        code = leaf.result.variable_code
        values[code] = leaf.result.reliability_r
        inputs = reliability_rows(database, leaf)
        details = reliability_explanation(leaf, inputs)
        # The independent audit's final beliefs must not be presented as this
        # workflow's unchanged reference memberships.
        details = details.replace('; High=0.00, Low=0.00, Unknown=1.00.', '.')
        if leaf.result.raw_value is None and inputs:
            details += ' Inspected source inputs: ' + '; '.join(
                f"{item['Input']}: S={Decimal(item['S']):.2f}, E={Decimal(item['E']):.2f}, "
                f"V={Decimal(item['V']):.2f}, C={Decimal(item['C']):.2f}, "
                f"r={Decimal(item['Input reliability r']):.2f}; exclusions: {item['Validation failures']}"
                for item in inputs) + '.'
        explanations[code] = details + ' This independent source audit does not change the reference High, Low or Unknown.'
    return ReliabilityView(values, explanations)


def evidence_rows(database: Database, view: ReferenceView, code: str) -> list[dict[str, object]]:
    """Resolve only the selected source facts and their exact recorded locators.

    A derived total retains every original operand. XHTML has concept/context
    locators rather than invented PDF page numbers. Governance retains API paths.
    """
    if code.startswith('F'):
        facts = {f.concept: f for f in view.foundation.facts}
        rows = []
        for concept in DEPENDENCIES[code]:
            fact = facts[concept]
            if not fact.fact_id:
                continue
            operands = database.query(
                'SELECT s.source_fact_id,s.source_label,s.source_concept,s.value AS source_value,s.currency,s.unit,e.*, '
                'r.raw_evidence_id,r.media_type,src.source_url '
                'FROM financial_observation_component c JOIN financial_source_fact s USING(source_fact_id) '
                'JOIN evidence_reference e ON e.evidence_id=s.evidence_id '
                'JOIN raw_evidence r ON r.source_id=e.source_id JOIN source src ON src.source_id=e.source_id '
                'WHERE c.fact_id=? ORDER BY c.position', (fact.fact_id,))
            for item in operands:
                rows.append({**item, 'canonical_concept': concept,
                             'canonical_value': str(fact.value) if fact.value is not None else None,
                             'fact_id': fact.fact_id})
        return rows
    # Match the API resources involved in this variable, retaining JSON paths.
    resources = ('officers',) if code == 'G2.2' else ('profile', 'filing-history')
    placeholders = ','.join('?' for _ in resources)
    return database.query(
        'SELECT DISTINCT e.*,r.raw_evidence_id,r.media_type,s.source_url '
        'FROM fact f JOIN fact_evidence fe USING(fact_id) JOIN evidence_reference e USING(evidence_id) '
        'JOIN raw_evidence r ON r.source_id=e.source_id JOIN source s ON s.source_id=e.source_id '
        'JOIN api_response a ON a.source_id=e.source_id '
        f'WHERE f.processing_run_id=? AND a.resource IN ({placeholders}) ORDER BY e.evidence_id',
        (view.foundation.m2_run_id, *resources))


def reference_rationale(view: ReferenceView, belief: ReferenceBelief) -> str:
    """Explain the actual numerator/denominator and reference-defined risk direction."""
    if belief.value is None:
        return 'The saved variable value is missing. High and Low are zero; Unknown is one. Missing inputs are not assumed to be zero.'
    facts = {f.concept: f for f in view.foundation.facts}
    def amount(concept: str) -> str:
        value = facts[concept].value
        return 'Unknown' if value is None else f'{value:.2f}'
    if belief.code == 'F1.1':
        detail = (f'Equity Ratio = net assets ({amount("NET_ASSETS")}) / total assets ({amount("TOTAL_ASSETS")}) = {belief.value:.2f}. '
                  'A smaller net-assets buffer relative to the asset base receives more high-risk support under the approved references. '
                  'Negative net assets indicate liabilities exceed assets. A positive but small ratio indicates a thin equity buffer; '
                  'it does not by itself establish why the buffer is small.')
    elif belief.code == 'F2.2':
        detail = (f'Current Ratio = current assets ({amount("CURRENT_ASSETS")}) / current liabilities ({amount("CURRENT_LIABILITIES")}) = {belief.value:.2f}. '
                  'High-risk support reflects limited current-asset coverage of current liabilities relative to the approved buffer. '
                  'The ratio alone cannot establish whether asset levels fell or liabilities rose.')
        if belief.value < 1:
            detail += ' Current assets are below current liabilities, so the recorded coverage is less than one-to-one.'
        else:
            detail += ' Current assets cover current liabilities at least one-to-one, but high-risk support can remain when the approved safety buffer is not met.'
    elif belief.code == 'F2.3':
        detail = (f'Quick Ratio = [current assets ({amount("CURRENT_ASSETS")}) - inventory ({amount("INVENTORY")})] / '
                  f'current liabilities ({amount("CURRENT_LIABILITIES")}) = {belief.value:.2f}. '
                  'Inventory is excluded from the liquid-asset numerator. High-risk support reflects limited coverage of current '
                  'liabilities by the remaining current assets. This does not establish whether the cause is low assets, large inventory '
                  'or large liabilities without further comparative evidence.')
        if belief.value < 1:
            detail += ' After excluding inventory, the recorded numerator is below current liabilities.'
    else:
        detail = (f'{NAMES[belief.code]} has saved value {belief.value:.2f} {belief.unit}. '
                  + ('Longer filing delay receives more high-risk support.' if belief.code != 'G2.2' else
                     'Shorter median active-director tenure receives more high-risk support under this reference standard; it does not prove misconduct.'))
    from risk_intelligence.risk_variables.core import DEFINITIONS
    anchors = DEFINITIONS[belief.code]
    return (detail + f' Low-risk reference={anchors.low:.2f}; high-risk reference={anchors.high:.2f}. '
            f'High={belief.high:.2f}, Low={belief.low:.2f}, Unknown={belief.unknown:.2f}. '
            'These are the project reference standards, not a universal industry verdict.')


class EvidenceReader(Protocol):
    """Existing storage adapters supply immutable raw bytes."""
    def read(self, object_path: str) -> bytes:
        """Read the indexed object without transforming its contents."""
        ...


def read_supporting_evidence(database: Database, view: ReferenceView, raw_id: str, storage: EvidenceReader) -> tuple[bytes, str, str]:
    """Read and checksum-check only evidence reachable from this selected snapshot."""
    allowed = {str(row['raw_evidence_id']) for b in view.beliefs for row in evidence_rows(database, view, b.code)}
    if raw_id not in allowed:
        raise IntegrityError('Document is not supporting evidence for this saved company')
    rows = database.query('SELECT object_path,checksum,media_type FROM raw_evidence WHERE raw_evidence_id=?', (raw_id,))
    if len(rows) != 1:
        raise IntegrityError('Supporting raw evidence is missing')
    row = rows[0]
    content = storage.read(str(row['object_path']))
    verify_checksum(content, str(row['checksum']))
    extension = {'application/pdf': 'pdf', 'application/xhtml+xml': 'xhtml', 'application/json': 'json'}.get(str(row['media_type']), 'bin')
    return content, str(row['media_type']), f'{view.foundation.company_number}_{raw_id}.{extension}'
