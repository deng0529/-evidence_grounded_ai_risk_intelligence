"""Synthetic layout and evidence admission, with no OpenAI network calls."""

from datetime import date
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import ExtractionMethod
from risk_intelligence.ingestion.accounts.pdf import PageText, Word, extract_pdf, pdf_pages
from risk_intelligence.ingestion.accounts.llm import Candidate, OpenAIExtraction
from risk_intelligence.ingestion.accounts.fallback import admit_candidate, page_lines
from risk_intelligence.ingestion.companies_house.client import ParseError


def layout() -> PageText:
    words = []
    for y, content in [(10, 'Balance sheet'), (20, 'at 31 December 2025'), (30, 'GBP')]:
        words.append(Word(x=10.0, y=float(y), right=180.0, text=content))
    words.extend((Word(x=280.0, y=40.0, right=310.0, text='2025'),
                  Word(x=380.0, y=40.0, right=410.0, text='2024')))
    for y, label, current, comparative in [(60, 'Net assets', '(500)', '750'), (80, 'Inventory', '0', '10')]:
        words.extend((Word(x=10.0, y=float(y), right=150.0, text=label),
                      Word(x=280.0, y=float(y), right=310.0, text=current),
                      Word(x=380.0, y=float(y), right=410.0, text=comparative)))
    return PageText(page=1, words=tuple(words), method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC)


def test_pdf_row_period_alignment_negative_and_explicit_zero() -> None:
    result = extract_pdf((layout(),), 'd', 'ZZ000003')
    assert [f.value for f in result.facts] == [Decimal('-500'), Decimal('750'), Decimal(0), Decimal(10)]
    assert result.facts[0].period.period_end == date(2025, 12, 31)
    assert result.facts[1].period_role == 'COMPARATIVE'
    assert not result.complete  # Parsed balance sheet is not proof of notes coverage.


def test_unaligned_pdf_amount_does_not_get_nearest_number() -> None:
    page = layout()
    fields = page.model_dump()
    fields['words'] = tuple(Word(**(w.model_dump() | {'right': 340.0})) if w.text == '(500)' else w for w in page.words)
    result = extract_pdf((PageText(**fields),), 'd', 'ZZ000003')
    assert all(f.source_label != 'net assets' for f in result.facts)
    assert any(f.source_label == 'inventory' for f in result.facts)
    assert not result.complete


def test_group_heading_preserves_source_scope_without_company_mapping() -> None:
    from risk_intelligence.ingestion.accounts.mapping import default_registry
    page = layout()
    words = tuple(Word(**(w.model_dump() | {'text': 'Consolidated balance sheet'}))
                  if w.text == 'Balance sheet' else w for w in page.words)
    result = extract_pdf((PageText(page=1, words=words, method=page.method),), 'd', 'ZZ000003')
    assert all(f.dimensions == (('pdf:entity-scope','GROUP'),) for f in result.facts)
    assert all(default_registry().map(f, company_id='c', company_number='ZZ000003', source_id='s',
               processing_run_id='r') is None for f in result.facts)


def test_unique_printed_section_subtotal_is_direct_not_component_sum() -> None:
    page = layout()
    words = tuple(w for w in page.words if w.y != 60) + (
        Word(x=10.0,y=55.0,right=150.0,text='Current assets'),
        Word(x=280.0,y=95.0,right=310.0,text='400'),
        Word(x=380.0,y=95.0,right=410.0,text='500'),
        Word(x=10.0,y=110.0,right=150.0,text='Current liabilities'),)
    result = extract_pdf((PageText(page=1,words=words,method=page.method),), 'd', 'ZZ000003')
    values = [f.value for f in result.facts if f.source_label == 'current assets']
    assert values == [Decimal(400),Decimal(500)]
    assert all(f.extraction_method == ExtractionMethod.PDF_NATIVE_DETERMINISTIC for f in result.facts)


def test_scanned_pdf_routes_to_ocr_and_missing_resources_fail_explicitly() -> None:
    import pymupdf
    with pymupdf.open() as doc:
        doc.new_page()
        content = doc.tobytes()
    with pytest.raises(ParseError, match='requires OCR'):
        pdf_pages(content)
    with pytest.raises(ParseError, match='PDF/OCR processing failed'):
        pdf_pages(content, ocr=True, tessdata='nonexistent-test-tessdata')


