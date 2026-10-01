"""Partial deterministic extraction must not bypass bounded, cached fallback."""

from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from risk_intelligence.domain.enums import ExtractionMethod, ProcessingStatus, RetrievalStatus, SourceType, TriggerType
from risk_intelligence.domain.evidence import Company, Document, RawEvidence, Source
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.ingestion.accounts.llm import Candidate
from risk_intelligence.ingestion.accounts.fallback import page_lines
from risk_intelligence.ingestion.accounts.pdf import PageText, Word, extract_pdf, PARSER_VERSION
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.companies_house.client import ParseError
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import open_sqlite
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum, object_key


class Model:
    """Offline provider substitute; cache/orchestration/storage remain real."""

    enabled = True
    model = 'configured-test-model'
    config_version = 'test-v2'

    def __init__(self, candidates: list[Candidate], *, fails: bool = False) -> None:
        self.candidates, self.fails, self.calls = candidates, fails, []

    def extract(self, evidence: str) -> bytes:
        self.calls.append(json.loads(evidence))
        if self.fails:
            raise ParseError('Synthetic unavailable provider')
        return json.dumps({'status':'completed','output':json.dumps({
            'candidates':[c.model_dump() for c in self.candidates], 'unresolved':not self.candidates})}).encode()


@pytest.fixture
def fallback_context(tmp_path: Path):
    words = [Word(x=10.0,y=float(y),right=220.0,text=text) for y,text in
        ((10,'Company balance sheet'),(20,'at 31 December 2025'),(30,'GBP'),
         (50,'Creditors: amounts falling due'),(60,'within one year'),(80,'Net assets'))]
    for y,right,text in ((40,310,'2025'),(40,410,'2024'),(60,310,'(100)'),(60,410,'(80)'),
                          (80,310,'500'),(80,410,'400')):
        words.append(Word(x=float(right-30),y=float(y),right=float(right),text=text))
    page = PageText(page=2,words=tuple(words),method=ExtractionMethod.PDF_OCR_DETERMINISTIC)
    now = datetime(2026,9,29,tzinfo=UTC)
    with open_sqlite() as db:
        migrate(db)
        SqlCompanyRepository(db).save(Company(company_id='c',company_number='ZZ000003',company_name='SYNTHETIC'))
        for run_id in ('r1','r2'):
            SqlAssessmentRepository(db).save_processing_run(ProcessingRun(processing_run_id=run_id,company_id='c',
                company_number='ZZ000003',started_at=now,status=ProcessingStatus.RUNNING,current_stage='M3',
                trigger_type=TriggerType.LIVE,app_version='test'))
            db.execute('INSERT INTO accounts_run VALUES (?,?,?,?,?)',(run_id,'2026-09-29',5,'financial-concepts-v1','RUNNING'))
        content = b'%PDF-synthetic-verified-test-evidence'
        source = Source(source_id='s',company_id='c',company_number='ZZ000003',source_type=SourceType.COMPANIES_HOUSE_PDF,
            source_name='Synthetic',source_identifier='test',retrieved_at=now,retrieval_status=RetrievalStatus.SUCCESS,
            processing_run_id='r1',checksum=checksum(content))
        key = object_key(source,checksum(content),'application/pdf')
        doc = Document(document_id='d',company_id='c',company_number='ZZ000003',source_id='s',document_type='ACCOUNTS',
            representation_type='application/pdf',object_path=key,checksum=checksum(content))
        raw = RawEvidence(raw_evidence_id='raw',source_id='s',document_id='d',object_path=key,checksum=checksum(content),
            retrieved_at=now,processing_run_id='r1',media_type='application/pdf')
        service = AccountsIngestion(db,LocalStorage(tmp_path/'raw'),None,ocr_version='test-ocr')
        service.evidence.save(source,raw,content,doc)
        service.cache.run(raw,'r1','OCR','test-ocr',{'dpi':200,'language':'eng','pymupdf':'1.28.2'},
                          lambda _: json.dumps([page.model_dump(mode='json')]).encode())
        yield service, raw, page


