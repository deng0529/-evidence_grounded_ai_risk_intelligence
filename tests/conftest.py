"""Synthetic fixtures; no real credentials, source downloads or clock dependence."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import (
    AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType,
    RetrievalStatus, SourceType,
)
from risk_intelligence.domain.evidence import Source
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.domain.reliability import ReliabilityResult
from risk_intelligence.domain.risk import BeliefDistribution, VariableResult


@pytest.fixture
def timestamp() -> datetime:
    """A fixed aware time makes all record examples repeatable."""
    return datetime(2026, 1, 15, 12, tzinfo=UTC)


@pytest.fixture
def source(timestamp: datetime) -> Source:
    """Synthetic source event used to exercise provenance metadata."""
    return Source(
        source_id="source-test", company_id="company-test", company_number="ZZ000001",
        source_type=SourceType.COMPANIES_HOUSE_IXBRL, source_name="SYNTHETIC source",
        source_url="https://example.invalid/test", retrieved_at=timestamp,
        retrieval_status=RetrievalStatus.SUCCESS, processing_run_id="run-test",
    )


@pytest.fixture
def financial_fact() -> FinancialFact:
    """Present exact monetary observation; provenance is fictional and explicit."""
    return FinancialFact(
        financial_fact_id="fact-test", company_id="company-test", company_number="ZZ000001",
        canonical_concept="CURRENT_ASSETS", source_concept="test:CurrentAssets",
        value_numeric=Decimal("12345.6700"), currency="GBP", unit="GBP",
        period=ReportingPeriod(
            period_type=PeriodType.INSTANT, period_end=date(2025, 12, 31),
            comparability_status=ComparabilityStatus.NOT_APPLICABLE,
        ),
        source_id="source-test", document_id="document-test", evidence_ids=("evidence-test",),
        extraction_method=ExtractionMethod.IXBRL_DIRECT,
        availability_status=AvailabilityStatus.AVAILABLE, processing_run_id="run-test",
    )


@pytest.fixture
def beliefs() -> BeliefDistribution:
    """Supplied components for contract tests, never computed risk values."""
    return BeliefDistribution(
        low_belief=Decimal("0.2"), high_belief=Decimal("0.3"), unknown_belief=Decimal("0.5"),
    )


@pytest.fixture
def reliability(timestamp: datetime) -> ReliabilityResult:
    """Supplied structural M4 output, without calculating any component."""
    return ReliabilityResult(
        reliability_id="reliability-test", fact_ids=("fact-test",), evidence_ids=("evidence-test",),
        source_quality_s=Decimal("0.8"), extraction_quality_e=Decimal("0.8"),
        validation_factor_v=Decimal("0"), conflict_factor_c=Decimal("0"),
        base_reliability=Decimal("0.64"), validated_reliability=Decimal("0.64"),
        final_reliability_r=Decimal("0.64"), hard_fail=False, reliability_model_version="1",
        calculated_at=timestamp, processing_run_id="run-test",
    )


@pytest.fixture
def variable(timestamp: datetime, beliefs: BeliefDistribution) -> VariableResult:
    """Supplied leaf result shape; no transformation is performed in this fixture."""
    return VariableResult(
        variable_result_id="variable-test", assessment_id="assessment-test", variable_code="F2.2",
        raw_value=Decimal("1.25"), unit="ratio", reliability_id="reliability-test",
        reliability_r=Decimal("0.5"), final_belief=beliefs,
        availability_status=AvailabilityStatus.AVAILABLE, risk_model_version="1",
        reliability_model_version="1", calculated_at=timestamp,
    )
