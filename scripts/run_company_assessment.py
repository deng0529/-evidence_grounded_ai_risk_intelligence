"""Run/replay the production M5 leaf example without changing frozen methodology."""

import argparse
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from risk_intelligence.config import load_settings
from risk_intelligence.ingestion.accounts.client import DocumentClient
from risk_intelligence.ingestion.accounts.llm import OpenAIExtraction
from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, HttpTransport
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import open_database, open_sqlite
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.services.company_assessment import (
    CompanyGoldenResult, persisted_leaves, render_table, run_company_assessment,
)
from risk_intelligence.services.structured_snapshot import snapshot_database
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.r2 import R2Storage
from risk_intelligence.services.structured_snapshot import recover_company_evidence, verify_company_bundle
from risk_intelligence.ingestion.companies_house.client import ParseError


class CachedExtraction(OpenAIExtraction):
    """Select existing provider fingerprints; prohibit requests on every cache miss."""

    def __init__(self, model: str, config_version: str) -> None:
        super().__init__(None, model, config_version=config_version)

    @property
    def enabled(self) -> bool:
        """Enable cache lookup without requiring or supplying a provider credential."""
        return True

    def _request(self, *args, **kwargs) -> bytes:
        raise ParseError("Cached-only extraction has no matching provider artifact")


