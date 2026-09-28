"""Run deterministic M0 examples using SYNTHETIC / TEST DATA only."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import ValidationError

from risk_intelligence.domain.common import Contract
from risk_intelligence.domain.enums import (
    AvailabilityStatus, ComparabilityStatus, ExtractionMethod, NodeType,
    PeriodType, RetrievalStatus, SourceType,
)
from risk_intelligence.domain.evidence import Company, Document, EvidenceReference, IxbrlLocator, Source
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.domain.risk import AggregationResult, BeliefDistribution


class InspectionExamples(Contract):
    """A review-only bundle of real M0 model instances with fictional inputs."""

    label: str = "SYNTHETIC / TEST DATA - NOT A REAL COMPANY ASSESSMENT"
    company: Company
    source: Source
    document: Document
    evidence: EvidenceReference
    valid_fact: FinancialFact
    missing_fact: FinancialFact
    future_result: AggregationResult


def build_examples() -> InspectionExamples:
    """Construct fixed examples; all result components are supplied, not calculated."""
    timestamp = datetime(2026, 1, 15, 12, tzinfo=UTC)
    company = Company(
        company_id="synthetic-company", company_number="ZZ000001",
        company_name="SYNTHETIC TEST COMPANY",
    )
    source = Source(
        source_id="synthetic-source", company_id=company.company_id,
        company_number=company.company_number,
        source_type=SourceType.COMPANIES_HOUSE_IXBRL,
        source_name="SYNTHETIC filed-accounts fixture",
        source_url="https://example.invalid/synthetic/accounts",
        retrieved_at=timestamp, retrieval_status=RetrievalStatus.SUCCESS,
        processing_run_id="synthetic-run",
    )
    document = Document(
        document_id="synthetic-document", company_id=company.company_id,
        company_number=company.company_number, source_id=source.source_id,
        document_type="ACCOUNTS", representation_type="IXBRL",
        title="SYNTHETIC accounts for model inspection",
        period_end=date(2025, 12, 31),
    )
    evidence = EvidenceReference(
        evidence_id="synthetic-evidence", source_id=source.source_id,
        document_id=document.document_id,
        location=IxbrlLocator(concept="synthetic:CurrentAssets", context_id="year-end"),
        evidence_text="SYNTHETIC current assets: GBP 12345.6700",
    )
    valid_fact = FinancialFact(
        financial_fact_id="synthetic-current-assets", company_id=company.company_id,
        company_number=company.company_number, canonical_concept="CURRENT_ASSETS",
        source_concept="synthetic:CurrentAssets", value_numeric=Decimal("12345.6700"),
        currency="GBP", unit="GBP", period=ReportingPeriod(
            period_type=PeriodType.INSTANT, period_end=date(2025, 12, 31),
            comparability_status=ComparabilityStatus.NOT_APPLICABLE,
        ),
        source_id=source.source_id, document_id=document.document_id,
        evidence_ids=(evidence.evidence_id,), extraction_method=ExtractionMethod.IXBRL_DIRECT,
        availability_status=AvailabilityStatus.AVAILABLE, processing_run_id="synthetic-run",
    )
    missing_fact = FinancialFact(
        financial_fact_id="synthetic-missing-inventory", company_id=company.company_id,
        company_number=company.company_number, canonical_concept="INVENTORY",
        value_numeric=None, source_id=source.source_id, document_id=document.document_id,
        extraction_method=ExtractionMethod.IXBRL_DIRECT,
        availability_status=AvailabilityStatus.NOT_DISCLOSED, processing_run_id="synthetic-run",
    )
    future_result = AggregationResult(
        aggregation_result_id="synthetic-result", assessment_id="synthetic-assessment",
        node_code="OVERALL", node_type=NodeType.OVERALL, node_name="Overall",
        belief=BeliefDistribution(
            low_belief=Decimal("0.20"), high_belief=Decimal("0.30"),
            unknown_belief=Decimal("0.50"),
        ),
        er_model_version="1", calculated_at=timestamp,
    )
    return InspectionExamples(
        company=company, source=source, document=document, evidence=evidence,
        valid_fact=valid_fact, missing_fact=missing_fact, future_result=future_result,
    )


def main() -> None:
    """Print exact serialized examples and demonstrate rejection of UNKNOWN."""
    examples = build_examples()
    payload = examples.model_dump(mode="json")
    invalid = examples.missing_fact.model_dump()
    invalid["value_numeric"] = "UNKNOWN"
    try:
        FinancialFact.model_validate(invalid)
    except ValidationError:
        payload["unknown_string_rejected"] = True
    else:
        raise AssertionError("UNKNOWN must not be accepted as a numeric value")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
