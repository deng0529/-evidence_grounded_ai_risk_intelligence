"""Source-heading handoff through existing SQL records, without cloud access."""

from decimal import Decimal

import pytest

from risk_intelligence.ingestion.accounts.asset_side import _source, PARSER_VERSION as STRUCTURE_VERSION
from risk_intelligence.ingestion.accounts.interpretation import deterministic_proposals
from risk_intelligence.ingestion.accounts.mapping import default_registry
from risk_intelligence.ingestion.accounts.pdf import PageText, Word, extract_pdf, PARSER_VERSION
from risk_intelligence.ingestion.accounts.scope import source_scope, SCOPE_VERSION
from risk_intelligence.persistence.connection import IntegrityError, PersistenceError
from risk_intelligence.persistence.evidence_repositories import SqlEvidenceReferenceRepository
from test_fallback_flow import fallback_context
from test_pdf_llm import layout


def headed(heading: str, *, page: int = 1) -> PageText:
    """Keep the numeric table fixed while varying only the source statement title."""
    original = layout()
    return original.model_copy(update={'page': page, 'words': tuple(
        word.model_copy(update={'text': heading}) if word.text == 'Balance sheet' else word
        for word in original.words)})


@pytest.mark.parametrize(('heading', 'scope'), [
    ('Company Balance Sheet', 'COMPANY'),
    ('Company statement of financial position', 'COMPANY'),
    ('Company balance sheet as at 31 December 2025', 'COMPANY'),
    ('Group Balance Sheet', 'GROUP'),
    ('Consolidated statement of financial position', 'GROUP'),
    ('Balance Sheet', 'UNRESOLVED'),
    ('Statement of financial position', 'UNRESOLVED'),
])
def test_explicit_heading_and_numeric_extraction(heading: str, scope: str) -> None:
    result = extract_pdf((headed(heading),), 'd', 'ZZ000003')
    assert [fact.value for fact in result.facts] == [Decimal('-500'), Decimal('750'), Decimal(0), Decimal(10)]
    assert all(fact.source_scope == scope for fact in result.facts)
    assert all(fact.statement_context == heading and fact.parser_version == PARSER_VERSION
               for fact in result.facts)
    mapped = [default_registry().map(fact, company_id='c', company_number='ZZ000003',
              source_id='s', processing_run_id='r1') for fact in result.facts]
    if scope == 'GROUP':
        assert all(item is None for item in mapped)
        assert all(fact.dimensions == (('pdf:entity-scope', 'GROUP'),) for fact in result.facts)
    else:
        assert [item.canonical_concept for item in mapped] == ['NET_ASSETS', 'NET_ASSETS', 'INVENTORY', 'INVENTORY']
        assert [item.value_numeric for item in mapped] == [fact.value for fact in result.facts]


@pytest.mark.parametrize('extra', ['Group balance sheet', 'Balance sheet', 'Company balance sheet'])
def test_multiple_statement_headings_do_not_choose_a_scope(extra: str) -> None:
    page = headed('Company balance sheet')
    page = page.model_copy(update={'words': page.words + (
        Word(x=10.0, y=15.0, right=180.0, text=extra),)})
    result = extract_pdf((page,), 'd', 'ZZ000003')
    assert all(fact.source_scope == 'UNRESOLVED' for fact in result.facts)
    assert all(fact.statement_context == 'Company balance sheet\n' + extra for fact in result.facts)


@pytest.mark.parametrize('context', [None, 'Balance sheet', 'Company and Group balance sheet',
                                    'The company publishes a balance sheet'])
def test_absent_or_unsupported_context_is_not_company(context: str | None) -> None:
    assert source_scope(context, PARSER_VERSION) == 'UNRESOLVED'


def test_admission_success_and_canonical_concept_do_not_establish_scope() -> None:
    result = extract_pdf((headed('Balance sheet'),), 'd', 'ZZ000003')
    decisions = deterministic_proposals(result, default_registry())
    assert decisions and all(decision.status == 'AVAILABLE' for decision in decisions)
    assert {decision.proposal.target for decision in decisions} == {'NET_ASSETS', 'INVENTORY'}
    assert all(fact.source_scope == 'UNRESOLVED' for fact in result.facts)
    old = result.facts[0].model_copy(update={'parser_version': 'pdf-table-v3',
                                          'statement_context': None})
    assert old.source_scope == 'UNRESOLVED'
    assert source_scope('Company balance sheet', 'unrecognized-parser') == 'UNRESOLVED'


def test_heading_after_financial_columns_does_not_supply_scope() -> None:
    page = headed('Balance sheet')
    page = page.model_copy(update={'words': page.words + (
        Word(x=10.0, y=100.0, right=180.0, text='Company balance sheet'),)})
    result = extract_pdf((page,), 'd', 'ZZ000003')
    assert all(fact.statement_context == 'Balance sheet' and fact.source_scope == 'UNRESOLVED'
               for fact in result.facts)


def test_legacy_explicit_group_is_retained_but_conflicting_context_is_unresolved() -> None:
    fact = extract_pdf((headed('Group balance sheet'),), 'd', 'ZZ000003').facts[0]
    legacy = fact.model_copy(update={'parser_version': 'pdf-table-v3', 'statement_context': None})
    assert legacy.source_scope == 'GROUP'
    assert legacy.model_copy(update={'dimensions': ()}).source_scope == 'UNRESOLVED'
    assert fact.model_copy(update={'statement_context': 'Company balance sheet'}).source_scope == 'UNRESOLVED'


