"""Compact six-variable MVP tables and exact reference-transform explanations."""
from .dashboard_config import CONFIG
from .saved_reference_beliefs import ReferenceView, ReferenceBelief
from .leaf_belief_test import NAMES
from risk_intelligence.risk_variables.core import DEFINITIONS

VALUE_FORMULAS = {code: metadata['formula'] for code, metadata in CONFIG['variables'].items()}
REFERENCE_BASES = {code: metadata['reference_explanation'] for code, metadata in CONFIG['variables'].items()}
DEPENDENCIES = {'F1.1': ('NET_ASSETS', 'TOTAL_ASSETS'), 'F2.2': ('CURRENT_ASSETS', 'CURRENT_LIABILITIES'),
                'F2.3': ('CURRENT_ASSETS', 'INVENTORY', 'CURRENT_LIABILITIES')}


def unknown_reason(view: ReferenceView, belief: ReferenceBelief) -> str:
    """Describe missing/unusable saved inputs without asserting an unproven absence."""
    if belief.value is not None:
        return '—'
    statuses = {code: status for code, _, status in (*view.foundation.governance_variables, *view.foundation.variables)}
    status = statuses[belief.code]
    if status == 'UNKNOWN_ZERO_DENOMINATOR':
        return 'The supplied denominator is zero; this ratio cannot be calculated.'
    if belief.code.startswith('F'):
        facts = {fact.concept: fact for fact in view.foundation.facts}
        details = []
        for concept in DEPENDENCIES[belief.code]:
            fact = facts[concept]
            if fact.value is not None:
                continue
            label = concept.replace('_', ' ').title()
            if fact.availability == 'NOT_DISCLOSED':
                reason = 'not identified in the supplied data; disclosure could not be established'
            elif fact.availability == 'EXTRACTION_FAILED':
                reason = 'not found during extraction; this does not establish that the company omitted it'
            elif fact.availability == 'RETRIEVAL_FAILED':
                reason = 'source data could not be retrieved'
            elif fact.availability == 'CONFLICT_UNRESOLVED':
                reason = 'conflicting supplied values remain unresolved'
            else:
                reason = 'no usable saved value is available'
            if fact.reason:
                reason += '; ' + fact.reason
            details.append(label + ': ' + reason)
        return '; '.join(details) or 'No usable ratio is available from the supplied data.'
    if status == 'UNKNOWN_INCOMPLETE_FILING_HISTORY':
        return 'The supplied filing history is incomplete; lateness cannot be established.'
    if status == 'CONFLICT_UNRESOLVED':
        return 'Conflicting filings prevent a unique lateness value.'
    if belief.code == 'G2.2':
        return 'No usable active-director appointment dates were found in the saved data.'
    return 'The required due date or obligation period was not found in the saved data.'


def summary_rows(view: ReferenceView) -> list[dict[str, str]]:
    """Present all six values, their formulas and memberships in one table."""
    return [{'Variable': NAMES[b.code], 'Value': 'Unknown' if b.value is None else f'{b.value:.2f}',
             'Domain': 'Governance' if b.code.startswith('G') else 'Financial',
             'Value basis / formula': VALUE_FORMULAS[b.code], 'Unit': b.unit,
             'High risk': f'{b.high:.2f}', 'Low risk': f'{b.low:.2f}', 'Unknown': f'{b.unknown:.2f}',
             'Unknown reason': unknown_reason(view, b)} for b in view.beliefs]


def standards_rows(view: ReferenceView) -> list[dict[str, str]]:
    """Explain unchanged approved anchors as MVP references, not paper-derived thresholds."""
    rows = []
    for b in view.beliefs:
        d = DEFINITIONS[b.code]
        direction = (f'Value ≤ {d.low:.2f}: full Low; value ≥ {d.high:.2f}: full High.'
                     if d.high > d.low else
                     f'Value ≥ {d.low:.2f}: full Low; value ≤ {d.high:.2f}: full High.')
        rows.append({'Variable': NAMES[b.code], 'Domain': 'Governance' if b.code.startswith('G') else 'Financial',
                     'Low risk reference': f'{d.low:.2f}', 'High risk reference': f'{d.high:.2f}', 'Unit': d.unit,
                     'Reference explanation': REFERENCE_BASES[b.code] + ' ' + direction})
    return rows


def calculation_explanation(view: ReferenceView, b: ReferenceBelief) -> str:
    """Explain each actual clamped or interpolated result using its own exact value."""
    name = NAMES[b.code]
    if b.value is None:
        return f'{name} — {unknown_reason(view, b)} High=0.00, Low=0.00, Unknown=1.00.'
    d = DEFINITIONS[b.code]
    x = b.value
    low_side = x <= d.low if d.high > d.low else x >= d.low
    high_side = x >= d.high if d.high > d.low else x <= d.high
    if low_side:
        explanation = f'Value {x:.2f} is at or beyond the Low-risk reference {d.low:.2f} on the low-risk side; full Low support.'
    elif high_side:
        explanation = f'Value {x:.2f} is at or beyond the High-risk reference {d.high:.2f} on the high-risk side; full High support.'
    else:
        explanation = (f'Value {x:.2f} lies between the two references. '
                       f'High = ({x:.2f} − {d.low:.2f}) / ({d.high:.2f} − {d.low:.2f}); Low = 1 − High.')
    return (f'{name} — {explanation} High={b.high:.2f}, Low={b.low:.2f}, Unknown={b.unknown:.2f}. '
            'The calculation uses the full saved precision; displayed values are rounded.')
