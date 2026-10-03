"""Foundation PDF route: filed PDF -> OpenAI multimodal -> semantic facts; no OCR gate."""
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from risk_intelligence.domain.enums import ProcessingStatus, RetrievalStatus, SourceType, TriggerType
from risk_intelligence.domain.evidence import Company, Document, RawEvidence, Source
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.ingestion.accounts.llm import Candidate, PdfSemanticCandidate
from risk_intelligence.ingestion.accounts.pdf_semantic import admit_pdf_candidate
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import open_sqlite
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum, object_key


def candidate(concept='CURRENT_LIABILITIES', value='(10,583,194)', *, kind='DIRECT', label=None, page=1):
    labels = {
        'CURRENT_LIABILITIES':'Creditors: amounts falling due within one year',
        'NET_ASSETS':'Net assets','CURRENT_ASSETS':'Current assets','INVENTORY':'Stocks','TOTAL_ASSETS':'Total assets'}
    return Candidate(page=page,row_start=1,row_end=1,concept=concept,kind=kind,scope='COMPANY',support='SUPPORTED',
        label=label or labels[concept],period_end='2025-12-31',currency='GBP',unit='GBP',raw_value=value,
        value=value.strip('()').replace(',',''),quote=f"{label or labels[concept]} {value}")


def test_direct_pdf_admission_uses_substance_not_ocr_locator():
    fact = admit_pdf_candidate(candidate(), document_id='d', company_number='ZZ000003',
        rendered_pages=frozenset({1,2}), requested=frozenset({'CURRENT_LIABILITIES'}), requested_reporting_year=2025)
    assert fact.value == Decimal('10583194')
    assert fact.source_concept == 'llm-semantic:CURRENT_LIABILITIES'
    assert fact.source_scope == 'COMPANY'
    assert fact.transformation.startswith('openai-pdf-semantic')


def test_total_assets_less_current_liabilities_stays_bridge():
    c = candidate('TOTAL_ASSETS','1,649,700',kind='COMPONENT',label='Total assets less current liabilities')
    fact = admit_pdf_candidate(c, document_id='d', company_number='ZZ000003', rendered_pages=frozenset({1}),
        requested=frozenset({'TOTAL_ASSETS'}), requested_reporting_year=2025)
    assert fact.source_concept == 'pdf-component:total assets less current liabilities'
    assert fact.value == Decimal('1649700')


def test_group_or_comparative_semantics_fail_closed():
    with pytest.raises(Exception):
        admit_pdf_candidate(candidate().model_copy(update={'scope':'GROUP'}), document_id='d', company_number='ZZ000003',
            rendered_pages=frozenset({1}), requested=frozenset({'CURRENT_LIABILITIES'}), requested_reporting_year=2025)


def test_year_only_candidate_inherits_authoritative_ixbrl_period():
    c = candidate('INVENTORY', '4,048,511').model_copy(update={'period_end':'2025'})
    fact = admit_pdf_candidate(c, document_id='d', company_number='ZZ000003',
        rendered_pages=frozenset({1}), requested=frozenset({'INVENTORY'}), requested_reporting_year=2025,
        authoritative_period_end=date(2025, 9, 30))
    assert fact.value == Decimal('4048511')
    assert fact.period.period_end == date(2025, 9, 30)

def test_other_displayed_year_is_retained_instead_of_rejected():
    c = candidate('INVENTORY', '4,048,511').model_copy(update={'period_end':'2024'})
    fact = admit_pdf_candidate(c, document_id='d', company_number='ZZ000003',
        rendered_pages=frozenset({1}), requested=frozenset({'INVENTORY'}), requested_reporting_year=2025,
        authoritative_period_end=date(2025, 9, 30))
    assert fact.period.period_end == date(2024, 12, 31)
    assert fact.value == Decimal('4048511')


class Model:
    enabled = True
    model = 'configured-test-model'
    config_version = 'test-direct-pdf-v1'
    def __init__(self, candidates): self.candidates, self.calls = candidates, []
    def extract_pdf_file(self, evidence, pdf):
        import pymupdf
        with pymupdf.open(stream=pdf, filetype='pdf') as document:
            self.calls.append((json.loads(evidence), tuple(range(1,len(document)+1))))
        return json.dumps({'status':'completed','output':json.dumps({'candidates':[
            PdfSemanticCandidate.model_validate(c.model_dump(exclude={'row_start','row_end'})).model_dump()
            for c in self.candidates]})}).encode()


def _pdf_bytes(pages=1):
    import pymupdf
    doc=pymupdf.open(); page=doc.new_page(); page.insert_text((72,72),'Company balance sheet at 31 December 2025')
    page.insert_text((72,100),'Current assets 11,381,830  Current liabilities 10,583,194  Stocks 3,273,856')
    for _ in range(pages - 1): doc.new_page()
    data=doc.tobytes(); doc.close(); return data