def supported(page: PageText) -> Candidate:
    return Candidate(page=2,row_start=5,row_end=6,concept='CURRENT_LIABILITIES',kind='DIRECT',scope='COMPANY',
        support='SUPPORTED',label='Creditors: amounts falling due within one year',period_end='2025-12-31',
        currency='GBP',unit='GBP',raw_value='(100)',value='100',quote='\n'.join(page_lines(page)[4:6]))


def test_partial_deterministic_triggers_verified_fallback_and_reuses_identical_result(fallback_context) -> None:
    service,raw,page = fallback_context
    service.llm = model = Model([supported(page)])
    first,_ = service._extract(raw,'r1','ZZ000003')
    assert len(model.calls) == 1
    assert 'CURRENT_LIABILITIES' in model.calls[0]['unresolved_concepts']
    assert 'NET_ASSETS' not in model.calls[0]['unresolved_concepts']
    assert [p['page'] for p in model.calls[0]['pages']] == [2]
    assert len(first.facts) == 3  # Two deterministic facts plus admitted fallback.
    assert first.facts[-1].value == Decimal(100)
    assert first.facts[-1].statement_context == 'Company balance sheet'
    assert first.facts[-1].source_scope == 'COMPANY'
    assert first.fallback.decisions[0].status == 'AVAILABLE'
    service._save_facts(raw,first)
    before = service.database.query('SELECT count(*) AS n FROM fact')[0]['n']
    second,_ = service._extract(raw,'r2','ZZ000003')
    service._save_facts(raw,second)
    assert second == first and len(model.calls) == 1
    assert service.database.query('SELECT count(*) AS n FROM fact')[0]['n'] == before


def test_located_heading_roundtrip_reaches_m4_without_strength_uplift(fallback_context):
    from risk_intelligence.persistence.accounts_repository import AccountsRepository
    from risk_intelligence.validation.financial_service import FinancialValidationService
    from datetime import date

    service, raw, page = fallback_context
    service.llm = Model([supported(page)])
    extraction, _ = service._extract(raw, 'r1', 'ZZ000003')
    ids = service._save_facts(raw, extraction)
    repository = AccountsRepository(service.database)
    fact = next(repository.canonical.get(identity) for identity in ids
                if repository.canonical.get(identity).canonical_concept == 'CURRENT_LIABILITIES'
                and repository.canonical.get(identity).value_numeric is not None)
    source = repository.get_observation_lineage(fact.financial_fact_id)[1][0]
    assert source.statement_context == 'Company balance sheet' and source.source_scope == 'COMPANY'
    result = FinancialValidationService(service.database).evaluate_and_persist(
        validated_fact_id='validated-liability', fact_id=fact.financial_fact_id,
        assessment_date=date(2026,9,29), analytical_scope='COMPANY')
    assert result.assessment.validation.admissible
    assert result.assessment.calculation.reliability_r == Decimal('.8075')


def test_current_m3_publishes_derived_sql_proof_and_m4_requires_it(fallback_context, monkeypatch):
    from datetime import date
    from tests.m3.test_asset_side import inspected, derivations
    from risk_intelligence.persistence.accounts_repository import AccountsRepository
    from risk_intelligence.persistence.connection import IntegrityError
    from risk_intelligence.validation.financial_service import FinancialValidationService

    service, raw, _ = fallback_context
    result = inspected()
    result = result.model_copy(update={'interpretations': tuple(derivations(result))})
    ids = service._save_facts(raw, result)
    repository = AccountsRepository(service.database)
    fact = next(repository.canonical.get(identity) for identity in ids
                if repository.canonical.get(identity).canonical_concept == 'TOTAL_ASSETS')
    assert repository.get_derivation_proof(fact.financial_fact_id) is not None
    validator = FinancialValidationService(service.database)
    assessment = validator.evaluate(fact_id=fact.financial_fact_id, assessment_date=date(2026,9,29), analytical_scope='COMPANY')
    assert assessment.assessment.validation.admissible
    monkeypatch.setattr(validator.accounts, 'get_derivation_proof', lambda identity: None)
    with pytest.raises(IntegrityError, match='no completeness proof'):
        validator.evaluate(fact_id=fact.financial_fact_id, assessment_date=date(2026,9,29), analytical_scope='COMPANY')


