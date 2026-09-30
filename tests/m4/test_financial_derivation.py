"""Focused M4.2b derivation-integrity and completeness tests."""

from datetime import date
from decimal import Decimal

from risk_intelligence.domain.enums import (
    AvailabilityStatus, ComparabilityStatus, EvidenceUse, ExtractionMethod, PeriodType,
    ValidationRole, ValidationStatus, ValidationStrength,
)
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.validation.financial import FinancialProvenance
from risk_intelligence.validation.financial_derivation import (
    FinancialAccountingCrossCheckRule, FinancialCompletenessRule,
    FinancialDerivationEvidence, FinancialDerivationIntegrityRule,
)
from risk_intelligence.validation.policy import (
    VALIDATION_FACTOR, classify_support,
)
from risk_intelligence.ingestion.accounts.models import CompletenessProof, SourceFinancialFact


PERIOD = ReportingPeriod(
    period_type=PeriodType.INSTANT,
    period_end=date(2025, 12, 31),
    comparability_status=ComparabilityStatus.COMPARABLE,
)


def source(identity: str, value: str, evidence: str) -> SourceFinancialFact:
    return SourceFinancialFact(
        source_fact_id=identity, document_id="d", evidence_id=evidence,
        source_concept="structure:component", source_label=identity, raw_value=value,
        value=Decimal(value), availability_status=AvailabilityStatus.AVAILABLE,
        currency="GBP", unit="GBP", context_ref="page-1", entity_identifier="ZZ000003",
        entity_scheme="companies-house", period=PERIOD, period_role="CURRENT",
        extraction_method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC,
        parser_version="financial-statement-structure-v4", page=1,
        statement_context="Company balance sheet",
    )


def derived(value: str = "30") -> FinancialFact:
    return FinancialFact(
        financial_fact_id="f", company_id="c", company_number="ZZ000003",
        canonical_concept="TOTAL_ASSETS", source_concept="evidence-grounded-expression",
        value_numeric=Decimal(value), currency="GBP", unit="GBP", period=PERIOD,
        source_id="s", document_id="d", evidence_ids=("e1", "e2", "proof"),
        extraction_method=ExtractionMethod.DERIVED,
        availability_status=AvailabilityStatus.AVAILABLE, processing_run_id="r",
    )


def context(fact: FinancialFact, lineage: FinancialDerivationEvidence):
    base = FinancialProvenance(fact=fact).analytical_input("ZZ000003", date(2026, 9, 30))
    return lineage.attach(base)


def lineage(*, proof: CompletenessProof | None = None) -> FinancialDerivationEvidence:
    return FinancialDerivationEvidence(
        canonical_fact_id="f", origin="DERIVED", mapping_version="financial-mapping-v1",
        derivation_version="financial-interpretation-v1", derivation_rule="ASSET_SIDE",
        components=(source("a", "10", "e1"), source("b", "20", "e2")), proof=proof,
    )


def complete_proof() -> CompletenessProof:
    return CompletenessProof(
        proof_id="proof", target="TOTAL_ASSETS", source_fact_ids=("a", "b"),
        document_id="d", page=1, row_start=1, row_end=10,
        evidence_text="Synthetic complete Company asset side", relationship="ASSET_SIDE",
    )


def test_exact_derived_value_reproduces() -> None:
    outcome = FinancialDerivationIntegrityRule().execute(context(derived(), lineage()))
    assert outcome.result == ValidationStatus.PASS


def test_arithmetic_mismatch_is_hard_failure() -> None:
    outcome = FinancialDerivationIntegrityRule().execute(context(derived("31"), lineage()))
    assert outcome.result == ValidationStatus.FAIL
    assert outcome.hard_fail


def test_duplicate_component_fails_closed() -> None:
    item = source("a", "10", "e1")
    evidence = lineage().model_copy(update={"components": (item, item)})
    outcome = FinancialDerivationIntegrityRule().execute(context(derived("20"), evidence))
    assert outcome.result == ValidationStatus.FAIL


def test_direct_observation_is_not_applicable() -> None:
    fact = derived().model_copy(update={"extraction_method": ExtractionMethod.PDF_NATIVE_DETERMINISTIC})
    evidence = FinancialDerivationEvidence(
        canonical_fact_id="f", origin="DIRECT", mapping_version="financial-mapping-v1"
    )
    outcome = FinancialDerivationIntegrityRule().execute(context(fact, evidence))
    assert outcome.result == ValidationStatus.NOT_APPLICABLE


