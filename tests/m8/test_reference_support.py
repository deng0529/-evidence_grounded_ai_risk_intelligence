"""Source audits, evidence downloads and bounded expert prose do not alter beliefs."""
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from risk_intelligence.services.saved_reference_beliefs import calculate_saved_reference_beliefs, transform_saved_value
from risk_intelligence.services.reference_support import source_reliability, evidence_rows, read_supporting_evidence, reference_rationale
from risk_intelligence.services.reference_narrative import validate_commentary, generate_reference_commentary
from risk_intelligence.services.narrative import NarrativeUnavailable
from risk_intelligence.persistence.connection import IntegrityError
from risk_intelligence.storage.objects import EvidenceIntegrityError
from tests.m8.test_leaf_belief_test import seed
from tests.m2.conftest import NUMBER


@pytest.fixture
def supported_ixbrl(ixbrl):
    content = ixbrl.replace(b'urn:synthetic:accounts:v1', b'http://xbrl.frc.org.uk/fr/2025-01-01/core')
    content = content.replace(b'test:NetAssets', b'test:NetAssetsLiabilities')
    extra = b'<ix:nonFraction name="test:TotalAssets" contextRef="current" unitRef="gbp">200000</ix:nonFraction><ix:nonFraction name="test:CurrentAssets" contextRef="current" unitRef="gbp">80</ix:nonFraction><ix:nonFraction name="test:CurrentLiabilities" contextRef="current" unitRef="gbp">100</ix:nonFraction>'
    return content.replace(b'</html>',extra+b'</html>')


