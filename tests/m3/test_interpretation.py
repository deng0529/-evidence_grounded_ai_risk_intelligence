"""Context-grounded normalization and cached, untrusted model proposals."""

from datetime import date
from decimal import Decimal
import json

import pytest

from risk_intelligence.ingestion.accounts.asset_side import inspect_context_rows
from risk_intelligence.ingestion.accounts.interpretation import VERSION, deterministic_proposals, operand, verify
from risk_intelligence.ingestion.accounts.interpretation_workflow import interpret
from risk_intelligence.ingestion.accounts.mapping import default_registry
from risk_intelligence.ingestion.accounts.models import InterpretationProposal
from risk_intelligence.ingestion.accounts.pdf import PageText, Word, extract_pdf
from test_fallback_flow import fallback_context


def contextual(page: PageText, *, generic: bool = False):
    """A current liability amount whose meaning depends on the preceding section."""
    words = [w for w in page.words if w.y not in (50,60)]
    words += [Word(x=10.0,y=50.0,right=220.0,text='Creditors'),
              Word(x=10.0,y=60.0,right=220.0,text='Creditors' if generic else 'Amounts falling due within one year')]
    words += [Word(x=280.0,y=60.0,right=310.0,text='100'),Word(x=380.0,y=60.0,right=410.0,text='80')]
    page = page.model_copy(update={'words':tuple(words)})
    result = inspect_context_rows((page,),extract_pdf((page,),'d','ZZ000003'))
    return result


def proposal(result):
    fact = next(f for f in result.facts if f.source_concept == 'structure:context-row')
    return InterpretationProposal(target='CURRENT_LIABILITIES',kind='NORMALIZATION',method='LLM_SEMANTIC',
        scope='COMPANY',period_end=fact.period.period_end,currency='GBP',unit='GBP',operands=(operand(fact),),
        rationale='The Company statement classifies this amount under Creditors with an explicit current maturity',version=VERSION)


def test_alternative_terminology_requires_verified_context_and_preserves_source(fallback_context) -> None:
    _,_,page = fallback_context
    result = contextual(page)
    item = proposal(result)
    accepted = verify(item,result,default_registry())
    assert accepted.status == 'AVAILABLE' and accepted.value == Decimal('100')
    assert item.operands[0].source_label == 'Amounts falling due within one year'
    assert result.contexts[0].section == 'Creditors'
    assert item.operands[0].evidence_id == result.facts[-2].evidence_id
    assert verify(item,result.model_copy(update={'contexts':()}),default_registry()).status == 'VALIDATION_FAILED'
    generic = contextual(page,generic=True)
    assert not generic.contexts
    assert not any(d.proposal.target == 'CURRENT_LIABILITIES' for d in deterministic_proposals(generic,default_registry()))


@pytest.mark.parametrize('update',[{'scope':'GROUP'},{'period_end':date(2000,12,31)},
                                  {'target':'TOTAL_ASSETS'},{'currency':'USD'}])
def test_semantic_context_mismatch_or_unsupported_target_rejected(fallback_context,update) -> None:
    _,_,page = fallback_context
    result = contextual(page)
    assert verify(proposal(result).model_copy(update=update),result,default_registry()).status == 'VALIDATION_FAILED'


def test_approved_mapping_does_not_require_semantic_model(fallback_context) -> None:
    service,raw,page = fallback_context
    result = extract_pdf((page,),'d','ZZ000003')
    class Forbidden:
        enabled = True
        def interpret(self, evidence):
            raise AssertionError('Approved mapping must avoid the model')
    actual = interpret(service.cache,raw,'r1',result,service.registry,Forbidden())
    assert actual.interpretations and all(d.proposal.method == 'DETERMINISTIC_MAPPING' for d in actual.interpretations)


