"""Cached interpretation orchestration, separate from pure financial admission."""

from hashlib import sha256
import json

from risk_intelligence.domain.evidence import RawEvidence
from risk_intelligence.ingestion.companies_house.client import ParseError
from .interpretation import VERSION, deterministic_proposals, verify
from .llm import OpenAIExtraction, INTERPRETATION_PROMPT_VERSION, INTERPRETATION_SCHEMA_VERSION
from .mapping import FinancialMappingRegistry
from .models import ExtractionResult, InterpretationResponse
from .processing import ProcessingCache, fingerprint


def _artifact_id(cache: ProcessingCache, raw: RawEvidence, stage: str,
                 version: str, config: dict[str, str | int]) -> str:
    identity = fingerprint(raw.checksum, stage+':'+version,
                           config | {'document_id':raw.document_id or raw.raw_evidence_id})
    return cache.database.query('SELECT output_raw_id FROM accounts_processing WHERE fingerprint=?',
                                (identity,))[0]['output_raw_id']


def interpret(cache: ProcessingCache, raw: RawEvidence, run_id: str,
              result: ExtractionResult, registry: FinancialMappingRegistry,
              llm: OpenAIExtraction | None) -> ExtractionResult:
    """Prefer deterministic decisions; ask only about context-supported unresolved inputs.

    No model request is made for debt lacking independent completeness evidence.
    Bounded proposals and all rejection decisions remain immutable cached artifacts.
    """
    deterministic = deterministic_proposals(result, registry)
    available = {(d.proposal.target,d.proposal.period_end) for d in deterministic if d.status=='AVAILABLE'}
    by_id = {f.source_fact_id:f for f in result.facts}
    contexts = tuple(c for c in result.contexts if any(
        (target,by_id[c.source_fact_id].period.period_end) not in available for target in c.compatible_concepts))
    output = None
    llm_id = None
    unavailable = None
    if contexts and llm is not None and llm.enabled and callable(getattr(llm,'interpret',None)):
        ids = {c.source_fact_id for c in contexts}
        ids.update(identity for proof in result.proofs for identity in proof.source_fact_ids + proof.cross_check_ids)
        evidence = json.dumps({'facts':[by_id[i].model_dump(mode='json') for i in sorted(ids)],
            'contexts':[c.model_dump(mode='json') for c in contexts],
            'proofs':[p.model_dump(mode='json') for p in result.proofs],
            'unresolved_concepts':sorted({target for c in contexts for target in c.compatible_concepts})}, sort_keys=True)
        if len(contexts) <= 24 and len(evidence) <= 40000:
            config = {'schema':INTERPRETATION_SCHEMA_VERSION,'model':llm.model,'config':llm.config_version,
                      'evidence_sha':sha256(evidence.encode()).hexdigest(),'max_output_tokens':5000}
            try:
                output,_ = cache.run(raw,run_id,'LLM',INTERPRETATION_PROMPT_VERSION,config,
                                      lambda _:llm.interpret(evidence))
                llm_id = _artifact_id(cache,raw,'LLM',INTERPRETATION_PROMPT_VERSION,config)
            except ParseError:
                unavailable = 'Optional semantic proposal unavailable; supported source facts retained'
        else:
            unavailable = 'Optional semantic proposal input exceeds bound'
    elif contexts:
        unavailable = 'Optional semantic proposal disabled; source semantics remain unresolved'
    config = {'source_sha':sha256(result.model_dump_json().encode()).hexdigest(),
              'mapping':registry.version,'llm_sha':sha256(output).hexdigest() if output else 'none',
              'provider_status':unavailable or 'available'}

    def admit(_: bytes) -> bytes:
        decisions = list(deterministic)
        notes = list(result.completeness_notes)
        if unavailable:
            notes.append(unavailable)
        if output is not None:
            try:
                artifact = json.loads(output)
                if artifact.get('status') != 'completed':
                    raise ValueError('Incomplete model response')
                proposals = InterpretationResponse.model_validate_json(artifact['output']).proposals
            except ValueError:
                notes.append('Malformed/incomplete semantic proposal; no model mappings admitted')
                proposals = ()
            for proposal in proposals:
                decision = verify(proposal,result,registry)
                expected = 'LLM_SEMANTIC' if proposal.kind == 'NORMALIZATION' else 'LLM_DERIVATION'
                if proposal.method != expected:
                    decision = decision.model_copy(update={'status':'VALIDATION_FAILED','value':None,
                        'reason':'Model proposal cannot claim deterministic authorship'})
                elif (proposal.target,proposal.period_end) in available:
                    decision = decision.model_copy(update={'status':'SUPERSEDED','value':None,
                        'reason':'Supported deterministic observation takes priority'})
                decisions.append(decision.model_copy(update={'llm_artifact_id':llm_id}))
        return result.model_copy(update={'interpretations':tuple(decisions),'completeness_notes':tuple(notes)}).model_dump_json().encode()
    encoded,_ = cache.run(raw,run_id,'PARSE',VERSION,config,admit)
    return ExtractionResult.model_validate_json(encoded).model_copy(update={
        'interpretation_artifact_id':_artifact_id(cache,raw,'PARSE',VERSION,config)})
