"""Accepted reference beliefs enter ER unchanged; analytical ER matches recursive ER."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import pytest
from streamlit.testing.v1 import AppTest
from risk_intelligence.aggregation import er_aggregate, WeightedBelief
from risk_intelligence.domain.risk import BeliefDistribution
from risk_intelligence.risk_variables.core import DECIMAL_CONTEXT
from risk_intelligence.services.saved_reference_beliefs import calculate_saved_reference_beliefs
from risk_intelligence.services.reference_er import aggregate_reference_view, calculate_saved_reference_er, chart_rows
from tests.m8.test_leaf_belief_test import seed
from tests.m8.test_application import ENTRY, environment
from tests.m2.conftest import NUMBER


def recursive_oracle(children):
    """Independent recursive ER with importance and incompleteness split masses."""
    masses=[]
    for c in children:
        w=Fraction(c.weight); b=c.belief
        masses.append((w*Fraction(b.low_belief),w*Fraction(b.high_belief),1-w,w*Fraction(b.unknown_belief)))
    low,high,bar,tilde=masses[0]
    for l,h,bar2,tilde2 in masses[1:]:
        k=1/(1-low*h-high*l)
        low,high,bar,tilde=(k*(low*l+low*(bar2+tilde2)+(bar+tilde)*l),
                           k*(high*h+high*(bar2+tilde2)+(bar+tilde)*h),
                           k*bar*bar2,k*(tilde*tilde2+tilde*bar2+bar*tilde2))
    return low/(1-bar),high/(1-bar),tilde/(1-bar)


@pytest.mark.parametrize('values',[
    [('1','0','0')]*3,[('0','1','0')]*3,[('0','0','1')]*3,
    [('1','0','0'),('1','0','0'),('0','0','1')],
    [('.8','.1','.1'),('.1','.7','.2'),('.2','.2','.6')],
    [('1','0','0'),('0','1','0'),('0','0','1')]])
def test_analytical_matches_recursive(values):
    with localcontext(DECIMAL_CONTEXT):
        children=tuple(WeightedBelief(str(i),str(i),BeliefDistribution(low_belief=Decimal(l),high_belief=Decimal(h),unknown_belief=Decimal(u)),Decimal(1)/3)
                       for i,(l,h,u) in enumerate(values))
        actual=er_aggregate(children)
        expected=recursive_oracle(children)
        for a,e in zip((actual.low_belief,actual.high_belief,actual.unknown_belief),expected,strict=True):
            assert abs(a-Decimal(e.numerator)/Decimal(e.denominator))<Decimal('1e-45')


def test_saved_er_replays_without_old_m5_or_providers(database,storage,api,ixbrl,monkeypatch):
    seed(database,storage,api,ixbrl)
    reference=calculate_saved_reference_beliefs(database,NUMBER)
    before=database.query('SELECT * FROM processing_run')
    import risk_intelligence.services.leaf_belief_test as old
    def forbidden(*args,**kwargs): raise AssertionError('No old discounted assessment runner')
    monkeypatch.setattr(old,'run_company_assessment',forbidden)
    first=calculate_saved_reference_er(database,NUMBER); second=calculate_saved_reference_er(database,NUMBER)
    assert not first.reused and second.reused and first.overall==second.overall
    assert first.reference.beliefs==reference.beliefs
    assert len(database.query('SELECT * FROM saved_reference_er'))==1
    assert database.query('SELECT * FROM processing_run')==before
    assert not database.query('SELECT * FROM m5_variable_result')
    assert not database.query('SELECT * FROM m6_aggregation_result')
    assert [c.weight for c in first.overall.children]==[Decimal('.4'),Decimal('.6')]
    for node in first.domains: assert len(node.children)==3
    payload=json.loads(database.query('SELECT payload FROM saved_reference_er')[0]['payload'])
    assert payload['reference_calculation_id']==reference.assessment_id and len(payload['nodes'])==3
    assert abs(sum(row['Share'] for row in chart_rows(first))-1)<1e-12


def test_unknown_domain_is_retained(database,storage,api,ixbrl):
    seed(database,storage,api,ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    beliefs=tuple(replace(b,low=Decimal(1),high=Decimal(0),unknown=Decimal(0)) if b.code.startswith('G')
        else replace(b,low=Decimal(0),high=Decimal(0),unknown=Decimal(1)) for b in view.beliefs)
    domains,overall=aggregate_reference_view(replace(view,beliefs=beliefs))
    assert domains[0].belief.low_belief==1 and domains[1].belief.unknown_belief==1
    assert overall.belief.unknown_belief>0 and overall.belief.low_belief<1


def test_er_ui_pie_domains_and_drilldown(database,storage,api,ixbrl,tmp_path,monkeypatch):
    seed(database,storage,api,ixbrl)
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    at=AppTest.from_file(str(ENTRY),default_timeout=30).run()
    at.radio[0].set_value('ER aggregation test').run()
    assert not at.exception and not at.error and not at.dataframe and at.selectbox[0].value is None
    assert not database.query('SELECT * FROM saved_reference_er')
    at.selectbox[0].set_value(NUMBER).run()
    assert not at.exception and not at.error
    assert not at.metric
    assert list(at.dataframe[0].value['Domain'])==['Governance','Financial']
    assert len(at.expander)==3 and 'Financial' in at.expander[2].label
    assert not any('Step 3' in m.value or 'Step 4' in m.value for m in at.markdown)
    charts=at.get('vega_lite_chart')
    assert len(charts)==1
    spec=json.loads(charts[0].proto.spec)
    assert spec['layer'][0]['mark']['type']=='arc'
    assert spec['layer'][1]['encoding']['text']['field']=='Percentage'
    at.run()
    assert not at.error and len(database.query('SELECT * FROM saved_reference_er'))==1


def test_two_level_conflict_regression_uses_er_not_weighted_average(database,storage,api,ixbrl):
    seed(database,storage,api,ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    beliefs=tuple(replace(b,low=Decimal(1 if b.code.startswith('G') else 0),
        high=Decimal(0 if b.code.startswith('G') else 1),unknown=Decimal(0)) for b in view.beliefs)
    _,overall=aggregate_reference_view(replace(view,beliefs=beliefs))
    assert abs(overall.belief.high_belief-Decimal(9)/13)<Decimal('1e-25')
    assert abs(overall.belief.low_belief-Decimal(4)/13)<Decimal('1e-25')
    assert overall.belief.unknown_belief==0
    assert overall.belief.high_belief!=Decimal('.6')


def test_all_missing_hierarchy_is_fully_unknown(database,storage,api,ixbrl):
    seed(database,storage,api,ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    beliefs=tuple(replace(b,low=Decimal(0),high=Decimal(0),unknown=Decimal(1)) for b in view.beliefs)
    domains,overall=aggregate_reference_view(replace(view,beliefs=beliefs))
    assert all(node.belief.unknown_belief==1 for node in (*domains,overall))


@pytest.mark.parametrize('high,low,unknown', [('.3999','.6001','0'),('.4369','.5631','0'),('.2','.3','.5'),('0','1','0'),('1','0','0'),('0','0','1')])
def test_pie_angles_match_overall_beliefs(high,low,unknown):
    from math import tau
    from types import SimpleNamespace
    belief=BeliefDistribution(high_belief=Decimal(high),low_belief=Decimal(low),unknown_belief=Decimal(unknown))
    rows=chart_rows(SimpleNamespace(overall=SimpleNamespace(belief=belief)))
    assert rows[0]['Start']==0
    assert rows[-1]['End']==pytest.approx(tau)
    for row,expected in zip(rows,(high,low,unknown),strict=True):
        assert (row['End']-row['Start'])/tau==pytest.approx(float(expected))
        assert row['Middle']==pytest.approx((row['Start']+row['End'])/2)
        assert row['Percentage']==f'{Decimal(expected)*100:.2f}%'