@pytest.fixture
def direct_context(tmp_path: Path, request):
    now=datetime(2026,9,29,tzinfo=UTC); content=_pdf_bytes(getattr(request, 'param', 1))
    with open_sqlite() as db:
        migrate(db)
        SqlCompanyRepository(db).save(Company(company_id='c',company_number='ZZ000003',company_name='SYNTHETIC'))
        SqlAssessmentRepository(db).save_processing_run(ProcessingRun(processing_run_id='r1',company_id='c',
            company_number='ZZ000003',started_at=now,status=ProcessingStatus.RUNNING,current_stage='M3',
            trigger_type=TriggerType.LIVE,app_version='test'))
        db.execute('INSERT INTO accounts_run VALUES (?,?,?,?,?)',('r1','2026-09-29',5,'financial-concepts-v4','RUNNING'))
        source=Source(source_id='s',company_id='c',company_number='ZZ000003',source_type=SourceType.COMPANIES_HOUSE_PDF,
            source_name='Synthetic',source_identifier='test',retrieved_at=now,retrieval_status=RetrievalStatus.SUCCESS,
            processing_run_id='r1',checksum=checksum(content))
        key=object_key(source,checksum(content),'application/pdf')
        doc=Document(document_id='d',company_id='c',company_number='ZZ000003',source_id='s',document_type='ACCOUNTS',
            representation_type='application/pdf',object_path=key,checksum=checksum(content))
        raw=RawEvidence(raw_evidence_id='raw',source_id='s',document_id='d',object_path=key,checksum=checksum(content),
            retrieved_at=now,processing_run_id='r1',media_type='application/pdf')
        model=Model([candidate('NET_ASSETS','1,083,960'), candidate('CURRENT_ASSETS','11,381,830'),
            candidate('CURRENT_LIABILITIES','(10,583,194)'), candidate('INVENTORY','3,273,856'),
            candidate('TOTAL_ASSETS','1,649,700',kind='COMPONENT',label='Total assets less current liabilities')])
        service=AccountsIngestion(db,LocalStorage(tmp_path/'raw'),None,llm=model)
        service.evidence.save(source,raw,content,doc)
        yield service,raw,model


def test_pdf_service_calls_openai_directly_without_ocr_and_persists_derivation(direct_context):
    service,raw,model=direct_context
    result,_=service._extract(raw,'r1','ZZ000003',reporting_year=2025)
    assert len(model.calls)==1
    assert model.calls[0][0]['unresolved_concepts']==['NET_ASSETS','TOTAL_ASSETS','CURRENT_ASSETS','CURRENT_LIABILITIES','INVENTORY']
    assert model.calls[0][1]==(1,)
    assert len(result.facts)==5
    assert all(f.transformation and f.transformation.startswith('openai-pdf-semantic') for f in result.facts)
    ids=service._save_facts(raw,result)
    rows=service.database.query("SELECT canonical_concept,value_numeric,extraction_method FROM fact WHERE canonical_concept IN ('CURRENT_LIABILITIES','TOTAL_ASSETS')")
    got={r['canonical_concept']:(str(r['value_numeric']),r['extraction_method']) for r in rows}
    assert got['CURRENT_LIABILITIES'][0]=='10583194'
    assert got['TOTAL_ASSETS'][0]=='12232894'
    assert got['TOTAL_ASSETS'][1]=='DERIVED'
    assert ids

# Compatibility fixture for persistence/scope tests. These tests exercise stored source
# semantics directly and do not invoke the retired OCR extraction route.
from risk_intelligence.domain.enums import ExtractionMethod
from risk_intelligence.ingestion.accounts.pdf import PageText, Word

@pytest.fixture
def fallback_context(tmp_path: Path):
    words = [Word(x=10.0,y=float(y),right=220.0,text=text) for y,text in
        ((10,'Company balance sheet'),(20,'at 31 December 2025'),(30,'GBP'),
         (50,'Creditors: amounts falling due'),(60,'within one year'),(80,'Net assets'))]
    for y,right,text in ((40,310,'2025'),(40,410,'2024'),(60,310,'(100)'),(60,410,'(80)'),
                          (80,310,'500'),(80,410,'400')):
        words.append(Word(x=float(right-30),y=float(y),right=float(right),text=text))
    page = PageText(page=2,words=tuple(words),method=ExtractionMethod.PDF_OCR_DETERMINISTIC)
    now = datetime(2026,9,29,tzinfo=UTC); content=b'%PDF-synthetic-persistence-fixture'
    with open_sqlite() as db:
        migrate(db)
        SqlCompanyRepository(db).save(Company(company_id='c',company_number='ZZ000003',company_name='SYNTHETIC'))
        for run_id in ('r1','r2'):
            SqlAssessmentRepository(db).save_processing_run(ProcessingRun(processing_run_id=run_id,company_id='c',
                company_number='ZZ000003',started_at=now,status=ProcessingStatus.RUNNING,current_stage='M3',
                trigger_type=TriggerType.LIVE,app_version='test'))
            db.execute('INSERT INTO accounts_run VALUES (?,?,?,?,?)',(run_id,'2026-09-29',5,'financial-concepts-v4','RUNNING'))
        source=Source(source_id='s',company_id='c',company_number='ZZ000003',source_type=SourceType.COMPANIES_HOUSE_PDF,
            source_name='Synthetic',source_identifier='test',retrieved_at=now,retrieval_status=RetrievalStatus.SUCCESS,
            processing_run_id='r1',checksum=checksum(content))
        key=object_key(source,checksum(content),'application/pdf')
        doc=Document(document_id='d',company_id='c',company_number='ZZ000003',source_id='s',document_type='ACCOUNTS',
            representation_type='application/pdf',object_path=key,checksum=checksum(content))
        raw=RawEvidence(raw_evidence_id='raw',source_id='s',document_id='d',object_path=key,checksum=checksum(content),
            retrieved_at=now,processing_run_id='r1',media_type='application/pdf')
        service=AccountsIngestion(db,LocalStorage(tmp_path/'raw'),None,ocr_version='test-ocr')
        service.evidence.save(source,raw,content,doc)
        yield service,raw,page

