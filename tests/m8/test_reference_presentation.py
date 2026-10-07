"""Explain boundary direction, interpolation and typed missingness in the compact UI."""
from dataclasses import replace
from decimal import Decimal
import pytest
from risk_intelligence.services.saved_reference_beliefs import calculate_saved_reference_beliefs, transform_saved_value
from risk_intelligence.services.reference_presentation import calculation_explanation, unknown_reason, standards_rows
from tests.m8.test_leaf_belief_test import seed
from tests.m2.conftest import NUMBER

@pytest.mark.parametrize('code,value,text,high,low',[
 ('G1.1','0','full Low','0','1'), ('G1.1','90','full High','1','0'),
 ('G1.1','45','between','0.5','0.5'), ('G2.2','9','full Low','0','1'),
 ('G2.2','1','full High','1','0'), ('G2.2','4','between','0.25','0.75'),
 ('F1.1','0.2','full Low','0','1'), ('F1.1','0.09','between','0.1','0.9'),
])
def test_boundary_and_interpolation_explanations(code,value,text,high,low):
 b=transform_saved_value(code,Decimal(value))
 paragraph=calculation_explanation(None,b)
 assert text in paragraph
 assert b.high==Decimal(high) and b.low==Decimal(low) and b.unknown==0
 assert f'High={Decimal(high):.2f}' in paragraph
 assert f'Low={Decimal(low):.2f}' in paragraph


def test_missing_extraction_is_not_asserted_as_company_non_disclosure(database,storage,api,ixbrl):
 seed(database,storage,api,ixbrl)
 view=calculate_saved_reference_beliefs(database,NUMBER)
 facts=tuple(replace(f,value=None,availability='EXTRACTION_FAILED',reason=None) if f.concept=='INVENTORY' else f for f in view.foundation.facts)
 view=replace(view,foundation=replace(view.foundation,facts=facts))
 b=transform_saved_value('F2.3',None)
 reason=unknown_reason(view,b)
 assert 'Inventory: not found during extraction' in reason
 assert 'does not establish that the company omitted it' in reason
 assert 'Unknown=1.00' in calculation_explanation(view,b)


def test_zero_denominator_and_unchanged_six_standards(database,storage,api,ixbrl):
 seed(database,storage,api,ixbrl)
 view=calculate_saved_reference_beliefs(database,NUMBER)
 variables=tuple((code,None,'UNKNOWN_ZERO_DENOMINATOR') if code=='F2.2' else (code,value,status) for code,value,status in view.foundation.variables)
 view=replace(view,foundation=replace(view.foundation,variables=variables))
 assert 'denominator is zero' in unknown_reason(view,transform_saved_value('F2.2',None))
 rows=standards_rows(view)
 assert len(rows)==6
 assert 'Value ≥ 5.00: full Low' in rows[2]['Reference explanation']
 assert rows[3]['Low risk reference']=='0.10'
 assert 'one tenth' in rows[3]['Reference explanation']
