"""Direct saved-value memberships must not be suppressed by another M4 pass."""
from decimal import Decimal
import pytest
from risk_intelligence.services.saved_reference_beliefs import transform_saved_value, calculate_saved_reference_beliefs
from tests.m8.test_leaf_belief_test import seed
from tests.m2.conftest import NUMBER

@pytest.mark.parametrize('code,value,high,low', [
    ('G1.1','45','0.5','0.5'), ('G1.2','15','0.5','0.5'),
    ('G2.2','3','0.5','0.5'), ('G2.2','9.339','0','1'),
    ('F1.1','0.09','0.1','0.9'), ('F1.1','0.48914','0','1'),
    ('F2.2','1.3','0.5','0.5'), ('F2.3','0.85','0.5','0.5'),
    ('F1.1','-0.1','1','0'), ('F2.2','2','0','1')])
def test_direct_numeric_conversion(code,value,high,low):
    b=transform_saved_value(code,Decimal(value))
    assert b.high == Decimal(high) and b.low == Decimal(low) and b.unknown == 0
    assert b.high+b.low+b.unknown == 1

@pytest.mark.parametrize('code',['G1.1','G1.2','G2.2','F1.1','F2.2','F2.3'])
def test_only_missing_values_are_unknown(code):
    b=transform_saved_value(code,None)
    assert (b.high,b.low,b.unknown)==(0,0,1)


def test_sql_direct_transform_skips_m4_preserves_source_and_replays(database,storage,api,ixbrl,monkeypatch):
    seed(database,storage,api,ixbrl)
    import risk_intelligence.services.leaf_belief_test as old
    def forbidden(*args,**kwargs):
        raise AssertionError('No second assessment or validation allowed')
    monkeypatch.setattr(old,'run_company_assessment',forbidden)
    before=database.query('SELECT * FROM processing_run')
    view=calculate_saved_reference_beliefs(database,NUMBER)
    assert len(view.beliefs)==6 and not view.reused
    for b in view.beliefs:
        assert b.unknown == (1 if b.value is None else 0)
    again=calculate_saved_reference_beliefs(database,NUMBER)
    assert again.reused and again.beliefs==view.beliefs
    assert len(database.query('SELECT * FROM saved_reference_belief'))==1
    assert database.query('SELECT * FROM processing_run')==before
    assert not database.query('SELECT * FROM m5_variable_result')
    assert not database.query('SELECT * FROM m6_aggregation_result')
