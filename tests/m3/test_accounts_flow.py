"""Offline M2-to-M3 handoff with actual storage and repeated orchestration."""

from datetime import UTC, datetime
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.accounts.mapping import FinancialMappingRegistry, MappingRule
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import open_sqlite
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.storage.local import LocalStorage


@pytest.mark.parametrize('filing_count', [1, 3])
def test_m2_handoff_document_publication_source_canonical_and_reuse(tmp_path: Path, ixbrl: bytes, filing_count: int) -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    def m2(path: str) -> Response:
        name = urlsplit(path).path.rsplit('/', 1)[1]
        if name == 'ZZ000003':
            data = {'company_number': name, 'company_name': 'SYNTHETIC M3 COMPANY'}
        else:
            items = ([{'transaction_id': f'accounts-{i}', 'date': f'{2026-i}-05-01', 'category': 'accounts',
                       'type': 'AA', 'links': {'document_metadata': f'/document/synthetic-{i}'}}
                      for i in range(filing_count)]
                     if name == 'filing-history' else [])
            data = {'items': items, 'start_index': 0, 'items_per_page': 100, 'total_results': len(items)}
        return Response(path, json.dumps(data).encode(), 200, now)

    class Documents:
        calls = 0

        def get(self, url: str, media_type: str = 'application/json') -> Response:
            self.calls += 1
            content = json.dumps({'resources': {'application/xhtml+xml': {}}}).encode() if media_type == 'application/json' else ixbrl
            if media_type != 'application/json' and url.endswith('-1'):
                content = content.replace(b'2024-12-31', b'2023-12-31').replace(b'2025-12-31', b'2024-12-31')
            return Response(url, content, 200, now, media_type)

    with open_sqlite() as database:
        migrate(database)
        storage = LocalStorage(tmp_path / 'raw')
        CompaniesHouseIngestion(database, storage, CompaniesHouseClient(m2), clock=lambda: now).ingest(
            'ZZ000003', now.date(), 'm2')
        documents = Documents()
        registry = FinancialMappingRegistry('synthetic-v1', (
            MappingRule(source_concept='{urn:synthetic:accounts:v1}NetAssets', canonical_concept='NET_ASSETS'),))
        service = AccountsIngestion(database, storage, documents, registry=registry)
        first = service.ingest('ZZ000003', now.date(), 'm3-first')
        assert first.status.value == 'COMPLETE'
        expected_documents = min(filing_count, 2)
        assert documents.calls == expected_documents * 2
        assert database.query("SELECT stopping_reason FROM accounts_run WHERE processing_run_id='m3-first'") == [
            {'stopping_reason': 'THREE_CANDIDATE_PERIODS' if filing_count == 3 else 'M2_INPUTS_EXHAUSTED'}]
        counts = [len(database.query('SELECT * FROM ' + table)) for table in
                  ('raw_evidence','financial_source_fact','financial_observation_lineage')]
        second = service.ingest('ZZ000003', now.date(), 'm3-second')
        assert second.status == first.status
        assert documents.calls == expected_documents * 2
        assert counts == [len(database.query('SELECT * FROM ' + table)) for table in
                          ('raw_evidence','financial_source_fact','financial_observation_lineage')]
        assert database.query("SELECT reused_raw,reused_parse FROM accounts_run_document WHERE processing_run_id='m3-second'") == [
            {'reused_raw': 1, 'reused_parse': 1}] * expected_documents
        assert not database.query('PRAGMA foreign_key_check')
        from risk_intelligence.ingestion.accounts.readiness import readiness_report
        report = readiness_report(database, 'm3-second')
        for variable in ('G1.1','G1.2','G2.1','G2.2','G2.3','G3.1','F1.1','F1.2','F2.2','F2.3','F3.1'):
            assert variable in report
        assert 'TOTAL_ASSETS' in report and 'EXTRACTION_FAILED' in report
        assert '-123400' in report and '2024-12-31' in report
        from risk_intelligence.ingestion.accounts.processing import ProcessingCache
        from risk_intelligence.services.evidence_persistence import EvidencePersistence
        evidence = EvidencePersistence(database, storage)
        raw_id = database.query('SELECT raw_evidence_id FROM raw_evidence WHERE document_id IS NOT NULL')[0]['raw_evidence_id']
        raw = evidence.raw.get(raw_id)
        cache = ProcessingCache(database, evidence)
        calls = []
        def operation(content: bytes) -> bytes:
            calls.append(content)
            return b'{"synthetic":true}'
        assert cache.run(raw, 'm3-first', 'LLM', 'test-v1', {'model': 'synthetic'}, operation)[1] is False
        assert cache.run(raw, 'm3-second', 'LLM', 'test-v1', {'model': 'synthetic'}, operation)[1] is True
        assert len(calls) == 1
        assert cache.run(raw, 'm3-second', 'LLM', 'test-v2', {'model': 'synthetic'}, operation)[1] is False
        assert len(calls) == 2
        # A new mapping version adds history but each run keeps exactly its own
        # observation membership, including reused results and explicit NULLs.
        registry_v2 = FinancialMappingRegistry('synthetic-v2', registry.rules)
        AccountsIngestion(database, storage, documents, registry=registry_v2).ingest(
            'ZZ000003', now.date(), 'm3-remapped')
        first_ids = {r['fact_id'] for r in database.query(
            "SELECT fact_id FROM accounts_run_fact WHERE processing_run_id='m3-first'")}
        reused_ids = {r['fact_id'] for r in database.query(
            "SELECT fact_id FROM accounts_run_fact WHERE processing_run_id='m3-second'")}
        remapped_ids = {r['fact_id'] for r in database.query(
            "SELECT fact_id FROM accounts_run_fact WHERE processing_run_id='m3-remapped'")}
        assert first_ids == reused_ids and first_ids.isdisjoint(remapped_ids)
        assert len(first_ids) == len(remapped_ids) == 12 * expected_documents
        assert documents.calls == expected_documents * 2
        assert readiness_report(database, 'm3-second') == report
        # A competing/reentrant worker cannot replay an outstanding external call.
        from risk_intelligence.persistence.connection import IntegrityError
        from risk_intelligence.ingestion.companies_house.client import ParseError
        def competing_operation(content: bytes) -> bytes:
            with pytest.raises(IntegrityError, match='explicit recovery'):
                cache.run(raw, 'm3-second', 'LLM', 'concurrent-v1', {}, operation)
            return b'{}'
        cache.run(raw, 'm3-first', 'LLM', 'concurrent-v1', {}, competing_operation)
        assert len(calls) == 2
        def failure(content: bytes) -> bytes:
            raise ParseError('Synthetic failed processing')
        with pytest.raises(ParseError, match='Synthetic'):
            cache.run(raw, 'm3-first', 'LLM', 'failed-v1', {}, failure)
        with pytest.raises(ParseError, match='Prior processing failed'):
            cache.run(raw, 'm3-second', 'LLM', 'failed-v1', {}, operation)
        assert len(calls) == 2
        cache.run(raw, 'm3-first', 'OCR', 'engine-v1', {'dpi': 200}, operation)
        cache.run(raw, 'm3-second', 'OCR', 'engine-v1', {'dpi': 200}, operation)
        cache.run(raw, 'm3-second', 'OCR', 'engine-v1', {'dpi': 300}, operation)
        assert len(calls) == 4  # Same OCR config reused, changed config recomputed.