@pytest.mark.parametrize('change',[{'raw_value':'(999)','value':'999'},{'scope':'GROUP'},
                                  {'concept':'TOTAL_ASSETS'}])
def test_rejected_candidate_preserves_deterministic_facts_and_typed_failure(fallback_context,change) -> None:
    service,raw,page = fallback_context
    service.llm = Model([supported(page).model_copy(update=change)])
    result,_ = service._extract(raw,'r1','ZZ000003')
    assert len(result.facts) == 2 and result.fallback.decisions[0].status == 'VALIDATION_FAILED'
    service._save_facts(raw,result)
    concept = change.get('concept','CURRENT_LIABILITIES')
    row = service.database.query('SELECT value_numeric,availability_status FROM fact WHERE canonical_concept=? '
                                 'AND period_end=?',(concept,'2025-12-31'))[0]
    assert row == {'value_numeric':None,'availability_status':'VALIDATION_FAILED'}


@pytest.mark.parametrize('mode',['unresolved','disabled','provider_failure'])
def test_unavailable_or_unresolved_fallback_keeps_valid_facts_and_nulls(fallback_context,mode) -> None:
    service,raw,page = fallback_context
    service.llm = model = Model([],fails=mode=='provider_failure')
    if mode == 'disabled':
        model.enabled = False
    result,_ = service._extract(raw,'r1','ZZ000003')
    assert len(result.facts) == 2
    assert len(model.calls) == (0 if mode == 'disabled' else 1)
    service._save_facts(raw,result)
    row = service.database.query("SELECT value_numeric,availability_status FROM fact WHERE canonical_concept='CURRENT_LIABILITIES' AND period_end='2025-12-31'")[0]
    assert row == {'value_numeric':None,'availability_status':'EXTRACTION_FAILED'}
    service._extract(raw,'r2','ZZ000003')
    assert len(model.calls) == (0 if mode == 'disabled' else 1)


def test_all_required_deterministic_inputs_available_avoids_model(fallback_context) -> None:
    service,raw,page = fallback_context
    result = extract_pdf((page,),'d','ZZ000003')
    labels = ('current assets','current liabilities','inventory','net assets','total assets','total interest-bearing debt')
    facts = tuple(fact.model_copy(update={'source_fact_id':f'{i}-{j}', 'source_concept':'pdf-label:'+label})
                  for i,label in enumerate(labels) for j,fact in enumerate(result.facts))
    result = result.model_copy(update={'facts':facts,'complete':True})
    service.cache.run(raw,'r1','PARSE',PARSER_VERSION,{'ocr_version':'test-ocr'},
                      lambda _:result.model_dump_json().encode())
    service.llm = model = Model([supported(page)])
    actual,_ = service._extract(raw,'r1','ZZ000003')
    assert not model.calls and actual.facts == result.facts


def test_failed_component_is_not_a_failed_canonical_total_candidate(fallback_context) -> None:
    service,raw,page = fallback_context
    service.llm = Model([supported(page).model_copy(update={'kind':'COMPONENT','concept':'TOTAL_ASSETS'})])
    result,_ = service._extract(raw,'r1','ZZ000003')
    assert result.fallback.decisions[0].status == 'VALIDATION_FAILED'
    service._save_facts(raw,result)
    row = service.database.query("SELECT value_numeric,availability_status FROM fact WHERE canonical_concept='TOTAL_ASSETS' AND period_end='2025-12-31'")[0]
    assert row == {'value_numeric':None,'availability_status':'EXTRACTION_FAILED'}