def test_independent_reliability_has_real_factors_and_does_not_mutate_memberships(database,storage,api,supported_ixbrl):
    seed(database,storage,api,supported_ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    before=view.beliefs
    audit=source_reliability(database,view)
    assert not audit.error and len(audit.values)==6
    assert audit.values['G1.1']==Decimal('0.9702')
    assert 'S=0.98' in audit.explanations['G1.1']
    assert view.beliefs==before
    for b in view.beliefs:
        assert b.unknown==(1 if b.value is None else 0)
    assert source_reliability(database,view)==audit
    assert len(database.query('SELECT * FROM reference_source_audit'))==1
    assert len(database.query('SELECT * FROM saved_reference_belief'))==1


def test_reliability_lineage_failure_is_independent_of_reference_results(database,storage,api,supported_ixbrl,monkeypatch):
    seed(database,storage,api,supported_ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    import risk_intelligence.services.reference_support as support
    def fail(*args,**kwargs): raise IntegrityError('test failure')
    monkeypatch.setattr(support,'calculate_saved_leaf_beliefs',fail)
    audit=source_reliability(database,view)
    assert audit.error and not audit.values
    assert all(b.unknown==0 for b in view.beliefs if b.value is not None)


def test_recorded_ixbrl_and_api_locators_download_only_selected_evidence(database,storage,api,supported_ixbrl):
    seed(database,storage,api,supported_ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    rows=evidence_rows(database,view,'F1.1')
    assert rows and all(row['locator_kind']=='IXBRL_FACT' for row in rows)
    assert all(row['page'] is None for row in rows)
    assert all(row['concept'] and row['context_id'] for row in rows)
    assert rows[0]['canonical_concept']=='NET_ASSETS'
    content,mime,filename=read_supporting_evidence(database,view,rows[0]['raw_evidence_id'],storage)
    assert mime=='application/xhtml+xml' and content.startswith(b'<html') and filename.endswith('.xhtml')
    api_rows=evidence_rows(database,view,'G2.2')
    assert api_rows and all(row['json_path'] and row['page'] is None for row in api_rows)
    with pytest.raises(IntegrityError,match='not supporting'):
        read_supporting_evidence(database,view,'unrelated',storage)
    bad=SimpleNamespace(read=lambda path:b'corrupt')
    with pytest.raises(EvidenceIntegrityError):
        read_supporting_evidence(database,view,rows[0]['raw_evidence_id'],bad)


@pytest.mark.parametrize('payload',[
    {'paragraph':'Low coverage indicates a small buffer.','evidence_ids':['other']},
    {'paragraph':'The ratio is 0.3 on page 99.','evidence_ids':['e1']},
    {'paragraph':'Small buffer.','evidence_ids':['e1','e1']},
])
def test_ai_rejects_unrecorded_citations_and_numeric_claims(payload):
    with pytest.raises(NarrativeUnavailable):
        validate_commentary(json.dumps(payload),[{'evidence_id':'e1'}])


def test_ai_call_uses_expert_prompt_and_persistent_cache(database,storage,api,supported_ixbrl,monkeypatch):
    seed(database,storage,api,supported_ixbrl)
    view=calculate_saved_reference_beliefs(database,NUMBER)
    evidence=evidence_rows(database,view,'F1.1')
    belief=next(b for b in view.beliefs if b.code=='F1.1')
    calls=[]
    response=SimpleNamespace(status='completed',output_text=json.dumps({'paragraph':'A negative equity buffer indicates liabilities exceed assets. The supplied snapshot does not establish the historical cause.', 'evidence_ids':[evidence[0]['evidence_id']]}))
    class Client:
        def __init__(self,**kwargs): self.responses=self
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def create(self,**kwargs): calls.append(kwargs); return response
    import openai
    monkeypatch.setattr(openai,'OpenAI',Client)
    first=generate_reference_commentary(database,view,belief,evidence,SecretStr('test-only'),'fake-model')
    second=generate_reference_commentary(database,view,belief,evidence,SecretStr('test-only'),'fake-model')
    assert first==second and len(calls)==1
    assert 'financial risk expert' in calls[0]['instructions']
    assert calls[0]['store'] is False
    assert 'test-only' not in calls[0]['input'] and 'object_path' not in calls[0]['input']
    assert len(database.query('SELECT * FROM reference_narrative'))==1


from tests.m3.test_fallback_flow import direct_context  # noqa: F401


def test_pdf_derived_total_preserves_operand_pages_and_download_bytes(direct_context):
    from datetime import date
    from risk_intelligence.services.data_foundation import FoundationFact, FoundationView
    from risk_intelligence.services.saved_reference_beliefs import ReferenceView
    service,raw,_=direct_context
    extracted,_=service._extract(raw,'r1','ZZ000003',reporting_year=2025)
    ids=service._save_facts(raw,extracted)
    db=service.database
    # Resolve the canonical records using the same repository as the read-only UI.
    from risk_intelligence.persistence.accounts_repository import AccountsRepository
    records=[AccountsRepository(db).canonical.get(identity) for identity in ids]
    facts=tuple(FoundationFact(f.canonical_concept,f.value_numeric,f.availability_status.value,
        f.extraction_method.value,f.document_id,f.period.period_end.isoformat(),f.financial_fact_id)
        for f in records)
    foundation=FoundationView('ZZ000003','unused-m2','r1',2025,2025,'2025-12-31','EXACT',(),(),facts,(),(),(),(),())
    beliefs=tuple(transform_saved_value(code,None) for code in ('G1.1','G1.2','G2.2','F1.1','F2.2','F2.3'))
    view=ReferenceView('SYNTHETIC',foundation,date(2026,9,29),'reference-test',beliefs,False)
    rows=evidence_rows(db,view,'F1.1')
    total_rows=[row for row in rows if row['canonical_concept']=='TOTAL_ASSETS']
    assert len(total_rows)==2
    assert all(row['page']==1 and row['locator_kind']=='PDF_REGION' for row in rows)
    assert {row['canonical_value'] for row in total_rows}=={'12232894'}
    data,mime,filename=read_supporting_evidence(db,view,raw.raw_evidence_id,service.evidence.storage)
    assert data.startswith(b'%PDF') and mime=='application/pdf' and filename.endswith('.pdf')


from tests.maintenance.test_retain_latest import history  # noqa: F401


def test_five_synthetic_saved_companies_keep_numeric_memberships_when_reliability_is_zero(history):
    from risk_intelligence.maintenance.retain_latest import COMPANIES
    db,_,_=history
    observed_zero=False
    for number in COMPANIES:
        view=calculate_saved_reference_beliefs(db,number)
        before=view.beliefs
        audit=source_reliability(db,view)
        assert not audit.error
        assert view.beliefs==before
        for b in view.beliefs:
            if b.value is not None:
                assert b.unknown==0 and b.high+b.low==1
                if audit.values[b.code]==0:
                    observed_zero=True
                    assert 'source audit' in audit.explanations[b.code]
    assert observed_zero


def test_compact_ui_keeps_correct_financial_beliefs_without_optional_audits(database,storage,api,supported_ixbrl,tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from tests.m8.test_application import ENTRY, environment
    seed(database,storage,api,supported_ixbrl)
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    def forbidden(*args,**kwargs): raise AssertionError('Optional source audit must not run')
    import risk_intelligence.services.reference_support as support
    monkeypatch.setattr(support,'source_reliability',forbidden)
    at=AppTest.from_file(str(ENTRY),default_timeout=30).run()
    at.radio[0].set_value('Six-variable belief test').run()
    assert at.selectbox[0].value is None and not at.dataframe
    at.selectbox[0].set_value(NUMBER).run()
    assert not at.exception and not at.error
    assert not at.expander and not at.button
    assert len(at.dataframe)==2
    combined=at.dataframe[0].value
    assert len(combined)==6 and 'Reliability' not in combined.columns
    assert combined.loc[combined['Variable']=='Current Ratio','Unknown'].iloc[0]=='0.00'
    assert combined.loc[combined['Variable']=='Current Ratio','High risk'].iloc[0]=='1.00'
    assert 'current assets / current liabilities' in combined.loc[combined['Variable']=='Current Ratio','Value basis / formula'].iloc[0]
    assert set(combined['Domain'])=={'Governance','Financial'}
    assert any('full High support' in m.value for m in at.markdown)
