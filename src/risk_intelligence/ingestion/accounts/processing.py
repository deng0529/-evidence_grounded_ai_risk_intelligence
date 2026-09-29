"""Versioned derived-artifact publication and durable processing claims."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Literal

from risk_intelligence.domain.enums import RetrievalStatus
from risk_intelligence.domain.evidence import RawEvidence, Source
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.mapping import encode, text
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.objects import checksum, object_key
from risk_intelligence.ingestion.companies_house.client import ParseError


def fingerprint(input_sha: str, version: str, config: dict[str, str | int]) -> str:
    """Hash stable algorithm inputs; creation time and secrets are not inputs."""
    return sha256(json.dumps([input_sha, version, config], sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ProcessingCache:
    """One durable claim per fingerprint; no automatic retry after uncertain work."""

    def __init__(self, database: Database, evidence: EvidencePersistence) -> None:
        self.database, self.evidence = database, evidence

    def run(self, raw: RawEvidence, run_id: str, stage: Literal['PARSE','OCR','LLM','CANONICAL'],
            version: str, config: dict[str, str | int], operation: Callable[[bytes], bytes]) -> tuple[bytes, bool]:
        """Return a verified derived artifact and whether a completed result was reused.

        RUNNING after a crash is deliberately not replayed: callers must reconcile
        uncertain external outcomes and explicitly change retry configuration.
        """
        identity = fingerprint(raw.checksum, stage + ':' + version,
                               config | {'document_id': raw.document_id or raw.raw_evidence_id})
        content = self.evidence.read(raw.raw_evidence_id)
        with self.database.transaction():
            existing = self.database.query('SELECT * FROM accounts_processing WHERE fingerprint=?', (identity,))
            if not existing:
                self.database.execute('INSERT INTO accounts_processing VALUES (?,?,?,?,?,?,?,?,?,?)', (
                    identity, stage, raw.raw_evidence_id, run_id, version,
                    json.dumps(config, sort_keys=True, separators=(',', ':')), encode(datetime.now(UTC)),
                    'RUNNING', None, None))
            self.database.execute('INSERT OR IGNORE INTO accounts_run_processing VALUES (?,?)', (run_id, identity))
        if existing:
            if existing[0]['status'] == 'FAILED':
                raise ParseError('Prior processing failed; explicit version/retry change required')
            if existing[0]['status'] != 'COMPLETE':
                raise IntegrityError('Processing attempt requires explicit recovery; automatic replay refused')
            return self.evidence.read(text(existing[0]['output_raw_id'])), True
        try:
            result = operation(content)
            parent = self.evidence.sources.get(raw.source_id)
            if parent is None:
                raise IntegrityError('Missing processing source')
            now = datetime.now(UTC)
            source = Source(source_id='derived-' + identity, company_id=parent.company_id,
                company_number=parent.company_number, source_type=parent.source_type,
                source_name='DERIVED ' + stage + ' artifact; not filed evidence',
                source_identifier='derived:' + identity, retrieved_at=now,
                retrieval_status=RetrievalStatus.SUCCESS, processing_run_id=run_id, checksum=checksum(result))
            output = RawEvidence(raw_evidence_id='artifact-' + identity, source_id=source.source_id,
                object_path=object_key(source, checksum(result), 'application/json'), checksum=checksum(result),
                retrieved_at=now, processing_run_id=run_id, media_type='application/json')
            self.evidence.save(source, output, result)
            with self.database.transaction():
                self.database.execute("UPDATE accounts_processing SET status='COMPLETE',output_raw_id=? WHERE fingerprint=?",
                                      (output.raw_evidence_id, identity))
            return result, False
        except Exception:
            # Record failure without storing provider exceptions, raw source text or keys.
            with self.database.transaction():
                self.database.execute("UPDATE accounts_processing SET status='FAILED',error_code='PROCESSING_FAILED' WHERE fingerprint=?",
                                      (identity,))
            raise
