"""Offline production-service orchestration and exact persisted-result reporting."""

from datetime import timedelta
import json

import pytest

from risk_intelligence.ingestion.accounts.service import AccountsIngestion
from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response
from risk_intelligence.ingestion.companies_house.service import CompaniesHouseIngestion
from risk_intelligence.persistence.connection import IntegrityError, open_sqlite
from risk_intelligence.services.company_assessment import (
    CompanyGoldenResult, persisted_leaves, render_table, run_company_assessment,
)
from risk_intelligence.services.structured_snapshot import snapshot_database
from tests.m2.conftest import NOW, NUMBER
from tests.m3.conftest import ixbrl  # noqa: F401


class Documents:
    """Synthetic HTTP bytes only; production M3 still extracts and publishes them."""

    def __init__(self, content):
        self.content = content.replace(b"ZZ000003", NUMBER.encode())
        self.calls = []

    def get(self, url, media_type="application/json"):
        self.calls.append((url, media_type))
        content = json.dumps({"resources": {"application/xhtml+xml": {}}}).encode() if media_type == "application/json" else self.content
        return Response(url, content, 200, NOW, media_type)


def services(database, storage, api, ixbrl):
    api.payloads["profile"]["accounts"] = {"next_accounts": {"period_end_on": "2026-12-31", "due_on": "2027-09-30"}}
    api.payloads["filing-history"] = [{"transaction_id": "old-accounts", "date": "2026-05-01",
        "category": "accounts", "type": "AA", "description_values": {"made_up_date": "2025-12-31"},
        "links": {"document_metadata": "/document/synthetic"}}]
    documents = Documents(ixbrl)
    return (CompaniesHouseIngestion(database, storage, CompaniesHouseClient(api), clock=lambda: NOW),
            AccountsIngestion(database, storage, documents), documents)


def test_real_services_fresh_mode_and_sql_replay(database, storage, api, ixbrl):
    m2, m3, documents = services(database, storage, api, ixbrl)
    report = run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025, run_id="runner",
                                    calculated_at=NOW, m2=m2, m3=m3)
    assert len(report.leaves) == 6
    assert documents.calls and api.calls
    assert database.query("SELECT count(*) AS n FROM financial_source_fact")[0]["n"] > 0
    assert database.query("SELECT count(*) AS n FROM validated_evidence_set") == [{"n": 2}]
    assert database.query("SELECT count(*) AS n FROM validated_obligation") == [{"n": 2}]
    assert report.leaves == persisted_leaves(database, report.assessment_id)
    assert CompanyGoldenResult.model_validate_json(report.model_dump_json()) == report
    accounts = next(leaf for leaf in report.leaves if leaf.result.variable_code == "G1.1")
    assert accounts.result.raw_value == 0
    # Typed unavailable M3 observations now cross M4 as validated missingness
    # rather than failing the handoff for lack of fictitious lineage.
    assert not report.stage_issues
    unavailable = database.query(
        "SELECT availability_status, reliability_r FROM validated_fact "
        "WHERE availability_status='EXTRACTION_FAILED'"
    )
    assert unavailable
    assert all(row["reliability_r"] == "0" for row in unavailable)
    rendered = render_table(report)
    assert len([line for line in rendered.splitlines() if line.startswith(("G1.", "G2.", "G3.", "F1.", "F2.", "F3."))]) == 6
    assert str(accounts.result.final_belief.low_belief) in rendered
    assert database.query("PRAGMA foreign_key_check") == []


def test_explicit_reuse_does_not_repeat_ingestion_and_keeps_ids(database, storage, api, ixbrl):
    m2, m3, documents = services(database, storage, api, ixbrl)
    first = run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025, run_id="first",
                                   calculated_at=NOW, m2=m2, m3=m3)
    calls = (tuple(api.calls), tuple(documents.calls))
    second = run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025, run_id="second",
        calculated_at=NOW, reuse_runs=(first.m2_run_id, first.m3_run_id))
    assert second.ingestion_mode == "REUSED_PRODUCTION_RUNS"
    assert calls == (tuple(api.calls), tuple(documents.calls))
    assert [leaf.result.final_belief for leaf in second.leaves] == [leaf.result.final_belief for leaf in first.leaves]
    assert [leaf.calculation.inputs for leaf in second.leaves] == [leaf.calculation.inputs for leaf in first.leaves]
    assert database.query("SELECT count(*) AS n FROM validated_evidence_set") == [{"n": 2}]
    with pytest.raises(IntegrityError, match="company/date"):
        run_company_assessment(database, number=NUMBER, assessment_date=NOW.date() - timedelta(days=1), reporting_year=2025, run_id="wrong",
            calculated_at=NOW, reuse_runs=(first.m2_run_id, first.m3_run_id))


