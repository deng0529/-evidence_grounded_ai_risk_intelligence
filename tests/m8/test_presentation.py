from decimal import Decimal
from risk_intelligence.services.presentation import two_dp, belief_display, variable_display


def test_two_decimal_display_only():
    assert two_dp(Decimal('0.58265125')) == '0.58'
    assert two_dp(Decimal('1.0754626628')) == '1.08'
    assert two_dp(None) == 'Unavailable'


def test_user_variable_table_hides_internal_code_and_normal_reason(database, assessed):
    from risk_intelligence.services.application import AssessmentApplication
    view = AssessmentApplication(database).load(assessed[0].assessment_id)
    row = variable_display(view.explanation.variables[0])
    assert 'Code' not in row and 'Reliability' not in row
    assert 'Reason' not in row and 'Issue' not in row
    assert set(('Variable','Domain','Raw value','Unit','Low','High','Unknown','Availability')) <= set(row)


def test_display_never_changes_persisted_belief(database, assessed):
    from risk_intelligence.services.application import AssessmentApplication
    view = AssessmentApplication(database).load(assessed[0].assessment_id)
    before = view.explanation.overall.result.belief
    shown = belief_display(before)
    after = AssessmentApplication(database).load(assessed[0].assessment_id).explanation.overall.result.belief
    assert before == after
    assert all(len(value.split('.')[-1]) == 2 for value in shown.values())


def test_unknown_dominance_is_not_described_as_low_risk(database, assessed):
    from risk_intelligence.services.application import AssessmentApplication
    from risk_intelligence.services.presentation import risk_sentence
    from risk_intelligence.domain.risk import BeliefDistribution
    variable = AssessmentApplication(database).load(assessed[0].assessment_id).explanation.variables[0]
    result = variable.leaf.result.model_copy(update={'final_belief': BeliefDistribution(
        low_belief=Decimal('.10'), high_belief=Decimal('.20'), unknown_belief=Decimal('.70'))})
    leaf = variable.leaf.model_copy(update={'result': result})
    text = risk_sentence(variable.model_copy(update={'leaf': leaf}))
    assert 'uncertainty is the largest' in text
    assert 'mainly the' not in text
