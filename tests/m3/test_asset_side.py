"""Complete asset structure, exact totals and fail-closed context checks."""

from datetime import date
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import ExtractionMethod
from risk_intelligence.ingestion.accounts.asset_side import inspect_asset_side
from risk_intelligence.ingestion.accounts.interpretation import VERSION, deterministic_proposals, verify, calculate
from risk_intelligence.ingestion.accounts.mapping import default_registry
from risk_intelligence.ingestion.accounts.pdf import PageText, Word, extract_pdf
from risk_intelligence.ingestion.companies_house.client import ParseError


def asset_page(*, intangible: str = '12', omit: bool = False, group: bool = False,
               extra: bool = False, subtotal: str = '115') -> PageText:
    """A synthetic statement with independently printed fixed/current subtotals."""
    entries = [(10, 'Group balance sheet' if group else 'Company balance sheet', None),
        (20, 'at 31 December 2025', None), (30, 'GBP', None),
        (40, '', ('2025', '2024')), (50, 'Fixed assets', None),
        (70, 'Tangible fixed assets', ('100', '100')), (80, 'Investments', ('3', '3')),
        (90, '', (subtotal, subtotal)), (100, 'Current assets', None),
        (110, 'Stocks', ('200', '200')), (120, '', ('200', '200')),
        (130, 'Current liabilities', ('40', '40')), (140, 'Net assets', ('275', '275'))]
    if not omit:
        entries.append((60, 'Intangible fixed assets', (intangible, intangible)))
    if extra:
        entries.append((85, 'Other assets', ('5', '5')))
    words = []
    for y, label, values in entries:
        if label:
            words.append(Word(x=10.0, y=float(y), right=220.0, text=label))
        for right, value in zip((310, 410), values or ()):
            words.append(Word(x=float(right-30), y=float(y), right=float(right), text=value))
    return PageText(page=2, words=tuple(words), method=ExtractionMethod.PDF_OCR_DETERMINISTIC)


def inspected(**changes):
    page = asset_page(**changes)
    return inspect_asset_side((page,), extract_pdf((page,), 'd', 'ZZ000003'))


def derivations(result):
    return [d for d in deterministic_proposals(result,default_registry()) if d.proposal.kind == 'DERIVATION']


def test_complete_subtotals_preserve_dynamic_operands_and_proof() -> None:
    result = inspected()
    decisions = derivations(result)
    assert len(decisions) == 2
    for decision in decisions:
        assert decision.status == 'AVAILABLE' and decision.value == Decimal('315')
        assert [o.source_label for o in decision.proposal.operands] == ['Fixed assets','current assets']
        assert decision.proposal.version == VERSION
        assert decision.proposal.proof_id in {p.proof_id for p in result.proofs}


@pytest.mark.parametrize('changes',[{'group':True},{'extra':True},{'subtotal':'114'}])
def test_incomplete_or_contradictory_asset_structure_rejected(changes) -> None:
    assert not inspected(**changes).proofs


def test_absent_intangible_is_not_required_when_complete_subtotal_disclosed() -> None:
    result = inspected(omit=True,subtotal='103')
    assert derivations(result)[0].value == Decimal('303')
    assert not any(f.source_label == 'Intangible fixed assets' for f in result.facts)


def test_component_structure_without_printed_subtotal_and_missing_not_zero() -> None:
    page = asset_page()
    page = page.model_copy(update={'words':tuple(w for w in page.words if w.y != 90)})
    result = inspect_asset_side((page,),extract_pdf((page,),'d','ZZ000003'))
    decision = derivations(result)[0]
    assert decision.value == Decimal('315') and len(decision.proposal.operands) == 4
    nil = page.model_copy(update={'words':tuple(w.model_copy(update={'text':'-'}) if w.y == 60 and w.x > 200 else w for w in page.words)})
    assert not inspect_asset_side((nil,),extract_pdf((nil,),'d','ZZ000003')).proofs