def test_derived_asset_and_debt_lineage_persist_with_rule_and_order(fallback_context) -> None:
    from test_asset_side import inspected
    from risk_intelligence.ingestion.accounts.interpretation import VERSION, deterministic_proposals
    from risk_intelligence.ingestion.accounts.derivation import DERIVATION_VERSION, COMPLETENESS_QUOTE
    from risk_intelligence.ingestion.accounts.models import DebtSchedule

    service,raw,_ = fallback_context
    result = inspected()
    result = result.model_copy(update={'interpretations':deterministic_proposals(result,service.registry)})
    service._save_facts(raw,result)
    rows = service.database.query("SELECT l.* FROM financial_observation_lineage l JOIN fact f ON f.fact_id=l.fact_id WHERE f.canonical_concept='TOTAL_ASSETS'")
    assert len(rows) == 2
    assert all(row['origin']=='DERIVED' and row['derivation_version']==VERSION for row in rows)
    for row,proof in zip(rows,result.proofs,strict=True):
        components = service.database.query('SELECT source_fact_id FROM financial_observation_component WHERE fact_id=? ORDER BY position',(row['fact_id'],))
        assert tuple(item['source_fact_id'] for item in components) == proof.source_fact_ids
        assert proof.proof_id in service.repository.canonical.get(row['fact_id']).evidence_ids

        persisted_proof = service.database.query(
            'SELECT proof_id,document_id,target_concept,relationship,page,row_start,row_end,evidence_text '
            'FROM financial_derivation_proof WHERE fact_id=?',
            (row['fact_id'],))
        assert persisted_proof == [{
            'proof_id': proof.proof_id,
            'document_id': proof.document_id,
            'target_concept': proof.target,
            'relationship': proof.relationship,
            'page': proof.page,
            'row_start': proof.row_start,
            'row_end': proof.row_end,
            'evidence_text': proof.evidence_text,
        }]

        persisted_checks = service.database.query(
            'SELECT source_fact_id FROM financial_derivation_cross_check '
            'WHERE fact_id=? ORDER BY position',
            (row['fact_id'],))
        assert tuple(item['source_fact_id'] for item in persisted_checks) == proof.cross_check_ids

        restored_proof = service.repository.get_derivation_proof(row['fact_id'])
        assert restored_proof == proof

        restored_lineage = service.repository.get_observation_lineage(row['fact_id'])
        assert restored_lineage is not None
        lineage, restored_components = restored_lineage
        assert lineage['origin'] == 'DERIVED'
        assert lineage['mapping_version'] == service.registry.version
        assert lineage['derivation_version'] == VERSION
        assert tuple(
            component.source_fact_id for component in restored_components
        ) == proof.source_fact_ids
    base = result.facts[0]
    debt = tuple(base.model_copy(update={'source_fact_id':f'debt-{i}','evidence_id':f'debt-e-{i}',
        'source_concept':'pdf-component:'+label,'source_label':label,'value':Decimal(value),'raw_value':value})
        for i,(label,value) in enumerate((('bank loans','100'),('finance lease liabilities','20'))))
    schedule = DebtSchedule(source_fact_ids=tuple(f.source_fact_id for f in debt),completeness_quote=COMPLETENESS_QUOTE,page=2)
    partial = result.model_copy(update={'facts':debt,'proofs':(),'interpretations':(),'debt_schedules':()})
    ids = service._save_facts(raw,partial)
    assert all(service.repository.canonical.get(i).value_numeric is None for i in ids)
    service._save_facts(raw,partial.model_copy(update={'debt_schedules':(schedule,)}))
    row = service.database.query('SELECT * FROM financial_observation_lineage WHERE derivation_version=?',(DERIVATION_VERSION,))[0]
    assert service.repository.canonical.get(row['fact_id']).value_numeric == Decimal('120')
    assert not service.database.query('PRAGMA foreign_key_check')
