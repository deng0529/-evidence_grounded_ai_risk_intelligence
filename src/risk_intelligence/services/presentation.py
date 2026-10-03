"""M8.1 user-facing presentation helpers; never recalculate persisted risk results."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from risk_intelligence.explanation import VariableExplanation


def two_dp(value: object | None) -> str:
    if value is None:
        return 'Unavailable'
    try:
        return str(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return str(value)


def belief_display(belief) -> dict[str, str]:
    return {'Low': two_dp(belief.low_belief), 'High': two_dp(belief.high_belief),
            'Unknown': two_dp(belief.unknown_belief)}


def variable_display(variable: VariableExplanation) -> dict[str, str]:
    r = variable.leaf.result
    row = {'Variable': variable.name, 'Domain': variable.domain.title(), 'Raw value': two_dp(r.raw_value),
           'Unit': r.unit, **belief_display(r.final_belief), 'Availability': r.availability_status.value.replace('_', ' ').title()}
    if variable.leaf.calculation.reasons:
        row['Issue'] = '; '.join(reason.value.replace('_', ' ').title() for reason in variable.leaf.calculation.reasons)
    return row


def risk_sentence(variable: VariableExplanation) -> str:
    """Explain only persisted beliefs; no new classification or model judgement."""
    r = variable.leaf.result
    b = r.final_belief
    if r.raw_value is None:
        return (f'{variable.name} could not be fully assessed from the validated evidence. '
                f'The unresolved share is {two_dp(b.unknown_belief)}.')
    if b.unknown_belief >= max(b.low_belief, b.high_belief):
        return (f'The recorded {variable.name} value is {two_dp(r.raw_value)} {r.unit}, '
                f'but uncertainty is the largest belief share ({two_dp(b.unknown_belief)}). '
                'The evidence does not support a confident low-risk or high-risk summary.')
    if b.low_belief == b.high_belief:
        return (f'The recorded {variable.name} value is {two_dp(r.raw_value)} {r.unit}. '
                f'Low and High have equal support; Unknown is {two_dp(b.unknown_belief)}.')
    dominant = 'high-risk'  if b.high_belief > b.low_belief else 'low-risk'
    return (f'The recorded {variable.name} value is {two_dp(r.raw_value)} {r.unit}. '
            f'Against the model reference levels, the validated evidence supports mainly the {dominant} side: '
            f'Low {two_dp(b.low_belief)}, High {two_dp(b.high_belief)}, Unknown {two_dp(b.unknown_belief)}.')
