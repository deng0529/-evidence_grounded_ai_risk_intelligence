"""Executable synthetic M1 acceptance walkthrough; temporary files and no network."""

from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from risk_intelligence.domain.enums import (
    AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType,
    ProcessingStatus, RetrievalStatus, SourceType, TriggerType,
)
from risk_intelligence.domain.evidence import Company, Document, EvidenceReference, ApiLocator, RawEvidence, Source
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import open_sqlite
from risk_intelligence.persistence.evidence_repositories import SqlEvidenceReferenceRepository
from risk_intelligence.persistence.fact_repositories import SqlFinancialFactRepository
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import EvidenceIntegrityError, checksum, object_key


def inspect_storage(root: Path) -> dict[str, object]:
    """Exercise real M1 adapters and assert each reported outcome using synthetic data."""
    timestamp = datetime(2026, 1, 15, 12, tzinfo=UTC)
    company = Company(company_id="company-synthetic", company_number="ZZ000001",
                      company_name="SYNTHETIC REVIEW COMPANY")
    run = ProcessingRun(processing_run_id="run-synthetic", company_id=company.company_id,
                        company_number=company.company_number, started_at=timestamp,
                        status=ProcessingStatus.RUNNING, current_stage="SYNTHETIC_INSPECTION",
                        trigger_type=TriggerType.DEMO_PRECOMPUTE, app_version="0.1.0")
    content = b'{"synthetic":true,"current_assets":"12345.6700"}'
    digest = checksum(content)
    source = Source(source_id="source-synthetic", company_id=company.company_id,
                    company_number=company.company_number, source_type=SourceType.COMPANIES_HOUSE_API,
                    source_name="SYNTHETIC FIXTURE ONLY", source_url="https://example.invalid/synthetic",
                    retrieved_at=timestamp, retrieval_status=RetrievalStatus.SUCCESS,
                    processing_run_id=run.processing_run_id, checksum=digest)
    key = object_key(source, digest, "application/json")
    document = Document(document_id="document-synthetic", company_id=company.company_id,
                        company_number=company.company_number, source_id=source.source_id,
                        document_type="SYNTHETIC_JSON", representation_type="JSON", object_path=key, checksum=digest)
    raw = RawEvidence(raw_evidence_id="raw-synthetic", source_id=source.source_id, document_id=document.document_id,
                      object_path=key, checksum=digest, retrieved_at=timestamp,
                      processing_run_id=run.processing_run_id, media_type="application/json")
    reference = EvidenceReference(evidence_id="evidence-synthetic", source_id=source.source_id,
                                  document_id=document.document_id,
                                  location=ApiLocator(endpoint="/synthetic", json_path="$.current_assets"))
    fact = FinancialFact(
        financial_fact_id="fact-synthetic", company_id=company.company_id, company_number=company.company_number,
        canonical_concept="CURRENT_ASSETS", value_numeric=Decimal("12345.6700"), currency="GBP", unit="GBP",
        period=ReportingPeriod(period_type=PeriodType.INSTANT, period_end=date(2025, 12, 31),
                               comparability_status=ComparabilityStatus.NOT_APPLICABLE),
        source_id=source.source_id, document_id=document.document_id, evidence_ids=(reference.evidence_id,),
        extraction_method=ExtractionMethod.API_DIRECT, availability_status=AvailabilityStatus.AVAILABLE,
        processing_run_id=run.processing_run_id,
    )
    missing = FinancialFact.model_validate(fact.model_dump() | {
        "financial_fact_id": "fact-missing-synthetic", "value_numeric": None,
        "availability_status": AvailabilityStatus.NOT_DISCLOSED,
    })
    storage = LocalStorage(root / "raw")
    with open_sqlite(root / "metadata.sqlite3") as database:
        migrate(database, applied_at=timestamp)
        companies = SqlCompanyRepository(database)
        companies.save(company)
        assert companies.get_by_company_number(company.company_number) == company
        SqlAssessmentRepository(database).save_processing_run(run)
        persistence = EvidencePersistence(database, storage)
        persistence.save(source, raw, content, document)
        SqlEvidenceReferenceRepository(database).save(reference.evidence_id, reference)
        facts = SqlFinancialFactRepository(database)
        facts.save(fact.financial_fact_id, fact)
        facts.save(missing.financial_fact_id, missing)
        restored = facts.get(fact.financial_fact_id)
        restored_missing = facts.get(missing.financial_fact_id)
        assert restored == fact and restored_missing == missing
        assert restored.value_numeric.as_tuple() == fact.value_numeric.as_tuple()
        assert persistence.read(raw.raw_evidence_id) == content
        replacement = RawEvidence.model_validate(raw.model_dump() | {"checksum": checksum(b"changed")})
        rejected = False
        try:
            storage.put(replacement, b"changed")
        except EvidenceIntegrityError:
            rejected = True
        assert rejected and persistence.read(raw.raw_evidence_id) == content
        lineage = database.query("""SELECT c.company_number, s.source_id, d.document_id,
            r.raw_evidence_id, r.object_path, r.checksum, e.evidence_id, f.fact_id
            FROM fact f JOIN company c USING(company_id)
            JOIN source s ON s.source_id=f.source_id
            JOIN document d ON d.document_id=f.document_id
            JOIN raw_evidence r ON r.source_id=s.source_id AND r.document_id=d.document_id
            JOIN fact_evidence fe ON fe.fact_id=f.fact_id
            JOIN evidence_reference e ON e.evidence_id=fe.evidence_id
            WHERE f.fact_id=?""", (fact.financial_fact_id,))
        reverse = facts.fact_ids_for_evidence(reference.evidence_id)
        assert len(lineage) == 1 and fact.financial_fact_id in reverse
        return {
            "label": "SYNTHETIC M1 STORAGE INSPECTION - NO NETWORK OR REAL COMPANY DATA",
            "company_round_trip": company.model_dump(mode="json"),
            "decimal": {"type": type(restored.value_numeric).__name__, "value": str(restored.value_numeric),
                        "tuple": restored.value_numeric.as_tuple()},
            "missing": {"value": restored_missing.value_numeric,
                        "status": restored_missing.availability_status.value,
                        "sql_is_null": database.query("SELECT value_numeric IS NULL AS missing FROM fact WHERE fact_id=?",
                                                      (missing.financial_fact_id,))[0]["missing"] == 1},
            "bytes_equal": persistence.read(raw.raw_evidence_id) == content,
            "size_bytes": len(content), "sha256": checksum(persistence.read(raw.raw_evidence_id)),
            "immutable_overwrite_rejected": rejected, "lineage": lineage,
            "reverse_evidence_to_fact_ids": reverse,
        }


def main() -> None:
    """Print checked results and remove only the temporary inspection directory."""
    with TemporaryDirectory(prefix="m1-synthetic-") as temporary:
        print(json.dumps(inspect_storage(Path(temporary)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
