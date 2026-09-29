"""Explicit M3 cloud smoke entry point; credentials come only from environment."""

import argparse
from datetime import date
from hashlib import sha256
from pathlib import Path

from risk_intelligence.config import load_settings
from risk_intelligence.ingestion.accounts.client import DocumentClient
from risk_intelligence.ingestion.accounts.llm import OpenAIExtraction
from risk_intelligence.ingestion.accounts.readiness import readiness_report
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.persistence.connection import open_database
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.r2 import R2Storage


def main() -> None:
    """Run bounded accounts ingestion only with explicit cloud opt-in and date."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--company', required=True)
    parser.add_argument('--assessment-date', type=date.fromisoformat, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--download-host', action='append', default=[])
    parser.add_argument('--tessdata', type=Path)
    parser.add_argument('--enable-llm', action='store_true')
    parser.add_argument('--llm-config-version')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    settings = load_settings()
    if not args.live or settings.database_backend != 'turso' or settings.evidence_storage_backend != 'r2':
        parser.error('Explicit --live and Turso/R2 configuration are required')
    if not settings.companies_house_api_key:
        parser.error('Companies House credentials are required')
    if args.enable_llm and not args.llm_config_version:
        parser.error('Enabling LLM requires an explicit config version')
    ocr_version = 'disabled'
    if args.tessdata:
        ocr_version = 'pymupdf-1.28.2-eng-' + sha256((args.tessdata / 'eng.traineddata').read_bytes()).hexdigest()
    client = DocumentClient(settings.companies_house_api_key, download_hosts=tuple(args.download_host))
    llm = (OpenAIExtraction(settings.openai_api_key, settings.openai_extraction_model,
                            config_version=args.llm_config_version) if args.enable_llm else None)
    storage = R2Storage.from_settings(settings)
    with open_database(settings) as database:
        migrate(database)
        service = AccountsIngestion(database, storage, client, tessdata=str(args.tessdata) if args.tessdata else None,
            ocr_version=ocr_version, llm=llm)
        run = service.ingest(args.company, args.assessment_date, args.run_id)
        evidence = EvidencePersistence(database, storage)
        raw_ids = database.query('SELECT DISTINCT r.raw_evidence_id FROM raw_evidence r '
            'LEFT JOIN accounts_run_document d ON d.document_id=r.document_id '
            'WHERE r.processing_run_id=? OR d.processing_run_id=?', (args.run_id, args.run_id))
        for row in raw_ids:
            evidence.read(row['raw_evidence_id'])
        if database.query('PRAGMA foreign_key_check'):
            raise RuntimeError('M3 relational provenance verification failed')
        report = readiness_report(database, args.run_id)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding='utf-8')
        print('M3 run:', run.processing_run_id, 'status:', run.status.value)
        print('Verified raw objects:', len(raw_ids))
        print('Data Readiness Report:', args.report)
        if run.status.value != 'COMPLETE':
            raise SystemExit(2)


if __name__ == '__main__':
    main()
