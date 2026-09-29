"""Frozen heuristic values, independent support and exact reliability calculations."""

from decimal import Decimal, localcontext
from itertools import permutations

import pytest
from pydantic import ValidationError

from risk_intelligence.domain.enums import (
    AdmissibilityReason, ConflictLevel, ConflictResolution, CriticalTransformation,
    EvidenceUse, SourceType, ValidationRole, ValidationStatus, ValidationStrength,
)
from risk_intelligence.domain.reliability import ConflictState, ReliabilityAssessment, ReliabilityComponents
from risk_intelligence.domain.validation import AdmissionFailure, RuleOutcome, ValidationReport
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.policy import (
    SOURCE_QUALITY, assess_reliability, calculate_reliability, classify_support,
    source_quality, transformation_quality,
)
from test_framework import context


def support(identity: str = 'support', *, strength: ValidationStrength = ValidationStrength.MEANINGFUL,
            group: str = 'relationship', use: EvidenceUse = EvidenceUse.INDEPENDENT_VALIDATION,
            evidence: tuple[str, ...] = ('independent',)) -> RuleOutcome:
    """A synthetic domain rule's explicit support assertion, not discovered by policy."""
    return RuleOutcome(rule_id=identity,rule_version='v1',result=ValidationStatus.PASS,
        role=ValidationRole.SUPPORT,validation_strength_candidate=strength,evidence_use=use,
        independence_group=group,evidence_ids=evidence,reason='Synthetic independent accounting relationship')


def report(outcomes: tuple[RuleOutcome, ...] = ()) -> ValidationReport:
    """Preserve the same input and ruleset when testing policy in isolation."""
    return ValidationReport(context=context(),ruleset_version='synthetic-rules-v1',outcomes=outcomes,failures=())


def conflict(level: ConflictLevel = ConflictLevel.NONE,
             resolution: ConflictResolution = ConflictResolution.NONE) -> ConflictState:
    """Explicit classification supplied by future domain rules."""
    return ConflictState(level=level,resolution=resolution,reason='Synthetic conflict classification',
                         evidence_ids=('independent',) if resolution not in
                         (ConflictResolution.NONE,ConflictResolution.UNRESOLVED) else ())


@pytest.mark.parametrize('source,expected', [
    (SourceType.COMPANIES_HOUSE_API,'0.98'), (SourceType.COMPANIES_HOUSE_IXBRL,'0.97'),
    (SourceType.COMPANIES_HOUSE_PDF,'0.95'), (SourceType.OFFICIAL_WEBSITE,'0.85'),
])
def test_frozen_sources(source: SourceType, expected: str) -> None:
    assert source_quality(source) == Decimal(expected)


def test_unmapped_source_and_transformation_and_mutation_rejected() -> None:
    with pytest.raises(ValueError,match='Unmapped'):
        source_quality('UNMAPPED')
    with pytest.raises(ValueError,match='Unmapped'):
        transformation_quality('UNMAPPED')
    with pytest.raises(TypeError):
        SOURCE_QUALITY[SourceType.COMPANIES_HOUSE_API] = Decimal('1')


@pytest.mark.parametrize('transformation,expected', [
    (CriticalTransformation.STRUCTURED_DETERMINISTIC,'0.99'),
    (CriticalTransformation.TAGGED_IXBRL_DETERMINISTIC,'0.98'),
    (CriticalTransformation.NATIVE_PDF_DETERMINISTIC,'0.95'),
    (CriticalTransformation.OCR_DETERMINISTIC,'0.85'),
    (CriticalTransformation.GROUNDED_LLM_SEMANTIC,'0.85'),
    (CriticalTransformation.COMPLEX_LLM_INTERPRETATION,'0.75'),
    (CriticalTransformation.UNSUPPORTED_LLM_NUMERIC,'0'),
])
def test_frozen_transformations_and_unsupported_hard_failure(transformation: CriticalTransformation, expected: str) -> None:
    result = assess_reliability(report(),SourceType.COMPANIES_HOUSE_PDF,transformation,conflict())
    assert result.calculation.components.e == Decimal(expected)
    if transformation == CriticalTransformation.UNSUPPORTED_LLM_NUMERIC:
        assert not result.calculation.supported_analytical_evidence
        assert result.calculation.reliability_r == 0
        assert result.calculation.failures[0].code == AdmissibilityReason.UNSUPPORTED_LLM_NUMERIC
    else:
        assert result.calculation.supported_analytical_evidence


