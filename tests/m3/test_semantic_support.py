"""SQL-only semantic context and bounded artifact backfill without provider calls."""

import json

import pytest

from risk_intelligence.ingestion.accounts.interpretation_workflow import interpret
from risk_intelligence.persistence.connection import IntegrityError, PersistenceError
from risk_intelligence.services.semantic_support_backfill import backfill_semantic_support
from risk_intelligence.storage.objects import EvidenceIntegrityError
from test_fallback_flow import fallback_context
from test_interpretation import contextual, proposal


def publish(service, raw, page):
    """Publish a fixture using the real cache, ledger and canonical writer."""
    source = contextual(page)
    item = proposal(source)
    class Model:
        enabled = True
        model = 'synthetic'
        config_version = 'test'

        def interpret(self, evidence):
            return json.dumps({'status':'completed', 'output':json.dumps({
                'proposals':[item.model_dump(mode='json')]})}).encode()
    result = interpret(service.cache, raw, 'r1', source, service.registry, Model())
    service._save_facts(raw, result)
    row = service.database.query("SELECT * FROM financial_interpretation WHERE method='LLM_SEMANTIC'")[0]
    return row, result


def test_sql_only_context_roundtrip_and_immutable_retry(fallback_context, monkeypatch):
    service, raw, page = fallback_context
    row, result = publish(service, raw, page)
    def forbidden(*args):
        raise AssertionError('SQL retrieval must not read artifacts')
    monkeypatch.setattr(service.evidence, 'read', forbidden)
    support = service.repository.get_semantic_support(row['interpretation_id'])
    assert support.rationale == result.interpretations[-1].proposal.rationale
    assert support.context.statement == 'Company balance sheet'
    assert support.context.section == 'Creditors'
    assert 'Amounts falling due within one year' in support.context.supporting_text
    assert support.context.compatible_concepts == ('CURRENT_LIABILITIES',)
    assert not service.repository.save_semantic_support(support)
    with pytest.raises(IntegrityError, match='Conflicting immutable'):
        service.repository.save_semantic_support(support.model_copy(update={'rationale':'Different rationale'}))
    with pytest.raises(PersistenceError):
        service.database.execute('DELETE FROM financial_semantic_support')
    assert service.repository.get_semantic_support('absent') is None
    assert not service.database.query('PRAGMA foreign_key_check')


def test_missing_context_rolls_back_entire_publication(fallback_context, monkeypatch):
    service, raw, page = fallback_context
    original = service.repository.save_interpretation
    def missing(document, artifact, decision, canonical, context=None):
        return original(document, artifact, decision, canonical, None)
    monkeypatch.setattr(service.repository, 'save_interpretation', missing)
    with pytest.raises(IntegrityError, match='requires source context'):
        publish(service, raw, page)
    assert not service.database.query('SELECT * FROM financial_interpretation')
    assert not service.database.query('SELECT * FROM financial_source_fact')
    assert not service.database.query('SELECT * FROM fact')


@pytest.mark.parametrize('change', [{'source_fact_id':'unrelated'}, {'compatible_concepts':('TOTAL_ASSETS',)}])
def test_context_must_match_source_and_target(fallback_context, change):
    service, raw, page = fallback_context
    row, _ = publish(service, raw, page)
    support = service.repository.get_semantic_support(row['interpretation_id'])
    with pytest.raises(IntegrityError, match='does not match'):
        service.repository.save_semantic_support(support.model_copy(update={
            'context':support.context.model_copy(update=change)}))


def test_backfill_rejects_wrong_artifact_link_without_reading_bytes(fallback_context, monkeypatch):
    service, raw, page = fallback_context
    row, _ = publish(service, raw, page)
    query = service.database.query
    def wrong_link(sql, parameters=()):
        return [{'document_id':'other'}] if 'SELECT r.document_id FROM accounts_processing' in sql else query(sql, parameters)
    def forbidden(*args):
        raise AssertionError('Invalid linkage must fail before object reads')
    monkeypatch.setattr(service.database, 'query', wrong_link)
    monkeypatch.setattr(service.evidence, 'read', forbidden)
    with pytest.raises(IntegrityError, match='lineage mismatch'):
        backfill_semantic_support(service.repository, service.evidence, (row['interpretation_id'],))


@pytest.mark.parametrize('mode', ['valid', 'missing', 'malformed', 'checksum'])
def test_historical_backfill_is_bounded_verified_and_idempotent(fallback_context, monkeypatch, mode):
    service, raw, page = fallback_context
    # Reproduce the pre-006 ledger writer without altering immutable SQL rows.
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, 'save_semantic_support', lambda support: False)
        row, result = publish(service, raw, page)
    before = service.database.query('SELECT * FROM fact')
    if mode in ('missing', 'malformed'):
        # Publish a genuine checksummed legacy artifact lacking usable context,
        # with its own matching historical interpretation identity.
        payload = result.model_copy(update={'contexts':()}).model_dump_json().encode() if mode == 'missing' else b'{}'
        service.cache.run(raw, 'r1', 'PARSE', 'legacy-'+mode, {}, lambda _:payload)
        artifact = service.database.query('SELECT output_raw_id FROM accounts_processing WHERE version=?', ('legacy-'+mode,))[0]['output_raw_id']
        with monkeypatch.context() as patch:
            patch.setattr(service.repository, 'save_semantic_support', lambda support: False)
            decision = result.interpretations[-1]
            service.repository.save_interpretation('d', artifact, decision, row['canonical_fact_id'], result.contexts[-2])
        row = service.database.query('SELECT * FROM financial_interpretation WHERE artifact_raw_id=?', (artifact,))[0]
    if mode == 'checksum':
        monkeypatch.setattr(service.evidence.storage, 'read', lambda path:b'corrupt')
        with pytest.raises(EvidenceIntegrityError):
            backfill_semantic_support(service.repository, service.evidence, (row['interpretation_id'],))
        assert service.repository.get_semantic_support(row['interpretation_id']) is None
        return
    outcomes = backfill_semantic_support(service.repository, service.evidence, (row['interpretation_id'],))
    assert outcomes[0].status == ('INSERTED' if mode == 'valid' else 'NOT_BACKFILLABLE')
    if mode == 'valid':
        assert backfill_semantic_support(service.repository, service.evidence, (row['interpretation_id'],))[0].status == 'UNCHANGED'
    assert service.database.query('SELECT * FROM fact') == before
    with pytest.raises(ValueError):
        backfill_semantic_support(service.repository, service.evidence, ())
    assert not service.database.query('PRAGMA foreign_key_check')