@pytest.mark.parametrize('reject',[False,True])
def test_semantic_artifact_reuse_sql_admission_and_rejected_source_retention(fallback_context,reject) -> None:
    service,raw,page = fallback_context
    result = contextual(page)
    item = proposal(result)
    if reject:
        item = item.model_copy(update={'target':'TOTAL_ASSETS'})
    class Model:
        enabled = True
        model = 'synthetic-model'
        config_version = 'synthetic-config'
        calls = 0
        def interpret(self,evidence):
            self.calls += 1
            return json.dumps({'status':'completed','requested_model':self.model,
                'prompt_version':'test','schema_version':'test','input':json.loads(evidence),
                'output':json.dumps({'proposals':[item.model_dump(mode='json')]})}).encode()
    model = Model()
    first = interpret(service.cache,raw,'r1',result,service.registry,model)
    first_ids = service._save_facts(raw,first)
    second = interpret(service.cache,raw,'r2',result,service.registry,model)
    assert second == first and model.calls == 1
    assert service._save_facts(raw,second) == first_ids
    decision = first.interpretations[-1]
    assert decision.status == ('VALIDATION_FAILED' if reject else 'AVAILABLE')
    assert decision.llm_artifact_id is not None
    assert service.repository.get_source(item.operands[0].source_fact_id) is not None
    row = service.database.query("SELECT * FROM financial_interpretation WHERE method='LLM_SEMANTIC'")[0]
    assert row['status'] == decision.status and row['llm_artifact_raw_id'] == decision.llm_artifact_id
    if not reject:
        fact = service.repository.canonical.get(row['canonical_fact_id'])
        assert fact.canonical_concept == 'CURRENT_LIABILITIES' and fact.value_numeric == Decimal('100')
        assert fact.evidence_ids == (item.operands[0].evidence_id,)
    else:
        assert row['canonical_fact_id'] is None
        rejected = service.database.query("SELECT availability_status FROM fact WHERE canonical_concept='TOTAL_ASSETS' AND period_end='2025-12-31'")
        assert rejected == [{'availability_status':'VALIDATION_FAILED'}]
    assert not service.database.query('PRAGMA foreign_key_check')


def test_complete_debt_plan_requires_independent_proof(fallback_context) -> None:
    from risk_intelligence.ingestion.accounts.models import CompletenessProof
    service,_,page = fallback_context
    result = contextual(page)
    item = proposal(result).model_copy(update={'kind':'DERIVATION','method':'LLM_DERIVATION',
        'target':'INTEREST_BEARING_DEBT','proof_id':'complete-debt'})
    assert verify(item,result,service.registry).status == 'VALIDATION_FAILED'
    # This synthetic fixture represents a parser-verified exhaustive disclosure;
    # model output cannot supply or modify this trusted proof collection.
    proof = CompletenessProof(proof_id='complete-debt',target='INTEREST_BEARING_DEBT',
        source_fact_ids=(item.operands[0].source_fact_id,),document_id='d',page=2,row_start=1,row_end=8,
        evidence_text='Synthetic complete interest-bearing population',relationship='EXHAUSTIVE_INTEREST_BEARING')
    assert verify(item,result.model_copy(update={'proofs':(proof,)}),service.registry).value == Decimal('100')


@pytest.mark.parametrize('label,complete', [('Invoice financing',True),('Interest-bearing director loan',True),
                                          ('Trade creditors',False),('Accruals',False)])
def test_exhaustive_debt_population_is_not_a_fixed_component_list(fallback_context,label,complete) -> None:
    from risk_intelligence.ingestion.accounts.asset_side import inspect_debt_population
    service,_,balance = fallback_context
    result = extract_pdf((balance,),'d','ZZ000003')
    words = [Word(x=10.0,y=float(y),right=220.0,text=text) for y,text in (
        (10,'Company'),(20,'GBP'),(30,'Interest-bearing debt comprises only:'),(50,label))]
    for y,right,value in ((40,310,'2025'),(40,410,'2024'),(50,310,'100'),(50,410,'80')):
        words.append(Word(x=float(right-30),y=float(y),right=float(right),text=value))
    page = balance.model_copy(update={'page':3,'words':tuple(words)})
    actual = inspect_debt_population((page,),result)
    decisions = [d for d in deterministic_proposals(actual,service.registry) if d.proposal.target=='INTEREST_BEARING_DEBT']
    assert bool(decisions) == complete
    if complete:
        assert decisions[0].status == 'AVAILABLE' and decisions[0].value == Decimal('100')
        assert decisions[0].proposal.operands[0].source_label == label
        assert decisions[0].proposal.operands[0].page == 3


def test_optional_provider_requests_data_schema_without_executable_code(monkeypatch) -> None:
    from types import SimpleNamespace
    from pydantic import SecretStr
    from risk_intelligence.ingestion.accounts.llm import OpenAIExtraction
    import openai
    seen = {}
    class Client:
        def __init__(self, **kwargs):
            self.responses = self
        def __enter__(self):
            return self
        def __exit__(self,*args):
            return None
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(model='synthetic',status='completed',output_text='{"proposals":[]}')
    monkeypatch.setattr(openai,'OpenAI',Client)
    model = OpenAIExtraction(SecretStr('synthetic-offline-placeholder'),'synthetic',config_version='test')
    artifact = json.loads(model.interpret('{"facts":[]}'))
    assert artifact['prompt_version'] == 'financial-interpretation-proposals-v1'
    assert seen['store'] is False and seen['max_output_tokens'] == 5000
    schema = seen['text']['format']['schema']
    for definition in schema['$defs'].values():
        if definition.get('type') == 'object':
            assert set(definition['required']) == set(definition['properties'])
    assert 'result' not in schema['$defs']['InterpretationProposal']['properties']
