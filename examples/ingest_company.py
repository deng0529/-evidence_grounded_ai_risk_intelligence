"""Explicit opt-in Companies House -> R2 -> Turso ingestion, with safe verification output.

Credentials come from the process environment through existing Settings. This
entry point never loads .env implicitly or prints source bodies/personal fields.
"""

import argparse
from datetime import date
import json

from risk_intelligence.config import load_settings
from risk_intelligence.domain.enums import ProcessingStatus
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, HttpTransport
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import Database, open_database
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.storage.objects import verify_checksum
from risk_intelligence.storage.r2 import R2Storage


def verify_run(database: Database, storage: R2Storage, run_id: str, *,
               allow_statements_not_found: bool = False) -> dict[str, object]:
    """Verify evidence and completeness, optionally checking the documented PSC 404 branch.

    This explicit smoke-test option does not change persisted completeness, run
    status or reuse eligibility. It accepts only observed PSC Statements HTTP 404,
    never an authentication, transport, parsing or arbitrary resource failure.
    """
    snapshots = database.query("SELECT * FROM resource_snapshot WHERE processing_run_id=? ORDER BY resource", (run_id,))
    context = database.query("SELECT * FROM ingestion_run WHERE processing_run_id=?", (run_id,))
    if len(context) != 1 or len(snapshots) != 5:
        raise RuntimeError("Run does not have five resource snapshots")
    run_rows = database.query("SELECT status FROM processing_run WHERE processing_run_id=?", (run_id,))
    if len(run_rows) != 1:
        raise RuntimeError("Run is absent")
    resources = []
    raw_count, fact_count = 0, 0
    for snapshot in snapshots:
        if not snapshot["complete"]:
            if (not allow_statements_not_found or snapshot["resource"] != "persons-with-significant-control-statements"
                    or snapshot["availability_status"] != "RETRIEVAL_FAILED" or snapshot["error_code"] != "HTTP_404"
                    or snapshot["page_count"] != 0 or snapshot["item_count"] != 0 or snapshot["reused_snapshot_id"]):
                raise RuntimeError("Resource is incomplete; smoke acceptance blocked")
            failed = database.query(
                "SELECT source_id,http_status,retrieval_status FROM source WHERE processing_run_id=? "
                "AND source_name=?", (run_id, "Companies House persons-with-significant-control-statements"))
            if (len(failed) != 1 or failed[0]["http_status"] != 404 or failed[0]["retrieval_status"] != "FAILED"
                    or run_rows[0]["status"] != "PARTIAL"):
                raise RuntimeError("Missing resource lacks explicit failed provenance")
            if database.query("SELECT raw_evidence_id FROM raw_evidence WHERE source_id=?", (failed[0]["source_id"],)):
                raise RuntimeError("Failed resource falsely claims raw evidence")
            resources.append({"resource": snapshot["resource"], "complete": False, "reused": False,
                              "availability_status": "RETRIEVAL_FAILED", "http_status": 404,
                              "pages": 0, "items": None, "facts": 0})
            continue
        origin = snapshot
        visited: set[str] = set()
        while origin["reused_snapshot_id"]:
            if origin["snapshot_id"] in visited:
                raise RuntimeError("Cyclic snapshot provenance")
            visited.add(origin["snapshot_id"])
            rows = database.query("SELECT * FROM resource_snapshot WHERE snapshot_id=?", (origin["reused_snapshot_id"],))
            if len(rows) != 1:
                raise RuntimeError("Missing reused snapshot")
            origin = rows[0]
        pages = database.query(
            "SELECT r.*, a.request_path FROM raw_evidence r JOIN source s USING(source_id) "
            "JOIN api_response a USING(source_id) WHERE s.processing_run_id=? AND a.resource=?",
            (origin["processing_run_id"], origin["resource"]))
        if len(pages) != origin["page_count"]:
            raise RuntimeError("Snapshot page coverage differs from raw evidence")
        count = 0
        for page in pages:
            verify_checksum(storage.read(page["object_path"]), page["checksum"])
            facts = database.query("SELECT fact_id,source_id FROM fact WHERE source_id=?", (page["source_id"],))
            links = database.query(
                "SELECT fe.fact_id,e.source_id FROM fact_evidence fe JOIN evidence_reference e USING(evidence_id) "
                "JOIN fact f USING(fact_id) WHERE f.source_id=?", (page["source_id"],))
            if ({fact["fact_id"] for fact in facts} != {link["fact_id"] for link in links}
                    or any(link["source_id"] != page["source_id"] for link in links)):
                raise RuntimeError("Fact evidence lineage mismatch")
            count += len(facts)
        resources.append({"resource": snapshot["resource"], "complete": bool(snapshot["complete"]),
                          "reused": snapshot["reused_snapshot_id"] is not None,
                          "pages": len(pages), "items": origin["item_count"], "facts": count})
        raw_count += len(pages)
        fact_count += count
    if database.query("PRAGMA foreign_key_check"):
        raise RuntimeError("Relational provenance check failed")
    return {"processing_run_id": run_id, "run_status": run_rows[0]["status"],
            "assessment_date": context[0]["assessment_date"],
            "horizon_start": context[0]["horizon_start"], "resources": resources,
            "verified_raw_pages": raw_count, "facts": fact_count, "provenance_verified": True}


def main() -> None:
    """Run only with explicit --live and caller-supplied company/date/run identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--company", required=True)
    parser.add_argument("--assessment-date", type=date.fromisoformat, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-statements-not-found", action="store_true",
                        help="Verify documented PSC Statements 404 without claiming complete data")
    args = parser.parse_args()
    if not args.live:
        parser.error("Network and cloud writes require explicit --live")
    try:
        settings = load_settings()
        if settings.environment != "production" or settings.companies_house_api_key is None:
            raise ValueError("Explicit production cloud configuration and Companies House key required")
        with open_database(settings) as database:
            migrate(database)
            storage = R2Storage.from_settings(settings)
            client = CompaniesHouseClient(HttpTransport(settings.companies_house_api_key))
            result = CompaniesHouseIngestion(database, storage, client).ingest(
                args.company, args.assessment_date, args.run_id)
            if result.run.status != ProcessingStatus.COMPLETE and not args.allow_statements_not_found:
                print(json.dumps({"processing_run_id": args.run_id, "status": result.run.status.value,
                                  "resources": [{"resource": s.resource.value, "complete": s.complete,
                                                 "error_code": s.error_code} for s in result.snapshots]}))
                raise SystemExit(1)
            print(json.dumps(verify_run(database, storage, args.run_id,
                                        allow_statements_not_found=args.allow_statements_not_found), indent=2))
    except Exception as error:
        # CLI boundary deliberately suppresses provider payloads, validation inputs,
        # URLs and credentials. Library callers receive typed exceptions.
        print(json.dumps({"processing_run_id": args.run_id, "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
