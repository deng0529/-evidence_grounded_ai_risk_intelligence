"""Approved filing-first routes, flexible units and closest-column regressions."""
import base64
from datetime import date
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from risk_intelligence.ingestion.accounts.llm import OpenAIExtraction
from risk_intelligence.ingestion.accounts.period_selection import select_period
from risk_intelligence.ingestion.accounts.semantic_values import semantic_amount, semantic_period
from risk_intelligence.ingestion.accounts.models import ExtractionResult
from test_ixbrl_direct_semantic import candidate, fact, PERIOD, admit


@pytest.mark.parametrize('unit,scale', [('GBP units', 0), ('pounds sterling', 0),
    ("£'000s", 3), ('GBP thousands', 3), ('£000s', 3), ('GBP millions', 6)])
def test_displayed_unit_variants_preserve_exact_money(unit, scale):
    assert semantic_amount('(1,234)', unit, 'GBP') == (Decimal(-1234) * Decimal(10) ** scale, scale)


def test_html_excerpt_format_and_actual_year_do_not_reject_supported_amount():
    result = admit(candidate(label='Inventories', quote='Inventory in company notes: £ 300',
                             reporting_year=2024, unit='GBP units'),
        visible='Company stocks 300 250', requested=('INVENTORY',), document_id='d',
        number='ZZ000003', year=2025, period_end=PERIOD.period_end)
    assert result.value == 300 and result.period.period_end == date(2024, 12, 31)


def test_grouping_spaces_do_not_make_a_different_amount_valid():
    result = admit(candidate(raw_value='4,048,511', quote='Stocks 4 048 511'),
        visible='Stocks 4 048 511', requested=('INVENTORY',), document_id='d',
        number='ZZ000003', year=2025, period_end=PERIOD.period_end)
    assert result.value == 4048511


def test_same_year_statement_dates_are_selected_once_not_combined():
    march = fact('NET_ASSETS').model_copy(update={'period': PERIOD.model_copy(update={'period_end':date(2025,3,31)})})
    september = march.model_copy(update={'source_fact_id':'september', 'value':Decimal(999),
        'period': PERIOD.model_copy(update={'period_end':date(2025,9,30)})})
    result = select_period(ExtractionResult(facts=(march,september), periods=(march.period,september.period),
                          complete=True), 2025, date(2025,3,31))
    assert result.facts == (march,) and result.periods == (march.period,)
    assert select_period(result, 2025, date(2025,3,31)) == result


def test_closest_displayed_year_and_missing_year_default():
    previous = fact('NET_ASSETS').model_copy(update={'period': PERIOD.model_copy(update={'period_end':date(2024,6,30)})})
    older = previous.model_copy(update={'source_fact_id':'older', 'period': PERIOD.model_copy(update={'period_end':date(2023,6,30)})})
    result = select_period(ExtractionResult(facts=(older,previous),periods=(),complete=True),2025)
    assert result.facts == (previous,)
    assert semantic_period(None, 2025, None) == date(2025,12,31)
    assert semantic_period('', 2025, date(2025,3,31)) == date(2025,3,31)


def test_responses_request_contains_complete_35_page_pdf_not_rendered_subset(monkeypatch):
    import openai
    import pymupdf
    with pymupdf.open() as doc:
        for _ in range(35): doc.new_page()
        original = doc.tobytes()
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            self.responses = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(model='configured-model',status='completed',output_text='{"candidates":[]}')
    monkeypatch.setattr(openai, 'OpenAI', Client)
    output = OpenAIExtraction(SecretStr('synthetic'), 'configured-model', config_version='test').extract_pdf_file(
        json.dumps({'preferred_reporting_year':2025}), original)
    content = captured['input'][0]['content']
    sent = base64.b64decode(next(c['file_data'] for c in content if c['type']=='input_file').split(',',1)[1])
    assert sent == original
    with pymupdf.open(stream=sent,filetype='pdf') as doc: assert len(doc)==35
    prompt = next(c['text'] for c in content if c['type']=='input_text')
    assert 'financial reporting expert' in prompt and 'accounting substance' in prompt
    assert 'Do not mistake investments, debtors or fixed assets for inventory' in prompt
    assert 'NOT a required year' in prompt and 'closest' in prompt and 'all pages' in prompt
    assert captured['store'] is False
    assert json.loads(output)['prompt_version']=='financial-pdf-file-semantic-v32-expert'