def test_detail_columns_and_note_reference_do_not_shift_year_values() -> None:
    words = [Word(x=10.0, y=float(y), right=180.0, text=text) for y, text in
             ((10, 'Company balance sheet'), (20, 'at 31 December 2025'), (30, 'GBP'),
              (50, 'Current assets'), (60, 'Stocks'), (90, 'Current liabilities'))]
    for y, right, text in ((40,424,'2025'),(40,557,'2024'),(60,286,'18'),
                          (60,356,'120'),(60,489,'80'),(80,356,'400'),(80,489,'300'),
                          (90,424,'200'),(90,557,'150')):
        words.append(Word(x=float(right-30),y=float(y),right=float(right),text=text))
    page = PageText(page=1,words=tuple(words),method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC)
    facts = extract_pdf((page,), 'd', 'ZZ000003').facts
    assert [(f.source_label,f.value) for f in facts] == [
        ('current assets',Decimal(400)),('current assets',Decimal(300)),
        ('stocks',Decimal(120)),('stocks',Decimal(80)),
        ('current liabilities',Decimal(200)),('current liabilities',Decimal(150))]
    ambiguous = PageText(page=1,words=page.words + (
        Word(x=394.0,y=60.0,right=424.0,text='999'),),method=page.method)
    assert all(f.source_label != 'stocks' for f in extract_pdf((ambiguous,), 'd', 'ZZ000003').facts)


def test_native_pdf_word_extraction_uses_real_parser() -> None:
    import pymupdf
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((30, 40), 'Synthetic accounts contain native text that can be located by page and position for testing only.')
        content = doc.tobytes()
    pages = pdf_pages(content)
    assert pages[0].method == ExtractionMethod.PDF_NATIVE_DETERMINISTIC
    assert pages[0].page == 1 and any(w.text == 'Synthetic' for w in pages[0].words)


def candidate_page() -> PageText:
    words = [Word(x=10.0,y=float(y),right=220.0,text=text) for y,text in
             ((10,'Company balance sheet'),(20,'at 31 December 2025'),(30,'GBP'),
              (50,'Creditors: amounts falling due'),(60,'within one year'))]
    for y,right,text in ((40,310,'2025'),(40,410,'2024'),(60,310,'(100)'),(60,410,'(80)')):
        words.append(Word(x=float(right-30),y=float(y),right=float(right),text=text))
    return PageText(page=2,words=tuple(words),method=ExtractionMethod.PDF_OCR_DETERMINISTIC)


def candidate(value: str = '100') -> Candidate:
    return Candidate(page=2,row_start=5,row_end=6,concept='CURRENT_LIABILITIES',kind='DIRECT',
        scope='COMPANY',support='SUPPORTED',label='Creditors: amounts falling due within one year',
        period_end='2025-12-31',currency='GBP',unit='GBP',raw_value='('+value+')',value=value,
        quote='\n'.join(page_lines(candidate_page())[4:6]))


def test_supported_llm_candidate_admitted_without_trusting_model_value() -> None:
    fact = admit_candidate(candidate(), (candidate_page(),), 'd', 'ZZ000003')
    assert fact.value == Decimal(100) and fact.page == 2
    assert fact.raw_value == '(100)' and fact.transformation == 'balance-sheet-creditor-deduction'
    assert fact.extraction_method == ExtractionMethod.LLM_OCR_TEXT
    assert admit_candidate(candidate().model_copy(update={'unit':'£'}),
        (candidate_page(),),'d','ZZ000003').value == fact.value


def test_invented_llm_source_token_rejected_but_quote_is_non_authoritative() -> None:
    # The persisted PDF/OCR token is authoritative. A model cannot invent a raw token,
    # while quote punctuation/spacing is explanatory provenance and need not match OCR.
    with pytest.raises(ParseError):
        admit_candidate(candidate('999'), (candidate_page(),), 'd', 'ZZ000003')
    fact = admit_candidate(candidate().model_copy(update={'quote':'vision transcription differs'}),
                           (candidate_page(),), 'd', 'ZZ000003')
    assert fact.value == Decimal(100) and fact.raw_value == '(100)'


@pytest.mark.parametrize('change', [
    {'scope':'GROUP'}, {'period_end':'2023-12-31'}, {'concept':'TOTAL_ASSETS'},
])
def test_candidate_source_identity_must_be_independently_supported(change: dict) -> None:
    with pytest.raises(ParseError):
        admit_candidate(candidate().model_copy(update=change), (candidate_page(),), 'd', 'ZZ000003')


