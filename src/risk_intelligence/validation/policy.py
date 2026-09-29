"""Frozen M4 v1 heuristic policies and exact, side-effect-free reliability arithmetic."""

from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext
from types import MappingProxyType

from risk_intelligence.domain.enums import (
    AdmissibilityReason, ConflictLevel, CriticalTransformation, EvidenceUse, SourceType,
    ValidationRole, ValidationStatus, ValidationStrength,
)
from risk_intelligence.domain.reliability import (
    ConflictState, ReliabilityAssessment, ReliabilityCalculation, ReliabilityComponents, ValidationSupport,
)
from risk_intelligence.domain.validation import AdmissionFailure, RuleOutcome, ValidationReport

POLICY_VERSION = 'm4-reliability-v1'
SOURCE_QUALITY = MappingProxyType({
    SourceType.COMPANIES_HOUSE_API: Decimal('0.98'),
    SourceType.COMPANIES_HOUSE_IXBRL: Decimal('0.97'),
    SourceType.COMPANIES_HOUSE_PDF: Decimal('0.95'),
    SourceType.OFFICIAL_WEBSITE: Decimal('0.85'),
})
TRANSFORMATION_QUALITY = MappingProxyType({
    CriticalTransformation.STRUCTURED_DETERMINISTIC: Decimal('0.99'),
    CriticalTransformation.TAGGED_IXBRL_DETERMINISTIC: Decimal('0.98'),
    CriticalTransformation.NATIVE_PDF_DETERMINISTIC: Decimal('0.95'),
    CriticalTransformation.OCR_DETERMINISTIC: Decimal('0.85'),
    CriticalTransformation.GROUNDED_LLM_SEMANTIC: Decimal('0.85'),
    CriticalTransformation.COMPLEX_LLM_INTERPRETATION: Decimal('0.75'),
    CriticalTransformation.UNSUPPORTED_LLM_NUMERIC: Decimal('0'),
})
VALIDATION_FACTOR = MappingProxyType({
    ValidationStrength.NONE: Decimal('0.00'),
    ValidationStrength.MEANINGFUL: Decimal('0.30'),
    ValidationStrength.STRONG: Decimal('0.60'),
})
CONFLICT_FACTOR = MappingProxyType({
    ConflictLevel.NONE: Decimal('0.00'),
    ConflictLevel.PARTIAL_UNRESOLVED: Decimal('0.30'),
    ConflictLevel.SERIOUS_UNRESOLVED: Decimal('1.00'),
})


def source_quality(source: SourceType) -> Decimal:
    """Reuse M0 source names; unknown classes fail instead of receiving a default."""
    if not isinstance(source, SourceType):
        raise ValueError('Unmapped source classification')
    return SOURCE_QUALITY[source]


def transformation_quality(transformation: CriticalTransformation) -> Decimal:
    """Return critical-stage E; unsupported numeric must also fail admission."""
    if not isinstance(transformation, CriticalTransformation):
        raise ValueError('Unmapped critical transformation')
    return TRANSFORMATION_QUALITY[transformation]


def classify_support(outcomes: tuple[RuleOutcome, ...],
                     construction_evidence_ids: tuple[str, ...] = ()) -> ValidationSupport:
    """Select explicit independent support, never promote strength by counting passes.

    One representative per independence group survives, preferring its strongest
    justified candidate and then stable rule identity. Multiple MEANINGFUL groups
    remain MEANINGFUL: a later domain rule may explicitly substantiate STRONG for
    a composite relationship. Admission reuse does not disqualify genuinely
    independent corroboration; only admission-only/construction checks are excluded.
    """
    groups: dict[str, RuleOutcome] = {}
    identities: set[tuple[str, str]] = set()
    for item in sorted(outcomes, key=lambda o: (o.rule_id, o.rule_version)):
        outcome = RuleOutcome.model_validate(item)
        identity = (outcome.rule_id, outcome.rule_version)
        if identity in identities:
            raise ValueError('Duplicate validation outcome identity')
        identities.add(identity)
        if (outcome.result != ValidationStatus.PASS or outcome.role != ValidationRole.SUPPORT
                or outcome.evidence_use != EvidenceUse.INDEPENDENT_VALIDATION
                or outcome.validation_strength_candidate == ValidationStrength.NONE
                or not set(outcome.evidence_ids) - set(construction_evidence_ids)):
            continue
        group = outcome.independence_group
        previous = groups.get(group)
        if previous is None or VALIDATION_FACTOR[outcome.validation_strength_candidate] > VALIDATION_FACTOR[previous.validation_strength_candidate]:
            groups[group] = outcome
    selected = tuple(groups[group] for group in sorted(groups))
    strength = max((o.validation_strength_candidate for o in selected),
                   key=lambda candidate: VALIDATION_FACTOR[candidate], default=ValidationStrength.NONE)
    return ValidationSupport(strength=strength, outcomes=selected,
        reason='Strongest explicit independent support candidate; correlated checks grouped, no pass-count uplift'
            if selected else 'No eligible independent validation support')