def environment(path: Path) -> dict[str, str]:
    """Read simple KEY=value local configuration; never print or modify credentials."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("Environment file must contain KEY=value entries")
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


def main(argv: list[str] | None = None) -> int:
    """Fresh ingestion or explicit SQL-source reuse, followed by persisted-result export."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-number")
    parser.add_argument("--assessment-date", type=date.fromisoformat)
    parser.add_argument("--reporting-year", type=int, help="Selected financial reporting year for MVP v1.1/v1.2")
    parser.add_argument("--run-id")
    parser.add_argument("--database", type=Path, required=True, help="Local SQLite assessment database")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--snapshot-configured-database", action="store_true",
                        help="Read-only snapshot of configured SQL backend into a NEW local SQLite file")
    parser.add_argument("--snapshot-local-database", type=Path, help="Copy an existing local bundle database into a NEW destination")
    parser.add_argument("--reuse-m2-run", help="Reuse this M2 run; omit --reuse-m3-run to reprocess M3 from immutable raw evidence")
    parser.add_argument("--reuse-m3-run", help="Reuse this M3 run together with --reuse-m2-run")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path, help="Verify audit JSON against persisted SQL and print; no ingestion or credentials")
    parser.add_argument("--max-documents", type=int, default=5)
    parser.add_argument("--evidence-directory", type=Path, default=Path("data/golden/raw"))
    parser.add_argument("--document-download-host", action="append", default=[])
    parser.add_argument("--tessdata", type=Path)
    parser.add_argument("--enable-llm", action="store_true")
    parser.add_argument("--cached-llm-model", help="Explicit recorded model for cache-only replay; never calls a provider")
    parser.add_argument("--recover-configured-evidence", action="store_true", help="Read configured R2 objects into the local evidence directory")
    parser.add_argument("--verify-evidence-bundle", action="store_true", help="Verify all local company objects and export their immutable identities")
    parser.add_argument("--llm-config-version", default="company-golden-v1")
    args = parser.parse_args(argv)
    if args.replay:
        if not args.database.exists():
            parser.error("Replay database does not exist")
        report = CompanyGoldenResult.model_validate_json(args.replay.read_text(encoding="utf-8"))
        with open_sqlite(args.database) as database:
            repository = SqlAssessmentRepository(database)
            context = repository.get_assessment(report.assessment_id)
            if (context is None or context.company_number != report.company_number
                    or context.assessment_date != report.assessment_date
                    or context.processing_run_id != report.application_run_id):
                raise ValueError("Audit context differs from persisted assessment")
            if context.risk_model_version in ("1.1", "1.2") and repository.get_financial_reporting_year(report.assessment_id) != report.reporting_year:
                raise ValueError("Audit reporting year differs from persisted assessment")
            if persisted_leaves(database, report.assessment_id) != report.leaves:
                raise ValueError("Audit JSON differs from persisted M5 results")
        print(render_table(report))
        return 0
    if not all((args.company_number, args.assessment_date, args.reporting_year, args.run_id, args.output)):
        parser.error("Execution requires --company-number, --assessment-date, --reporting-year, --run-id and --output")
    if args.output.exists():
        parser.error("Audit output already exists; use --replay")
    if not 1 <= args.max_documents <= 10:
        parser.error("--max-documents must be between 1 and 10")
    if args.snapshot_configured_database and not args.reuse_m2_run:
        parser.error("A structured-only snapshot requires explicit ingestion-run reuse")
    if args.snapshot_configured_database and args.snapshot_local_database:
        parser.error("Choose one snapshot source")
    if args.snapshot_local_database and not args.snapshot_local_database.is_file():
        parser.error("Local snapshot source does not exist")
    settings = load_settings(environment(args.env_file))
    if args.enable_llm and args.cached_llm_model:
        parser.error("Choose live LLM or cached-only LLM")
    if args.snapshot_configured_database:
        with open_database(settings) as source:
            counts = snapshot_database(source, args.database)
        manifest = args.database.with_suffix(".snapshot.json")
        manifest.write_text(json.dumps({"snapshot_version": "structured-snapshot-v1", "row_counts": counts}, indent=2), encoding="utf-8")
    elif args.snapshot_local_database:
        with open_sqlite(args.snapshot_local_database) as source:
            counts = snapshot_database(source, args.database)
        args.database.with_suffix(".snapshot.json").write_text(
            json.dumps({"snapshot_version": "structured-snapshot-v1", "row_counts": counts}, indent=2), encoding="utf-8")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with open_sqlite(args.database) as database:
        migrate(database)
        if args.recover_configured_evidence:
            records = recover_company_evidence(database, args.company_number,
                R2Storage.from_settings(settings), LocalStorage(args.evidence_directory))
            manifest = args.database.with_suffix(".evidence.json")
            with manifest.open("x", encoding="utf-8") as output:
                json.dump([record.model_dump(mode="json") for record in records], output, indent=2)
        m2 = m3 = None
        reuse = ((args.reuse_m2_run, args.reuse_m3_run)
                 if args.reuse_m2_run and args.reuse_m3_run else None)
        reprocess_m3 = bool(args.reuse_m2_run and not args.reuse_m3_run)
        if args.reuse_m3_run and not args.reuse_m2_run:
            parser.error("--reuse-m3-run requires --reuse-m2-run")
        if reuse is None:
            if not reprocess_m3 and settings.companies_house_api_key is None:
                parser.error("COMPANIES_HOUSE_API_KEY is required for live ingestion")
            if args.enable_llm and not (settings.openai_api_key and settings.openai_extraction_model):
                parser.error("--enable-llm requires OPENAI_API_KEY and OPENAI_EXTRACTION_MODEL")
            storage = LocalStorage(args.evidence_directory)
            if not reprocess_m3:
                m2 = CompaniesHouseIngestion(database, storage, CompaniesHouseClient(HttpTransport(settings.companies_house_api_key)))
            model = OpenAIExtraction(settings.openai_api_key, settings.openai_extraction_model,
                                     config_version=args.llm_config_version) if args.enable_llm else None
            if args.cached_llm_model:
                model = CachedExtraction(args.cached_llm_model, args.llm_config_version)
            ocr_version = "disabled"
            if args.tessdata:
                trained = args.tessdata / "eng.traineddata"
                if not trained.is_file():
                    parser.error("OCR requires eng.traineddata in --tessdata")
                ocr_version = "pymupdf-1.28.2-eng-" + sha256(trained.read_bytes()).hexdigest()
            document_client = None if reprocess_m3 else DocumentClient(
                settings.companies_house_api_key, download_hosts=tuple(args.document_download_host))
            m3 = AccountsIngestion(database, storage, document_client,
                tessdata=str(args.tessdata) if args.tessdata else None, ocr_version=ocr_version, llm=model)
        report = run_company_assessment(database, number=args.company_number, assessment_date=args.assessment_date, reporting_year=args.reporting_year,
            run_id=args.run_id, calculated_at=datetime.now(UTC), m2=m2, m3=m3, reuse_runs=reuse,
            reuse_m2_run=args.reuse_m2_run if reprocess_m3 else None, max_documents=args.max_documents)
        if args.recover_configured_evidence or args.verify_evidence_bundle:
            records = verify_company_bundle(database, args.company_number, LocalStorage(args.evidence_directory))
            with args.output.with_suffix(".bundle.json").open("x", encoding="utf-8") as output:
                json.dump([record.model_dump(mode="json") for record in records], output, indent=2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(report.model_dump_json(indent=2) + "\n")
        print(render_table(report))
        print(f"\nAudit JSON: {args.output}")
        print(f"Production handoff rejections: {len(report.stage_issues)} (details retained in JSON)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Provider errors can contain endpoints or credentials. The normal audit
        # contains source/validation diagnostics; unexpected errors expose type only.
        print(f"Golden execution stopped: {type(error).__name__}; no result was fabricated.", file=sys.stderr)
        raise SystemExit(1) from None
