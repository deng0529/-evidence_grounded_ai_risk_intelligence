"""Before/after counts describe unique concepts and survive structured read-back."""
from types import SimpleNamespace
import json
from decimal import Decimal

from risk_intelligence.ingestion.accounts.coverage import (
    TARGETS, coverage_note, coverage_rows, coverage_text, read_coverage, resolved_concepts)
from risk_intelligence.ingestion.accounts.ixbrl_semantic import complete
from risk_intelligence.ingestion.accounts.models import ExtractionResult
from risk_intelligence.ingestion.accounts.mapping import default_registry
from test_ixbrl_direct_semantic import PERIOD, candidate, fact, service


def test_two_before_three_requested_one_recovered_are_not_candidate_counts():
    model, _, _ = service([candidate(), candidate()])  # Duplicate source occurrence is one concept.
    initial = ExtractionResult(facts=(fact('NET_ASSETS'),fact('CURRENT_ASSETS')),periods=(PERIOD,),complete=False)
    result = complete(model,SimpleNamespace(source_id='s',raw_evidence_id='raw',document_id='doc'),
                      'r','ZZ000003',initial,2025,None)
    data = read_coverage(coverage_note(result))
    assert len(data['deterministic'])==2
    assert len(data['openai_requested'])==3
    assert data['openai_recovered']==['INVENTORY']
    assert len(data['final_identified'])==3 and len(data['unknown'])==2
    assert 'OpenAI recovered 1/3' in coverage_text(data)
    rows = coverage_rows([{'reason':'Examined\n'+coverage_note(result)}])
    assert rows[0]['Resolved before OpenAI']=='2/5'
    assert rows[0]['OpenAI asked to examine']=='3/5'
    assert rows[0]['OpenAI recovered']=='1/3'


def test_complete_deterministic_result_records_zero_openai_targets():
    model, requests, _ = service()
    result = complete(model,SimpleNamespace(source_id='s'),'r','ZZ000003',
        ExtractionResult(facts=tuple(fact(c) for c in TARGETS),periods=(PERIOD,),complete=True),2025,None)
    data = read_coverage(coverage_note(result))
    assert len(data['deterministic'])==5 and not data['openai_requested'] and not requests
    assert data['unknown']==[]


def test_conflicting_values_do_not_count_as_identified():
    source = fact('INVENTORY')
    conflict = source.model_copy(update={'source_fact_id':'conflict','value':Decimal(999)})
    assert resolved_concepts((source,conflict),default_registry(),'ZZ000003','s','r')==frozenset()


def test_older_and_malformed_counts_do_not_get_invented():
    assert coverage_rows([{'reason':'Supported extraction completed'}])==[]
    assert read_coverage('FINANCIAL_COVERAGE_V1:{"route":"iXBRL/XHTML"}') is None


def test_one_openai_candidate_can_resolve_two_targets_with_python_bridge():
    model, requests, _ = service([candidate('CURRENT_LIABILITIES',label='Creditors',raw_value='500',quote='Creditors 500')])
    bridge = fact('TOTAL_ASSETS').model_copy(update={
        'source_concept':'pdf-component:total assets less current liabilities',
        'source_label':'Total assets less current liabilities', 'entity_scheme':'M2_DOCUMENT_LINEAGE'})
    initial = ExtractionResult(facts=(fact('NET_ASSETS'),fact('CURRENT_ASSETS'),fact('INVENTORY'),bridge),
                               periods=(PERIOD,),complete=False)
    result = complete(model,SimpleNamespace(source_id='s',raw_evidence_id='raw',document_id='doc'),
                      'r','ZZ000003',initial,2025,None)
    data = read_coverage(coverage_note(result))
    assert len(result.fallback.decisions)==1
    assert len(data['deterministic'])==3 and len(data['openai_requested'])==2
    assert data['openai_recovered']==['CURRENT_LIABILITIES','TOTAL_ASSETS']
    assert len(data['final_identified'])==5 and len(requests)==1
