"""Hierarchical Yang/Xu analytical ER over the accepted reference memberships."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from math import tau

from risk_intelligence.aggregation import WeightedBelief, er_aggregate, aggregation_identity
from risk_intelligence.domain.risk import BeliefDistribution
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.risk_variables.core import DECIMAL_CONTEXT, ACTIVE_VARIABLES, model_aggregation_config
from .saved_reference_beliefs import ReferenceView, calculate_saved_reference_beliefs
from .leaf_belief_test import NAMES
from .reference_presentation import calculation_explanation

ER_VERSION = 'yang-xu-analytical-er-reference-v45'
PAPER_URL = 'https://personalpages.manchester.ac.uk/staff/jian-bo.yang/JB%20Yang%20Journal_Papers/ER-Aggregation-IEEE.pdf'


@dataclass(frozen=True)
class ERNode:
    """One aggregate with exact local importance weights and child lineage."""
    code: str
    result_id: str
    belief: BeliefDistribution
    children: tuple[WeightedBelief, ...]


@dataclass(frozen=True)
class ERView:
    """Reference inputs, two domain nodes and the final overall node."""
    reference: ReferenceView
    domains: tuple[ERNode, ...]
    overall: ERNode
    fingerprint: str
    reused: bool


def aggregate_reference_view(view: ReferenceView) -> tuple[tuple[ERNode, ...], ERNode]:
    """Use the existing ER engine and registry, without a second reliability discount."""
    if tuple(b.code for b in view.beliefs) != ACTIVE_VARIABLES:
        raise IntegrityError('ER requires exactly the accepted six reference variables')
    config = model_aggregation_config('1.2')
    leaves = {b.code: b for b in view.beliefs}
    domains = []
    with localcontext(DECIMAL_CONTEXT):
        for domain, spec in config.items():
            if spec['weighting_policy'] != 'EQUAL_WEIGHT_ACTIVE_VARIABLES':
                raise IntegrityError('Unsupported reference ER weighting policy')
            codes = spec['variables']
            weight = Decimal(1) / Decimal(len(codes))
            children = tuple(WeightedBelief(code=code, result_id=view.assessment_id + ':' + code,
                belief=BeliefDistribution(low_belief=leaves[code].low, high_belief=leaves[code].high,
                    unknown_belief=leaves[code].unknown), weight=weight) for code in codes)
            identity = aggregation_identity(view.assessment_id, domain, ER_VERSION, children)
            domains.append(ERNode(domain, identity, er_aggregate(children), children))
        top_children = tuple(WeightedBelief(code=node.code, result_id=node.result_id, belief=node.belief,
            weight=Decimal(config[node.code]['weight'])) for node in domains)
        overall = ERNode('OVERALL', aggregation_identity(view.assessment_id, 'OVERALL', ER_VERSION, top_children),
                         er_aggregate(top_children), top_children)
    return tuple(domains), overall


def calculate_saved_reference_er(database: Database, number: str) -> ERView:
    """Persist/reuse ER by exact accepted reference inputs, weights and method version."""
    with database.transaction():
        reference = calculate_saved_reference_beliefs(database, number)
        domains, overall = aggregate_reference_view(reference)
        payload = {'nodes': [{'code': n.code, 'result_id': n.result_id, 'belief': n.belief.model_dump(mode='json'),
            'children': [{'code': c.code, 'result_id': c.result_id, 'weight': str(c.weight),
                          'belief': c.belief.model_dump(mode='json')} for c in n.children]}
            for n in (*domains, overall)], 'risk_model_version': '1.2', 'method_version': ER_VERSION,
            'reference_calculation_id': reference.assessment_id}
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        fingerprint = sha256(encoded.encode()).hexdigest()
        previous = database.query('SELECT payload FROM saved_reference_er WHERE fingerprint=?', (fingerprint,))
        if previous and previous[0]['payload'] != encoded:
            raise IntegrityError('Stored ER calculation differs from its fingerprint')
        database.execute('INSERT OR IGNORE INTO saved_reference_er VALUES (?,?,?,?)',
                         (fingerprint, reference.assessment_id, ER_VERSION, encoded))
    return ERView(reference, domains, overall, fingerprint, bool(previous))


def node_rows(nodes: tuple[ERNode, ...]) -> list[dict[str, str]]:
    """Format domain results without converting stored beliefs into rounded inputs."""
    return [{'Domain': n.code.title(), 'High risk': f'{n.belief.high_belief:.2f}',
             'Low risk': f'{n.belief.low_belief:.2f}', 'Unknown': f'{n.belief.unknown_belief:.2f}'} for n in nodes]


def child_rows(node: ERNode) -> list[dict[str, str]]:
    """Show the exact child distributions used by this node and local weights."""
    return [{'Input': NAMES.get(c.code, c.code.title()), 'Weight': '1/3 (equal)' if len(node.children) == 3 else f'{c.weight:.2f}',
             'High risk': f'{c.belief.high_belief:.2f}', 'Low risk': f'{c.belief.low_belief:.2f}',
             'Unknown': f'{c.belief.unknown_belief:.2f}'} for c in node.children]


def chart_rows(view: ERView) -> list[dict[str, object]]:
    """Float conversion is for chart rendering only; all ER calculation uses Decimal."""
    b = view.overall.belief
    rows = []
    start = 0.0
    for name, value in (('High risk', b.high_belief), ('Low risk', b.low_belief), ('Unknown', b.unknown_belief)):
        share = float(value)
        end = start + share * tau
        rows.append({'Risk': name, 'Share': share, 'Percentage': f'{value * 100:.2f}%',
                     'Start': start, 'End': end, 'Middle': (start + end) / 2})
        start = end
    return rows


def node_explanation(node: ERNode) -> str:
    """Explain this actual output, including missingness and agreement/disagreement."""
    high = [NAMES.get(c.code, c.code.title()) for c in node.children if c.belief.high_belief > c.belief.low_belief]
    low = [NAMES.get(c.code, c.code.title()) for c in node.children if c.belief.low_belief > c.belief.high_belief]
    missing = [NAMES.get(c.code, c.code.title()) for c in node.children if c.belief.unknown_belief > 0]
    details = []
    if high: details.append('More High than Low support: ' + ', '.join(high) + '.')
    if low: details.append('More Low than High support: ' + ', '.join(low) + '.')
    if missing: details.append('Unassigned input support retained: ' + ', '.join(missing) + '. These inputs keep their original importance weights.')
    if high and low: details.append('Inputs disagree; ER normalizes their combined support. Disagreement is not automatically labelled Unknown.')
    if not missing: details.append('All input assessments are complete, so this node has no missing-information share.')
    b = node.belief
    return (' '.join(details) + f' ER result: High={b.high_belief:.2f}, Low={b.low_belief:.2f}, Unknown={b.unknown_belief:.2f}.')


def variable_explanations(view: ERView, node: ERNode) -> tuple[str, ...]:
    """Trace a domain down to the same saved values and reference standards as V44."""
    codes = {c.code for c in node.children}
    return tuple(calculation_explanation(view.reference, b) for b in view.reference.beliefs if b.code in codes)


def source_input_rows(view: ERView, node: ERNode) -> list[dict[str, str]]:
    """Trace ratios to saved financial amounts and governance metrics to API dates."""
    if node.code == 'FINANCIAL':
        return [{'Input': f.concept.replace('_', ' ').title(),
                 'Value': 'Unknown' if f.value is None else f'{f.value:.2f}',
                 'Status': f.availability.replace('_', ' ').title(),
                 'Period end': f.period_end or 'Unknown',
                 'Document': f.document_id or 'Unknown'} for f in view.reference.foundation.facts]
    return [{str(key): NAMES.get(str(value), str(value)) if key == 'Variable' else str(value)
             for key, value in row.items() if key not in {'Method', 'Status'}}
            for row in view.reference.foundation.governance_inputs]


def load_dashboard_er(database: Database, number: str) -> ERView:
    """Read existing structured sources and derive the accepted hierarchy without writes.

    Uses the same reference values, versioned anchors and ER engine as the test
    workflow. No migrations, provider calls or evidence extraction are performed.
    """
    reference = calculate_saved_reference_beliefs(database, number, persist=False)
    domains, overall = aggregate_reference_view(reference)
    return ERView(reference, domains, overall, overall.result_id, reference.reused)