@pytest.mark.parametrize('change', [
    {'period_end':'2025-06-30'}, {'currency':'USD'}, {'value':'999'},
])
def test_non_authoritative_model_metadata_does_not_override_grounded_source(change: dict) -> None:
    fact = admit_candidate(candidate().model_copy(update=change), (candidate_page(),), 'd', 'ZZ000003')
    assert fact.value == Decimal(100)
    assert fact.period.period_end.isoformat() == '2025-12-31'
    assert fact.currency == 'GBP' and fact.unit == 'GBP'


def test_assets_less_liabilities_is_never_total_assets() -> None:
    page = candidate_page()
    words = tuple(w.model_copy(update={'text':'Total assets less current liabilities'}) if w.y == 50
                  else w for w in page.words if not (w.y == 60 and w.x == 10))
    page = page.model_copy(update={'words':words})
    item = candidate().model_copy(update={'concept':'TOTAL_ASSETS','label':'Total assets less current liabilities',
        'quote':'\n'.join(page_lines(page)[4:6])})
    with pytest.raises(ParseError,match='Label does not support'):
        admit_candidate(item,(page,),'d','ZZ000003')


def test_company_component_column_cannot_take_group_amount_or_authorize_debt_total() -> None:
    words = [Word(x=10.0,y=10.0,right=200.0,text='Notes to accounts'),
             Word(x=260.0,y=20.0,right=330.0,text='Group'),
             Word(x=410.0,y=20.0,right=480.0,text='Company'),
             Word(x=10.0,y=40.0,right=200.0,text='GBP'),
             Word(x=10.0,y=50.0,right=200.0,text='Other loans')]
    for right,year,value in ((255,'2025','900'),(330,'2024','800'),(405,'2025','100'),(480,'2024','80')):
        words.extend((Word(x=float(right-25),y=30.0,right=float(right),text=year),
                      Word(x=float(right-25),y=50.0,right=float(right),text=value)))
    page = PageText(page=3,words=tuple(words),method=ExtractionMethod.PDF_OCR_DETERMINISTIC)
    item = candidate().model_copy(update={'page':3,'row_start':5,'row_end':5,'kind':'COMPONENT',
        'concept':'INTEREST_BEARING_DEBT','label':'Other loans','raw_value':'100','value':'100',
        'quote':page_lines(page)[4]})
    fact = admit_candidate(item,(candidate_page(),page),'d','ZZ000003')
    assert fact.value == Decimal(100) and fact.source_concept == 'pdf-component:other loans'
    repeated = page.model_copy(update={'words':tuple(w for w in page.words if w.y != 20) + tuple(
        Word(x=float(right-25),y=20.0,right=float(right),text=scope)
        for right,scope in ((255,'Group'),(330,'Group'),(405,'Company'),(480,'Company')))})
    assert admit_candidate(item,(candidate_page(),repeated),'d','ZZ000003').value == Decimal(100)
    with pytest.raises(ParseError):
        admit_candidate(item.model_copy(update={'raw_value':'900','value':'900'}),
                        (candidate_page(),page),'d','ZZ000003')
    with pytest.raises(ParseError):
        admit_candidate(item.model_copy(update={'kind':'DIRECT'}),(candidate_page(),page),'d','ZZ000003')
    maturity = page.model_copy(update={'words':page.words + (
        Word(x=10.0,y=15.0,right=500.0,text='Creditors: amounts falling due after more than one year'),)})
    qualified = item.model_copy(update={'row_start':6,'row_end':6,'label':'Other loans due after one year',
        'quote':page_lines(maturity)[5]})
    assert admit_candidate(qualified,(candidate_page(),maturity),'d','ZZ000003').source_label == 'other loans due after one year'
    wrong_maturity = maturity.model_copy(update={'words':tuple(w.model_copy(update={
        'text':'Creditors: amounts falling due within one year'}) if w.y == 15 else w for w in maturity.words)})
    with pytest.raises(ParseError):
        admit_candidate(qualified,(candidate_page(),wrong_maturity),'d','ZZ000003')


def test_missing_key_disables_optional_llm() -> None:
    fallback = OpenAIExtraction(None, 'explicit-test-model', config_version='test-v1')
    assert not fallback.enabled
    with pytest.raises(ParseError, match='disabled'):
        fallback.extract('synthetic evidence')