def calculate_reliability(components: ReliabilityComponents,
                          failures: tuple[AdmissionFailure, ...] = ()) -> ReliabilityCalculation:
    """Apply the frozen formula exactly, preserving intermediates and hard exclusions.

    Precision covers all input decimal places through the products, independent
    of the caller's Decimal context. There is no quantization or early rounding.
    C=1 is the frozen serious-conflict case and always withholds evidence.
    """
    components = ReliabilityComponents.model_validate(components)
    exclusions = [AdmissionFailure.model_validate(failure) for failure in failures]
    if components.c == 1 and not any(f.code == AdmissibilityReason.SERIOUS_UNRESOLVED_CONFLICT for f in exclusions):
        exclusions.append(AdmissionFailure(code=AdmissibilityReason.SERIOUS_UNRESOLVED_CONFLICT,
                                           reason='Serious unresolved conflict'))
    numbers = (components.s, components.e, components.v, components.c)
    precision = max(28, sum(max(0, -number.as_tuple().exponent) for number in numbers) + 8)
    with localcontext(Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN)):
        base = components.s * components.e
        validated = base + (1 - base) * components.v
        final = min(Decimal('0.99'), validated * (1 - components.c))
    if exclusions:
        final = Decimal('0')
    return ReliabilityCalculation(components=components, r_base=base, r_v=validated,
        reliability_r=final, failures=tuple(sorted(set(exclusions), key=lambda f:f.model_dump_json())))


def assess_reliability(validation: ValidationReport, source: SourceType,
                       transformation: CriticalTransformation, conflict: ConflictState,
                       transformation_chain: tuple[str, ...] = ()) -> ReliabilityAssessment:
    """Apply the frozen policy to supplied classifications; discover no domain conflicts.

    The full chain is retained for explanation but never multiplied. Source and
    transformation classes must already be established by evidence-grounded rules.
    """
    validation = ValidationReport.model_validate(validation)
    conflict = ConflictState.model_validate(conflict)
    if not set(conflict.evidence_ids) <= set(validation.context.evidence_ids):
        raise ValueError('Conflict references evidence outside supplied context')
    s = source_quality(source)
    e = transformation_quality(transformation)
    support = classify_support(validation.outcomes, validation.context.construction_evidence_ids)
    failures = list(validation.failures)
    if transformation == CriticalTransformation.UNSUPPORTED_LLM_NUMERIC:
        failures.append(AdmissionFailure(code=AdmissibilityReason.UNSUPPORTED_LLM_NUMERIC,
                                         reason='Unsupported model numeric evidence cannot be admitted'))
    if conflict.level == ConflictLevel.SERIOUS_UNRESOLVED:
        failures.append(AdmissionFailure(code=AdmissibilityReason.SERIOUS_UNRESOLVED_CONFLICT,
                                         reason=conflict.reason, evidence_ids=conflict.evidence_ids))
    components = ReliabilityComponents(s=s, e=e, v=VALIDATION_FACTOR[support.strength],
                                       c=CONFLICT_FACTOR[conflict.level])
    calculation = calculate_reliability(components, tuple(failures))
    return ReliabilityAssessment(validation=validation, source_type=source,
        critical_transformation=transformation, transformation_chain=transformation_chain,
        support=support, conflict=conflict, calculation=calculation,
        source_reason=f'{source.value}: S={s} under {POLICY_VERSION}',
        transformation_reason=f'{transformation.value}: E={e}; critical transformation, not stage multiplication',
        conflict_reason=f'{conflict.level.value}/{conflict.resolution.value}: C={components.c}; {conflict.reason}',
        formula_reason='r_base=S*E; r_v=r_base+(1-r_base)*V; r=min(0.99,r_v*(1-C)); hard failure overrides r to 0')
