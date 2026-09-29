"""Explicit bounded artifact-to-SQL backfill; no extraction or model invocation."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from pydantic import ValidationError

from risk_intelligence.ingestion.accounts.models import ExtractionResult, SemanticSupport
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.connection import IntegrityError
from .evidence_persistence import EvidencePersistence


@dataclass(frozen=True)
class BackfillResult:
    """Per-interpretation outcome; missing artifact content is never fabricated."""

    interpretation_id: str
    status: Literal['INSERTED', 'UNCHANGED', 'NOT_BACKFILLABLE']
    reason: str


def backfill_semantic_support(repository: AccountsRepository, evidence: EvidencePersistence,
                              interpretation_ids: tuple[str, ...]) -> tuple[BackfillResult, ...]:
    """Process 1–100 explicit IDs, verifying bytes and exact historical decisions.

    Each support append is atomic. Earlier successful items survive a later
    infrastructure/integrity failure; exact retries are safe. Storage/checksum
    failures propagate rather than being mistaken for absent semantic context.
    """
    if not 1 <= len(interpretation_ids) <= 100 or len(set(interpretation_ids)) != len(interpretation_ids):
        raise ValueError('Require 1–100 distinct interpretation IDs')
    if repository.database is not evidence.database:
        raise IntegrityError('Backfill requires the same metadata database')
    if repository.database.in_transaction:
        raise IntegrityError('Backfill artifact reads must occur outside SQL transactions')
    outcomes = []
    for identity in interpretation_ids:
        rows = repository.database.query('SELECT * FROM financial_interpretation WHERE interpretation_id=?', (identity,))
        if not rows or rows[0]['status'] != 'AVAILABLE' or rows[0]['method'] != 'LLM_SEMANTIC':
            outcomes.append(BackfillResult(identity, 'NOT_BACKFILLABLE', 'Not an accepted semantic interpretation'))
            continue
        row = rows[0]
        links = repository.database.query('SELECT r.document_id FROM accounts_processing p '
            'JOIN raw_evidence r ON r.raw_evidence_id=p.input_raw_id WHERE p.output_raw_id=? AND p.status=?',
            (row['artifact_raw_id'], 'COMPLETE'))
        if links != [{'document_id':row['document_id']}]:
            raise IntegrityError('Backfill artifact/document lineage mismatch')
        content = evidence.read(row['artifact_raw_id'])
        try:
            result = ExtractionResult.model_validate_json(content)
        except ValidationError:
            outcomes.append(BackfillResult(identity, 'NOT_BACKFILLABLE', 'Artifact has no valid extraction/context schema'))
            continue
        decisions = [d for d in result.interpretations
            if sha256((row['artifact_raw_id']+d.model_dump_json()).encode()).hexdigest() == identity]
        contexts = [c for c in result.contexts if c.source_fact_id == row['source_fact_id']]
        if len(decisions) != 1 or len(contexts) != 1:
            outcomes.append(BackfillResult(identity, 'NOT_BACKFILLABLE', 'Exact decision or unique context missing'))
            continue
        decision = decisions[0]
        proposal = decision.proposal
        canonical = repository.canonical.get(row['canonical_fact_id'])
        if (decision.status != 'AVAILABLE' or proposal.kind != 'NORMALIZATION'
                or proposal.method != 'LLM_SEMANTIC' or len(proposal.operands) != 1
                or proposal.operands[0].source_fact_id != row['source_fact_id']
                or proposal.target not in contexts[0].compatible_concepts
                or canonical is None or canonical.value_numeric != decision.value):
            outcomes.append(BackfillResult(identity, 'NOT_BACKFILLABLE', 'Historical support does not match accepted observation'))
            continue
        support = SemanticSupport(interpretation_id=identity, rationale=proposal.rationale, context=contexts[0])
        # Reuse the immutable ledger comparison to check every existing admission
        # field, without rerunning semantic normalization or arithmetic admission.
        previous = repository.get_semantic_support(identity)
        repository.save_interpretation(row['document_id'], row['artifact_raw_id'], decision,
                                      row['canonical_fact_id'], support.context)
        outcomes.append(BackfillResult(identity, 'UNCHANGED' if previous else 'INSERTED', 'Verified historical support'))
    return tuple(outcomes)