@pytest.mark.parametrize('strength,expected', [
    (ValidationStrength.NONE,'0.00'), (ValidationStrength.MEANINGFUL,'0.30'),
    (ValidationStrength.STRONG,'0.60'),
])
def test_explicit_strength_values(strength: ValidationStrength, expected: str) -> None:
    result = assess_reliability(report((support(strength=strength),)),SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,conflict())
    assert result.calculation.components.v == Decimal(expected)


def test_correlated_or_multiple_meaningful_checks_do_not_become_strong() -> None:
    correlated = (support('a'),support('b'))
    selected = classify_support(correlated)
    assert selected.strength == ValidationStrength.MEANINGFUL and len(selected.outcomes) == 1
    independent = (support('a'),support('b',group='different',evidence=('other',)))
    selected = classify_support(independent)
    assert selected.strength == ValidationStrength.MEANINGFUL and len(selected.outcomes) == 2


@pytest.mark.parametrize('use', [EvidenceUse.CONSTRUCTION, EvidenceUse.ADMISSION_ONLY])
def test_admission_and_construction_only_checks_cannot_self_validate(use: EvidenceUse) -> None:
    assert classify_support((support(strength=ValidationStrength.STRONG,use=use),)).strength == ValidationStrength.NONE


def test_constructing_evidence_cannot_be_relabelled_as_independent() -> None:
    outcome = support(strength=ValidationStrength.STRONG,evidence=('construction',))
    assert classify_support((outcome,),('construction',)).strength == ValidationStrength.NONE
    # Sharing one operand does not erase separately grounded corroborating evidence.
    independent = support(strength=ValidationStrength.STRONG,evidence=('construction','independent'))
    assert classify_support((independent,),('construction',)).strength == ValidationStrength.STRONG


def test_support_selection_is_order_invariant_and_retains_reasons() -> None:
    outcomes = (support('z'),support('a'),support('strong',group='separate',strength=ValidationStrength.STRONG))
    results = [classify_support(ordering) for ordering in permutations(outcomes)]
    assert all(result == results[0] for result in results)
    assert results[0].strength == ValidationStrength.STRONG
    assert {o.rule_id for o in results[0].outcomes} == {'a','strong'}
    assert all(o.reason and o.evidence_ids and o.rule_version for o in results[0].outcomes)


def test_invalid_support_claims_and_duplicate_outcomes_rejected() -> None:
    for changes in ({'result':ValidationStatus.FAIL}, {'independence_group':None},
                    {'evidence_ids':()}, {'role':ValidationRole.INFORMATIONAL}):
        with pytest.raises(ValidationError):
            RuleOutcome.model_validate(support().model_dump() | changes)
    with pytest.raises(ValueError,match='Duplicate'):
        classify_support((support(),support()))
    assert classify_support(()).strength == ValidationStrength.NONE


@pytest.mark.parametrize('level,resolution,expected', [
    (ConflictLevel.NONE,ConflictResolution.NONE,'0'),
    (ConflictLevel.PARTIAL_UNRESOLVED,ConflictResolution.UNRESOLVED,'0.30'),
    (ConflictLevel.SERIOUS_UNRESOLVED,ConflictResolution.UNRESOLVED,'1'),
])
def test_conflict_values_and_serious_exclusion(level: ConflictLevel, resolution: ConflictResolution, expected: str) -> None:
    result = assess_reliability(report(),SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,conflict(level,resolution))
    assert result.calculation.components.c == Decimal(expected)
    assert result.calculation.supported_analytical_evidence == (level != ConflictLevel.SERIOUS_UNRESOLVED)


@pytest.mark.parametrize('resolution', [ConflictResolution.RESTATEMENT, ConflictResolution.SUPERSEDED,
    ConflictResolution.EXTRACTION_ERROR, ConflictResolution.ROUNDING_EXPLAINED,
    ConflictResolution.SCOPE_DIFFERENCE, ConflictResolution.PERIOD_DIFFERENCE, ConflictResolution.UNIT_DIFFERENCE])