def test_official_sdk_request_uses_configured_model_and_structured_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from types import SimpleNamespace
    from pydantic import SecretStr
    import openai
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['max_retries'] == 0
            self.responses = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(model='configured-test-snapshot', status='completed',
                output_text=json.dumps({'candidates': [candidate().model_dump()], 'unresolved': False}))
    monkeypatch.setattr(openai, 'OpenAI', Client)
    result = json.loads(OpenAIExtraction(SecretStr('synthetic'), 'configured-test-model',
                                        config_version='test-v1').extract(json.dumps({'pages': [{'page': 2, 'rows': candidate().quote}]})))
    assert len(calls) == 1 and calls[0]['model'] == 'configured-test-model'
    assert calls[0]['text']['format']['strict'] is True and calls[0]['store'] is False
    assert result['returned_model'] == 'configured-test-snapshot'
    assert 'synthetic' not in json.dumps(result)

def test_semantic_llm_can_admit_verified_unlisted_accounting_label() -> None:
    words = [Word(x=10.0,y=float(y),right=220.0,text=text) for y,text in
             ((10,'Company balance sheet'),(20,'at 31 December 2025'),(30,'GBP'),
              (60,'Property held for resale'))]
    for y,right,text in ((40,310,'2025'),(40,410,'2024'),(60,310,'125'),(60,410,'80')):
        words.append(Word(x=float(right-30),y=float(y),right=float(right),text=text))
    page=PageText(page=3,words=tuple(words),method=ExtractionMethod.PDF_OCR_DETERMINISTIC)
    item=Candidate(page=3,row_start=5,row_end=5,concept='INVENTORY',kind='DIRECT',scope='COMPANY',
        support='SUPPORTED',label='Property held for resale',period_end='2025-12-31',currency='GBP',unit='GBP',
        raw_value='125',value='125',quote=page_lines(page)[4])
    fact=admit_candidate(item,(page,),'d','ZZ000003')
    assert fact.source_concept == 'llm-semantic:INVENTORY'
    from risk_intelligence.ingestion.accounts.mapping import default_registry
    mapped=default_registry().map(fact,company_id='c',company_number='ZZ000003',source_id='s',processing_run_id='r')
    assert mapped is not None and mapped.canonical_concept == 'INVENTORY' and mapped.value_numeric == Decimal(125)


def test_semantic_locator_recovers_from_vision_ocr_row_number_drift() -> None:
    drifted = candidate().model_copy(update={'row_start': 999, 'row_end': 999})
    fact = admit_candidate(drifted, (candidate_page(),), 'd', 'ZZ000003')
    assert fact.value == Decimal(100) and fact.raw_value == '(100)'


def test_four_column_year_major_layout_resolves_company_column() -> None:
    words = [Word(x=10.0,y=10.0,right=200.0,text='Company balance sheet'),
             Word(x=10.0,y=15.0,right=200.0,text='at 31 December 2025'),
             Word(x=10.0,y=20.0,right=200.0,text='GBP'),
             Word(x=250.0,y=25.0,right=275.0,text='Group'),
             Word(x=350.0,y=25.0,right=375.0,text='Company'),
             Word(x=250.0,y=30.0,right=275.0,text='2025'),
             Word(x=350.0,y=30.0,right=375.0,text='2025'),
             Word(x=450.0,y=30.0,right=475.0,text='2024'),
             Word(x=550.0,y=30.0,right=575.0,text='2024'),
             Word(x=10.0,y=50.0,right=180.0,text='Stocks 7'),
             Word(x=250.0,y=50.0,right=275.0,text='9,000'),
             Word(x=350.0,y=50.0,right=375.0,text='4,048,511'),
             Word(x=450.0,y=50.0,right=475.0,text='8,000'),
             Word(x=550.0,y=50.0,right=575.0,text='3,000')]
    page = PageText(page=5,words=tuple(words),method=ExtractionMethod.PDF_OCR_DETERMINISTIC)
    item = candidate().model_copy(update={'page':5,'row_start':999,'row_end':999,
        'concept':'INVENTORY','label':'Stocks 7','raw_value':'4,048,511','value':'4,048,511',
        'period_end':'2025','quote':'vision row'})
    fact = admit_candidate(item,(page,),'d','ZZ000003')
    assert fact.value == Decimal(4048511)
