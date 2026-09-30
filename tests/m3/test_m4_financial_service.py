"""End-to-end M3 SQL -> M4 financial validation -> immutable handoff."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from risk_intelligence.domain.enums import (
    AvailabilityStatus,
    ComparabilityStatus,
    ExtractionMethod,
    PeriodType,
    ProcessingStatus,
    RetrievalStatus,
    SourceType,
    TriggerType,
    ValidationStatus,
)
from risk_intelligence.domain.evidence import (
    Company,
    Document,
    EvidenceReference,
    PdfLocator,
    RawEvidence,
    Source,
)
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.assessment_repository import (
    SqlAssessmentRepository,
)
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import open_sqlite
from risk_intelligence.persistence.evidence_repositories import (
    SqlEvidenceReferenceRepository,
)
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.objects import checksum, object_key
from risk_intelligence.validation.financial_service import (
    FinancialValidationService,
)


NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
ASSESSMENT_DATE = date(2026, 9, 30)
COMPANY_NUMBER = "ZZ000003"


def test_sql_pdf_fact_reaches_immutable_validated_fact(
    tmp_path: Path,
) -> None:
    payload = b"%PDF-1.4 synthetic accounts"

    with open_sqlite() as db:
        migrate(db)

        company = Company(
            company_id="c",
            company_number=COMPANY_NUMBER,
            company_name="SYNTHETIC LTD",
        )
        SqlCompanyRepository(db).save(company)

        SqlAssessmentRepository(db).save_processing_run(
            ProcessingRun(
                processing_run_id="r",
                company_id="c",
                company_number=COMPANY_NUMBER,
                started_at=NOW,
                status=ProcessingStatus.RUNNING,
                current_stage="M4",
                trigger_type=TriggerType.LIVE,
                app_version="test",
            )
        )

        source = Source(
            source_id="s",
            company_id="c",
            company_number=COMPANY_NUMBER,
            source_type=SourceType.COMPANIES_HOUSE_PDF,
            source_name="Synthetic filed accounts",
            source_identifier="synthetic-accounts",
            retrieved_at=NOW,
            retrieval_status=RetrievalStatus.SUCCESS,
            processing_run_id="r",
            checksum=checksum(payload),
        )

        key = object_key(
            source,
            checksum(payload),
            "application/pdf",
        )

        document = Document(
            document_id="d",
            company_id="c",
            company_number=COMPANY_NUMBER,
            source_id="s",
            document_type="ACCOUNTS",
            representation_type="application/pdf",
            period_end=date(2025, 12, 31),
            filing_date=date(2026, 5, 1),
            object_path=key,
            checksum=checksum(payload),
        )

        raw = RawEvidence(
            raw_evidence_id="raw",
            source_id="s",
            document_id="d",
            object_path=key,
            checksum=checksum(payload),
            retrieved_at=NOW,
            processing_run_id="r",
            media_type="application/pdf",
        )

        EvidencePersistence(
            db,
            LocalStorage(tmp_path / "raw"),
        ).save(
            source,
            raw,
            payload,
            document,
        )

        evidence = EvidenceReference(
            evidence_id="e",
            source_id="s",
            document_id="d",
            location=PdfLocator(
                page=1,
                label="Net assets",
                section="Company balance sheet",
            ),
            evidence_text="Net assets 100",
        )
        SqlEvidenceReferenceRepository(db).save("e", evidence)

        period = ReportingPeriod(
            period_type=PeriodType.INSTANT,
            period_end=date(2025, 12, 31),
            comparability_status=ComparabilityStatus.COMPARABLE,
        )

        source_fact = SourceFinancialFact(
            source_fact_id="sf",
            document_id="d",
            evidence_id="e",
            source_concept="pdf-label:net assets",
            source_label="Net assets",
            raw_value="100",
            value=Decimal("100"),
            availability_status=AvailabilityStatus.AVAILABLE,
            currency="GBP",
            unit="GBP",
            scale=0,
            context_ref="page-1:2025",
            entity_identifier=COMPANY_NUMBER,
            entity_scheme="M2_DOCUMENT_LINEAGE",
            period=period,
            period_role="CURRENT",
            extraction_method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC,
            parser_version="pdf-table-v4",
            page=1,
            statement_context="Company balance sheet",
        )

        accounts = AccountsRepository(db)
        accounts.save_source(source_fact)

        fact = FinancialFact(
            financial_fact_id="f",
            company_id="c",
            company_number=COMPANY_NUMBER,
            canonical_concept="NET_ASSETS",
            source_concept="pdf-label:net assets",
            value_numeric=Decimal("100"),
            currency="GBP",
            unit="GBP",
            period=period,
            source_id="s",
            document_id="d",
            evidence_ids=("e",),
            extraction_method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC,
            availability_status=AvailabilityStatus.AVAILABLE,
            processing_run_id="r",
        )

        accounts.save_direct(
            fact,
            "sf",
            "financial-concepts-v1",
        )

        service = FinancialValidationService(db)

        result = service.evaluate_and_persist(
            validated_fact_id="vf",
            fact_id="f",
            assessment_date=ASSESSMENT_DATE,
            analytical_scope="COMPANY",
        )

        stored = service.validated.get_fact("vf")

        assert result.fact == fact
        assert result.assessment.validation.admissible
        assert stored is not None

        # M4 handoff freezes the analytical observation needed by M5.
        assert stored.fact_id == "f"
        assert stored.company_number == COMPANY_NUMBER
        assert stored.canonical_concept == "NET_ASSETS"
        assert stored.value_numeric == Decimal("100")
        assert stored.currency == "GBP"
        assert stored.unit == "GBP"
        assert stored.period_type == PeriodType.INSTANT
        assert stored.period_end == date(2025, 12, 31)
        assert stored.comparability_status == ComparabilityStatus.COMPARABLE
        assert stored.source_id == "s"
        assert stored.document_id == "d"
        assert stored.evidence_ids == ("e",)

        # Direct deterministic mapping is retained explicitly.
        assert stored.provenance_type == "DIRECT"
        assert stored.normalization_method == "financial-concepts-v1"
        assert stored.derivation_method is None

        # Frozen M4 versions.
        assert stored.validation_status == ValidationStatus.PASS
        assert (
            stored.validation_ruleset_version
            == "financial-core-derivation-v1"
        )
        assert stored.reliability_policy_version == "m4-reliability-v1"

        # Filed PDF S=.95; native deterministic extraction E=.95.
        # All consistency rules are admission-only, so V remains zero.
        # No competing observation means C=0.
        assert stored.source_quality_s == Decimal("0.95")
        assert stored.extraction_quality_e == Decimal("0.95")
        assert stored.validation_factor_v == Decimal("0.00")
        assert stored.conflict_factor_c == Decimal("0.00")
        assert stored.reliability_r == Decimal("0.9025")

        outcomes = {
            outcome.rule_id: outcome.result
            for outcome in result.assessment.validation.outcomes
        }

        assert outcomes["financial.identity"] == ValidationStatus.PASS
        assert (
            outcomes["financial.evidence_grounding"]
            == ValidationStatus.PASS
        )
        assert outcomes["financial.period"] == ValidationStatus.PASS
        assert outcomes["financial.scope"] == ValidationStatus.PASS
        assert outcomes["financial.currency"] == ValidationStatus.PASS
        assert outcomes["financial.unit_scale"] == ValidationStatus.PASS
        assert (
            outcomes["financial.semantic_consistency"]
            == ValidationStatus.PASS
        )

        # Direct observations do not require derivation/completeness work.
        assert (
            outcomes["financial.derivation_integrity"]
            == ValidationStatus.NOT_APPLICABLE
        )
        assert (
            outcomes["financial.completeness"]
            == ValidationStatus.NOT_APPLICABLE
        )
        assert (
            outcomes["financial.accounting_cross_check"]
            == ValidationStatus.NOT_APPLICABLE
        )

        # Exact retry must not create a second analytical handoff.
        retry = service.evaluate_and_persist(
            validated_fact_id="vf",
            fact_id="f",
            assessment_date=ASSESSMENT_DATE,
            analytical_scope="COMPANY",
        )

        assert retry.assessment == result.assessment
        assert db.query(
            "SELECT COUNT(*) AS n FROM validated_fact"
        ) == [{"n": 1}]

        # The persisted relational graph remains referentially sound.
        assert db.query("PRAGMA foreign_key_check") == []