def test_resolved_conflicts_retain_provenance_without_penalty(resolution: ConflictResolution) -> None:
    result = assess_reliability(report(),SourceType.COMPANIES_HOUSE_API,
        CriticalTransformation.STRUCTURED_DETERMINISTIC,conflict(resolution=resolution))
    assert result.conflict.resolution == resolution
    assert resolution.value in result.conflict_reason
    assert result.calculation.components.c == 0
    assert result.calculation.reliability_r == Decimal('0.9702')


@pytest.mark.parametrize('level,resolution', [(ConflictLevel.NONE,ConflictResolution.UNRESOLVED),
    (ConflictLevel.SERIOUS_UNRESOLVED,ConflictResolution.RESTATEMENT)])
def test_inconsistent_conflict_classification_rejected(level: ConflictLevel, resolution: ConflictResolution) -> None:
    with pytest.raises(ValidationError):
        conflict(level,resolution)


def test_resolved_conflict_requires_evidence_and_cannot_reference_other_population() -> None:
    with pytest.raises(ValidationError,match='supporting evidence'):
        ConflictState(level=ConflictLevel.NONE,resolution=ConflictResolution.RESTATEMENT,reason='Unsubstantiated')
    supplied = ConflictState(level=ConflictLevel.NONE,resolution=ConflictResolution.RESTATEMENT,
                             reason='Wrong source',evidence_ids=('unrelated',))
    with pytest.raises(ValueError,match='outside'):
        assess_reliability(report(),SourceType.COMPANIES_HOUSE_API,
                           CriticalTransformation.STRUCTURED_DETERMINISTIC,supplied)


@pytest.mark.parametrize('s,e,v,c,base,uplift,final', [
    ('0.98','0.99','0','0','0.9702','0.9702','0.9702'),
    ('0.98','0.99','0.30','0','0.9702','0.97914','0.97914'),
    ('0.98','0.99','0.30','0.30','0.9702','0.97914','0.685398'),
    ('0.98','0.99','0.60','1','0.9702','0.98808','0'),
    ('1','1','0.60','0','1','1','0.99'),
    ('0.123456789','0.987654321','0.30','0.30','0.121932631112635269','0.3853528417788446883','0.26974698924519128181'),
])
def test_exact_formula_independent_of_decimal_context(s: str,e: str,v: str,c: str,base: str,uplift: str,final: str) -> None:
    with localcontext() as caller:
        caller.prec = 2
        result = calculate_reliability(ReliabilityComponents(s=Decimal(s),e=Decimal(e),v=Decimal(v),c=Decimal(c)))
    assert result.r_base == Decimal(base)
    assert result.r_v == Decimal(uplift)
    assert result.reliability_r == Decimal(final)
    assert result.policy_version == 'm4-reliability-v1'
    if c == '1':
        assert not result.supported_analytical_evidence


@pytest.mark.parametrize('value',[0.98,Decimal('NaN'),Decimal('-0.01'),Decimal('1.01')])
def test_formula_rejects_inexact_or_out_of_range_values(value: object) -> None:
    with pytest.raises(ValidationError):
        ReliabilityComponents(s=value,e=Decimal('0.99'),v=Decimal('0'),c=Decimal('0'))


def test_hard_failure_does_not_become_valid_low_confidence_and_chain_is_not_multiplied() -> None:
    failure = AdmissionFailure(code=AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,reason='Incomplete population')
    validation = ValidationEngine(RuleRegistry('synthetic-v1')).validate(context(admission_failures=(failure,)))
    result = assess_reliability(validation,SourceType.COMPANIES_HOUSE_PDF,
        CriticalTransformation.GROUNDED_LLM_SEMANTIC,conflict(),('PDF','OCR','LLM','ADMISSION'))
    assert result.calculation.r_base == Decimal('0.8075')
    assert result.calculation.reliability_r == 0 and not result.calculation.supported_analytical_evidence
    assert result.calculation.failures == (failure,)
    assert result.transformation_chain == ('PDF','OCR','LLM','ADMISSION')
    assert result.source_reason and result.transformation_reason and result.support.reason and result.formula_reason
    assert ReliabilityAssessment.model_validate_json(result.model_dump_json()) == result