def test_required_completeness_proof_passes() -> None:
    proof = complete_proof()
    outcome = FinancialCompletenessRule().execute(context(derived(), lineage(proof=proof)))
    assert outcome.result == ValidationStatus.PASS


def test_missing_required_completeness_is_inconclusive_hard_failure() -> None:
    outcome = FinancialCompletenessRule().execute(context(derived(), lineage()))
    assert outcome.result == ValidationStatus.INCONCLUSIVE
    assert outcome.hard_fail


def test_wrong_component_population_fails_completeness() -> None:
    proof = complete_proof().model_copy(update={"source_fact_ids": ("a",)})
    outcome = FinancialCompletenessRule().execute(context(derived(), lineage(proof=proof)))
    assert outcome.result == ValidationStatus.FAIL
    assert outcome.hard_fail


def accounting_proof() -> CompletenessProof:
    return complete_proof().model_copy(
        update={"cross_check_ids": ("liability", "subtotal")}
    )


def accounting_lineage(
        *,
        reported_subtotal: str = "25",
) -> FinancialDerivationEvidence:
    proof = accounting_proof()
    return lineage(proof=proof).model_copy(
        update={
            "cross_checks": (
                source("liability", "5", "e-liability"),
                source("subtotal", reported_subtotal, "e-subtotal"),
            )
        }
    )


def accounting_fact() -> FinancialFact:
    return derived().model_copy(
        update={
            "evidence_ids": (
                "e1", "e2", "proof", "e-liability", "e-subtotal",
            )
        }
    )


def test_accounting_cross_check_is_strong_independent_support() -> None:
    evidence = accounting_lineage()
    analytical = context(accounting_fact(), evidence)

    # Only derivation operands construct TOTAL_ASSETS.  The accounting
    # observations remain eligible as genuinely independent validation.
    assert set(analytical.construction_evidence_ids) == {"e1", "e2"}

    outcome = FinancialAccountingCrossCheckRule().execute(analytical)

    assert outcome.result == ValidationStatus.PASS
    assert outcome.role == ValidationRole.SUPPORT
    assert outcome.evidence_use == EvidenceUse.INDEPENDENT_VALIDATION
    assert outcome.validation_strength_candidate == ValidationStrength.STRONG
    assert outcome.independence_group == (
        "accounting-identity:assets-less-current-liabilities"
    )
    assert set(outcome.evidence_ids) == {"e-liability", "e-subtotal"}
    assert not set(outcome.evidence_ids) & set(
        analytical.construction_evidence_ids
    )


def test_missing_accounting_cross_check_is_not_applicable() -> None:
    outcome = FinancialAccountingCrossCheckRule().execute(
        context(derived(), lineage(proof=complete_proof()))
    )

    assert outcome.result == ValidationStatus.NOT_APPLICABLE
    assert outcome.validation_strength_candidate == ValidationStrength.NONE


def test_accounting_mismatch_cannot_provide_validation_uplift() -> None:
    outcome = FinancialAccountingCrossCheckRule().execute(
        context(accounting_fact(), accounting_lineage(reported_subtotal="24"))
    )

    assert outcome.result == ValidationStatus.FAIL
    assert outcome.role == ValidationRole.SUPPORT
    assert outcome.validation_strength_candidate == ValidationStrength.NONE
    assert outcome.evidence_use != EvidenceUse.INDEPENDENT_VALIDATION


def test_accounting_cross_check_drives_frozen_strong_validation_factor() -> None:
    analytical = context(accounting_fact(), accounting_lineage())
    outcome = FinancialAccountingCrossCheckRule().execute(analytical)

    support = classify_support(
        (outcome,),
        analytical.construction_evidence_ids,
    )

    assert support.strength == ValidationStrength.STRONG
    assert support.outcomes == (outcome,)
    assert VALIDATION_FACTOR[support.strength] == Decimal("0.60")


def test_construction_reuse_cannot_create_validation_uplift() -> None:
    analytical = context(accounting_fact(), accounting_lineage())
    outcome = FinancialAccountingCrossCheckRule().execute(analytical)

    support = classify_support(
        (outcome,),
        analytical.construction_evidence_ids + outcome.evidence_ids,
    )

    assert support.strength == ValidationStrength.NONE
    assert support.outcomes == ()
    assert VALIDATION_FACTOR[support.strength] == Decimal("0.00")