@pytest.mark.parametrize(('heading', 'scope'), [('Company Balance Sheet', 'COMPANY'),
    ('Group Balance Sheet', 'GROUP'), ('Balance Sheet', 'UNRESOLVED')])
def test_sql_roundtrip_retains_heading_locator_version_and_scope(fallback_context, monkeypatch,
                                                               heading: str, scope: str) -> None:
    service, raw, _ = fallback_context
    result = extract_pdf((headed(heading, page=2),), 'd', 'ZZ000003')
    service._save_facts(raw, result)
    before = service.database.query('SELECT * FROM financial_source_fact ORDER BY source_fact_id')
    service._save_facts(raw, result)
    assert service.database.query('SELECT * FROM financial_source_fact ORDER BY source_fact_id') == before

    def forbidden(*args, **kwargs):
        raise AssertionError('Scope retrieval must use SQL only')

    monkeypatch.setattr(service.evidence, 'read', forbidden)
    for fact in result.facts:
        restored = service.repository.get_source(fact.source_fact_id)
        assert restored == fact
        assert restored.source_scope == scope and restored.parser_version == 'pdf-table-v4'
        evidence = SqlEvidenceReferenceRepository(service.database).get(fact.evidence_id)
        assert evidence.location.page == 2 and evidence.location.section == heading
        assert evidence.location.label == fact.source_label
        assert evidence.evidence_text == fact.raw_value
    assert SCOPE_VERSION == 'pdf-heading-scope-v1'
    assert service.database.query('PRAGMA foreign_key_check') == []


def test_company_and_unqualified_remain_distinct_in_sql(fallback_context) -> None:
    service, raw, _ = fallback_context
    loaded = []
    for page, heading in ((2, 'Company balance sheet'), (3, 'Balance sheet')):
        result = extract_pdf((headed(heading, page=page),), 'd', 'ZZ000003')
        service._save_facts(raw, result)
        loaded.append(service.repository.get_source(result.facts[0].source_fact_id))
    assert [fact.source_scope for fact in loaded] == ['COMPANY', 'UNRESOLVED']
    assert loaded[0].value == loaded[1].value
    assert loaded[0].source_concept == loaded[1].source_concept
    assert loaded[0].statement_context != loaded[1].statement_context


def test_scope_context_is_immutable_and_cannot_be_dropped(fallback_context) -> None:
    service, raw, _ = fallback_context
    result = extract_pdf((headed('Company balance sheet'),), 'd', 'ZZ000003')
    service._save_facts(raw, result)
    fact = result.facts[0]
    with pytest.raises(IntegrityError, match='context/locator mismatch'):
        service.repository.save_source(fact.model_copy(update={'statement_context': None}))
    references = SqlEvidenceReferenceRepository(service.database)
    reference = references.get(fact.evidence_id)
    with pytest.raises(IntegrityError, match='immutable'):
        references.save(fact.evidence_id, reference.model_copy(update={'location':
            reference.location.model_copy(update={'section': 'Group balance sheet'})}))
    with pytest.raises(PersistenceError):
        service.database.execute('UPDATE evidence_reference SET section=? WHERE evidence_id=?',
                                 ('Group balance sheet', fact.evidence_id))
    assert service.repository.get_source(fact.source_fact_id) == fact


def test_old_observation_survives_append_only_versioned_reprocessing(fallback_context) -> None:
    from hashlib import sha256

    service, raw, _ = fallback_context
    result = extract_pdf((headed('Company balance sheet'),), 'd', 'ZZ000003')
    old_facts = tuple(fact.model_copy(update={
        'source_fact_id': sha256(('old:' + fact.source_fact_id).encode()).hexdigest(),
        'evidence_id': 'old-' + fact.evidence_id, 'parser_version': 'pdf-table-v3',
        'statement_context': None}) for fact in result.facts)
    service._save_facts(raw, result.model_copy(update={'facts': old_facts}))
    old_rows = service.database.query("SELECT * FROM financial_source_fact WHERE parser_version='pdf-table-v3'")
    old_canonical = service.database.query('SELECT * FROM fact ORDER BY fact_id')
    service._save_facts(raw, result)
    assert service.database.query("SELECT * FROM financial_source_fact WHERE parser_version='pdf-table-v3'") == old_rows
    for row in old_canonical:
        assert service.database.query('SELECT * FROM fact WHERE fact_id=?', (row['fact_id'],)) == [row]
    assert all(service.repository.get_source(f.source_fact_id).source_scope == 'UNRESOLVED' for f in old_facts)
    assert all(service.repository.get_source(f.source_fact_id).source_scope == 'COMPANY' for f in result.facts)


def test_structural_source_uses_its_own_page_context_not_anchor_scope() -> None:
    anchor = extract_pdf((headed('Company balance sheet'),), 'd', 'ZZ000003').facts[0]
    page = headed('Balance sheet', page=2)
    row = tuple(word for word in page.words if word.y == 60)
    component = _source(anchor, page, 5, 'Net assets', row, (250, 330), 'test-component')
    assert component.parser_version == STRUCTURE_VERSION
    assert component.statement_context == 'Balance sheet' and component.source_scope == 'UNRESOLVED'
    assert component.page == 2 and component.value == Decimal('-500')