def test_readonly_snapshot_preserves_real_rows_and_refuses_overwrite(database, storage, api, ixbrl, tmp_path):
    m2, m3, _ = services(database, storage, api, ixbrl)
    report = run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025, run_id="seed",
                                    calculated_at=NOW, m2=m2, m3=m3)
    ledger = database.query("SELECT * FROM schema_migration ORDER BY version")
    target = tmp_path / "snapshot.sqlite3"
    counts = snapshot_database(database, target)
    assert counts["m5_variable_result"] == 6
    assert ledger == database.query("SELECT * FROM schema_migration ORDER BY version")
    with open_sqlite(target) as copied:
        assert persisted_leaves(copied, report.assessment_id) == report.leaves
        assert copied.query("PRAGMA foreign_key_check") == []
    with pytest.raises(FileExistsError):
        snapshot_database(database, target)


def test_missing_live_service_and_unknown_reuse_fail_without_fake_results(database):
    with pytest.raises(ValueError, match="both"):
        run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025, run_id="missing",
                               calculated_at=NOW)
    with pytest.raises(IntegrityError):
        run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025, run_id="missing",
                               calculated_at=NOW, reuse_runs=("absent-m2", "absent-m3"))
    assert database.query("SELECT count(*) AS n FROM m5_variable_result") == [{"n": 0}]


def test_reuse_m2_reprocesses_m3_from_existing_raw_without_network(database, storage, api, ixbrl):
    """Current M3 code can be applied to immutable evidence without repeating M2/network."""
    m2, m3, documents = services(database, storage, api, ixbrl)
    first = run_company_assessment(
        database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025,
        run_id="before-reprocess", calculated_at=NOW, m2=m2, m3=m3,
    )
    calls = (tuple(api.calls), tuple(documents.calls))

    offline_m3 = AccountsIngestion(database, storage, None)
    second = run_company_assessment(
        database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025,
        run_id="after-reprocess", calculated_at=NOW, m3=offline_m3,
        reuse_m2_run=first.m2_run_id,
    )

    assert second.ingestion_mode == "REUSED_M2_REPROCESSED_M3"
    assert second.m2_run_id == first.m2_run_id
    assert second.m3_run_id == "after-reprocess-m3"
    assert calls == (tuple(api.calls), tuple(documents.calls))
    assert database.query(
        "SELECT reused_raw FROM accounts_run_document WHERE processing_run_id=?",
        (second.m3_run_id,),
    ) == [{"reused_raw": 1}]
    assert not second.stage_issues
    assert database.query("PRAGMA foreign_key_check") == []


def test_evidence_recovery_preserves_bytes_and_rejects_corruption(database, storage, api, ixbrl, tmp_path):
    from risk_intelligence.services.structured_snapshot import recover_company_evidence, verify_company_bundle
    from risk_intelligence.storage.local import LocalStorage
    from risk_intelligence.storage.objects import EvidenceIntegrityError

    m2, m3, _ = services(database, storage, api, ixbrl)
    run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025,
                           run_id="bundle", calculated_at=NOW, m2=m2, m3=m3)
    destination = LocalStorage(tmp_path / "recovered")
    records = recover_company_evidence(database, NUMBER, storage, destination)
    assert records and records == verify_company_bundle(database, NUMBER, destination)
    assert all(storage.read(record.object_path) == destination.read(record.object_path) for record in records)

    class CorruptSource:
        def read(self, path):
            return b"corrupt"

    with pytest.raises(EvidenceIntegrityError):
        recover_company_evidence(database, NUMBER, CorruptSource(), destination)


def test_cached_extraction_never_contacts_provider(monkeypatch):
    from scripts.run_company_assessment import CachedExtraction
    from risk_intelligence.ingestion.companies_house.client import ParseError

    provider = CachedExtraction("recorded-model", "recorded-config")
    assert provider.enabled and provider.key is None
    for operation in (provider.extract, provider.interpret):
        with pytest.raises(ParseError, match="Cached-only"):
            operation("source evidence")


def test_handoff_integrity_error_is_not_converted_to_success(database, storage, api, ixbrl, monkeypatch):
    from risk_intelligence.validation.financial_service import FinancialValidationService

    m2, m3, _ = services(database, storage, api, ixbrl)
    def broken(*args, **kwargs):
        raise IntegrityError("Synthetic broken handoff")
    monkeypatch.setattr(FinancialValidationService, "evaluate_and_persist", broken)
    with pytest.raises(IntegrityError, match="broken handoff"):
        run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025,
                               run_id="broken", calculated_at=NOW, m2=m2, m3=m3)
    assert database.query("SELECT count(*) AS n FROM m5_variable_result") == [{"n": 0}]
