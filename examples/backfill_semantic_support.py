"""Review eligible IDs or explicitly append support from existing cloud artifacts."""

import argparse

from risk_intelligence.config import load_settings
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.connection import open_database
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.services.semantic_support_backfill import backfill_semantic_support
from risk_intelligence.storage.r2 import R2Storage


def main() -> None:
    """Default to metadata-only listing; applying requires explicit bounded IDs.

    Credentials must already be supplied in the environment. Migration 006 must
    have been separately approved/applied; this command never runs migrations.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--interpretation-id', action='append', default=[])
    args = parser.parse_args()
    settings = load_settings()
    if settings.database_backend != 'turso':
        parser.error('Explicit Turso configuration required')
    ids = tuple(args.interpretation_id)
    if args.apply and (not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids)):
        parser.error('--apply requires 1–100 distinct --interpretation-id values')
    with open_database(settings) as database:
        rows = database.query("SELECT i.interpretation_id FROM financial_interpretation i "
            "JOIN document d USING(document_id) WHERE d.company_number=? "
            "AND i.method='LLM_SEMANTIC' AND i.status='AVAILABLE' ORDER BY i.interpretation_id", (args.company,))
        eligible = {row['interpretation_id'] for row in rows}
        if not args.apply:
            print('Accepted semantic interpretations (support may already exist):', len(rows))
            for row in rows:
                print(row['interpretation_id'])
            return
        if not set(ids) <= eligible:
            parser.error('Selected IDs must be accepted semantic interpretations for this company')
        if settings.evidence_storage_backend != 'r2':
            parser.error('Explicit R2 configuration required for artifact backfill')
        if not database.query("SELECT name FROM sqlite_master WHERE type='table' AND name='financial_semantic_support'"):
            parser.error('Migration 006 must be separately applied before backfill')
        evidence = EvidencePersistence(database, R2Storage.from_settings(settings))
        for result in backfill_semantic_support(AccountsRepository(database), evidence, ids):
            print(result.interpretation_id, result.status, result.reason)


if __name__ == '__main__':
    main()