def test_candidate_without_printed_year_inherits_requested_year_without_date_gate():
    c = candidate('INVENTORY', '4,048,511').model_copy(update={'period_end':''})
    fact = admit_pdf_candidate(c, document_id='d', company_number='ZZ000003',
        rendered_pages=frozenset({1}), requested=frozenset({'INVENTORY'}), requested_reporting_year=2023,
        authoritative_period_end=date(2023, 9, 30))
    assert fact.value == Decimal('4048511')
    assert fact.period.period_end.year == 2023


def test_explicit_target_year_wins_over_comparative_year_rule():
    c = candidate('CURRENT_ASSETS', '7,091,772').model_copy(update={'period_end':'2023'})
    fact = admit_pdf_candidate(c, document_id='d', company_number='ZZ000003',
        rendered_pages=frozenset({1}), requested=frozenset({'CURRENT_ASSETS'}), requested_reporting_year=2023,
        authoritative_period_end=date(2023, 9, 30))
    assert fact.period.period_end.year == 2023


def test_empty_semantic_response_persists_not_disclosed_reasons(direct_context):
    service, raw, model = direct_context
    model.candidates = []
    result, _ = service._extract(raw, 'r1', 'ZZ000003', reporting_year=2025)
    service._save_facts(raw, result)
    rows = service.database.query("SELECT f.canonical_concept,f.availability_status,r.reason_code FROM fact f "
        "JOIN financial_fact_missing_reason r ON r.fact_id=f.fact_id WHERE f.canonical_concept='INVENTORY'")
    assert rows == [{'canonical_concept':'INVENTORY', 'availability_status':'NOT_DISCLOSED',
                     'reason_code':'NOT_FOUND_IN_SELECTED_ACCOUNTS'}]
    assert not service.database.query('PRAGMA foreign_key_check')


def test_provider_failure_persists_extraction_failed_without_stopping(direct_context):
    from risk_intelligence.ingestion.companies_house.client import ParseError
    service, raw, model = direct_context
    def fail(*args):
        raise ParseError('Synthetic provider failure')
    model.extract_pdf_file = fail
    result, _ = service._extract(raw, 'r1', 'ZZ000003', reporting_year=2025)
    service._save_facts(raw, result)
    rows = service.database.query("SELECT f.availability_status,r.reason_code FROM fact f "
        "JOIN financial_fact_missing_reason r ON r.fact_id=f.fact_id WHERE f.canonical_concept='INVENTORY'")
    assert rows == [{'availability_status':'EXTRACTION_FAILED','reason_code':'EXTRACTION_FAILED'}]


@pytest.mark.parametrize('direct_context', [35], indirect=True)
def test_complete_35_page_pdf_reaches_model_including_last_page_note(direct_context):
    service, raw, model = direct_context
    model.candidates = [candidate('INVENTORY', '3,273,856', page=35)]
    result, _ = service._extract(raw, 'r1', 'ZZ000003', reporting_year=2025)
    assert model.calls[0][1] == tuple(range(1, 36))
    assert result.facts[0].page == 35 and result.facts[0].value == 3273856


def test_pdf_service_selects_closest_supported_company_column(direct_context):
    service, raw, model = direct_context
    model.candidates = [candidate('INVENTORY', '111').model_copy(update={'period_end':'2023'}),
        candidate('INVENTORY', '222').model_copy(update={'period_end':'2024'}),
        candidate('INVENTORY', '999').model_copy(update={'period_end':'2025', 'scope':'GROUP'})]
    result, _ = service._extract(raw, 'r1', 'ZZ000003', reporting_year=2025)
    assert len(result.facts) == 1
    assert result.facts[0].value == 222 and result.periods[0].period_end.year == 2024