@pytest.mark.parametrize('change',['group','period','currency','missing','value','locator','duplicate','operation'])
def test_dynamic_plan_rejects_ungrounded_or_mixed_operands(change) -> None:
    result = inspected()
    proposal = derivations(result)[0].proposal
    items = list(proposal.operands)
    if change in ('group','period','currency'):
        update = {'scope':'GROUP'} if change == 'group' else ({'period_end':date(2000,12,31)} if change == 'period' else {'currency':'USD'})
        proposal = proposal.model_copy(update=update)
    elif change == 'missing':
        items.pop()
    elif change == 'duplicate':
        items.append(items[0])
    else:
        update = {'value':Decimal('999')} if change == 'value' else ({'evidence_id':'other'} if change == 'locator' else {'operation':'MULTIPLY'})
        items[0] = items[0].model_copy(update=update)
    proposal = proposal.model_copy(update={'operands':tuple(items)})
    assert verify(proposal,result,default_registry()).status == 'VALIDATION_FAILED'


def test_subtotal_and_child_double_count_is_rejected() -> None:
    from risk_intelligence.ingestion.accounts.interpretation import operand
    result = inspected()
    proposal = derivations(result)[0].proposal
    child = next(f for f in result.facts if f.source_concept == 'structure:fixed-component')
    proposal = proposal.model_copy(update={'operands':proposal.operands+(operand(child),)})
    assert verify(proposal,result,default_registry()).status == 'VALIDATION_FAILED'


@pytest.mark.parametrize('reported,expected',[('275','AVAILABLE'),('276','VALIDATION_FAILED')])
def test_assets_less_liabilities_is_cross_check_not_total(reported,expected) -> None:
    page = asset_page()
    words = list(page.words)
    words.append(Word(x=10.0,y=150.0,right=220.0,text='Total assets less current liabilities'))
    for right in (310,410):
        words.append(Word(x=float(right-30),y=150.0,right=float(right),text=reported))
    page = page.model_copy(update={'words':tuple(words)})
    result = inspect_asset_side((page,),extract_pdf((page,),'d','ZZ000003'))
    decisions = derivations(result)
    assert decisions[0].status == expected
    assert result.proofs[0].cross_check_ids
    source = next(f for f in result.facts if f.source_concept=='structure:assets-less-current-liabilities')
    assert default_registry().map(source,company_id='c',company_number='ZZ000003',source_id='s',processing_run_id='r') is None


def test_direct_disclosure_wins_and_llm_plan_uses_python_result() -> None:
    result = inspected()
    proposal = derivations(result)[0].proposal.model_copy(update={'method':'LLM_DERIVATION'})
    assert verify(proposal,result,default_registry()).value == Decimal('315')
    base = result.facts[0]
    direct = base.model_copy(update={'source_fact_id':'direct','evidence_id':'direct-e','source_concept':'pdf-label:total assets','value':Decimal('999')})
    updated = result.model_copy(update={'facts':result.facts+(direct,)})
    assert any(d.status == 'SUPERSEDED' for d in derivations(updated))


def test_bounded_arithmetic_has_no_code_and_protects_division() -> None:
    proposal = derivations(inspected())[0].proposal
    left,right = proposal.operands
    assert calculate((left,right.model_copy(update={'operation':'SUBTRACT'}))) == Decimal('-85')
    with pytest.raises(ParseError,match='zero'):
        calculate((left,right.model_copy(update={'value':Decimal('0'),'operation':'DIVIDE'})))


def test_additional_asset_section_before_fixed_assets_prevents_completeness() -> None:
    page = asset_page()
    words = page.words + (Word(x=10.0,y=45.0,right=220.0,text='Assets held for sale'),
                         Word(x=280.0,y=45.0,right=310.0,text='10'),
                         Word(x=380.0,y=45.0,right=410.0,text='10'))
    page = page.model_copy(update={'words':words})
    result = inspect_asset_side((page,),extract_pdf((page,),'d','ZZ000003'))
    assert not result.proofs
