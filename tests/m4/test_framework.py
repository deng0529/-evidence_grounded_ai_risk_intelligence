"""Synthetic rules exercise registration, exclusions, evidence and typed diagnostics."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from risk_intelligence.domain.enums import (
    AdmissibilityReason, AvailabilityStatus, ValidationRole, ValidationStatus,
)
from risk_intelligence.domain.facts import NumericValue
from risk_intelligence.domain.validation import (
    AdmissionFailure, AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField, ValidationReport,
)
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine


def context(**changes: object) -> AnalyticalInput:
    """A synthetic analytical population, not a financial/governance rule fixture."""
    values = dict(input_id='input', input_type='SYNTHETIC', company_number='ZZ000004',
        assessment_date=date(2026,9,29), evidence_ids=('construction','independent','other'),
        construction_evidence_ids=('construction',),
        fields=(ValidationField(name='amount', value=NumericValue(value=Decimal('10'))),))
    return AnalyticalInput(**(values | changes))


@dataclass(frozen=True)
class SyntheticRule:
    """Constant diagnostic used solely to isolate framework behavior."""

    definition: RuleDefinition
    result: ValidationStatus = ValidationStatus.PASS
    evidence_ids: tuple[str, ...] = ('independent',)
    failure_code: AdmissibilityReason | None = None

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Return typed synthetic diagnostics without side effects."""
        return RuleOutcome(rule_id=self.definition.rule_id, rule_version=self.definition.rule_version,
            role=self.definition.role, result=self.result, evidence_ids=self.evidence_ids,
            reason='Synthetic diagnostic', failure_code=self.failure_code,
            structured_details=(ValidationField(name='observed', value=NumericValue(value=Decimal('10'))),))


def rule(identity: str = 'rule', *, role: ValidationRole = ValidationRole.INFORMATIONAL,
         result: ValidationStatus = ValidationStatus.PASS, required: tuple[str, ...] = (),
         applies_to: tuple[str, ...] = ('SYNTHETIC',),
         failure_code: AdmissibilityReason | None = None) -> SyntheticRule:
    """Explicit registry entry, avoiding production example rules."""
    return SyntheticRule(RuleDefinition(rule_id=identity, rule_version='v1', applies_to=applies_to,
        required_inputs=required, role=role), result=result, failure_code=failure_code)


def test_registry_order_applicability_versions_and_exact_reregistration() -> None:
    first, second = rule('a'), rule('z')
    registries = []
    for ordering in ((second,first),(first,second)):
        registry = RuleRegistry('synthetic-rules-v1')
        for item in ordering:
            registry.register(item)
        registry.register(first)
        registry.register(rule('unrelated', applies_to=('OTHER',)))
        assert [r.definition.rule_id for r in registry.applicable('SYNTHETIC')] == ['a','z']
        assert not registry.applicable('ABSENT')
        registries.append(registry)
    reports = [ValidationEngine(registry).validate(context()) for registry in registries]
    assert reports[0] == reports[1]
    assert reports[0].ruleset_version == 'synthetic-rules-v1'
    with pytest.raises(ValueError, match='duplicate'):
        registries[0].register(rule('a'))
    with pytest.raises(ValueError, match='duplicate'):
        registries[0].register(replace(first, definition=first.definition.model_copy(update={'rule_version':'v2'})))


def test_used_registry_cannot_silently_change_membership_or_rule_metadata() -> None:
    registry = RuleRegistry('v1')
    item = rule()
    registry.register(item)
    registry.applicable('SYNTHETIC')
    registry.register(item)
    with pytest.raises(ValueError,match='new versioned registry'):
        registry.register(rule('new'))
    object.__setattr__(item, 'definition', item.definition.model_copy(update={'rule_version':'v2'}))
    with pytest.raises(ValueError,match='definition changed'):
        registry.applicable('SYNTHETIC')


@pytest.mark.parametrize('status', [ValidationStatus.PASS, ValidationStatus.FAIL,
                                   ValidationStatus.INCONCLUSIVE, ValidationStatus.NOT_APPLICABLE])
def test_engine_preserves_all_four_outcomes_and_structured_details(status: ValidationStatus) -> None:
    registry = RuleRegistry('rules-v1')
    registry.register(rule(result=status))
    report = ValidationEngine(registry).validate(context())
    assert report.outcomes[0].result == status
    assert report.outcomes[0].evidence_ids == ('independent',)
    assert report.outcomes[0].structured_details[0].value.value == Decimal('10')
    assert report.outcomes[0].reason == 'Synthetic diagnostic'
    assert report.admissible  # An informational FAIL is not a mandatory exclusion.
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize('code', list(AdmissibilityReason))
def test_typed_hard_failures_propagate(code: AdmissibilityReason) -> None:
    registry = RuleRegistry('rules-v1')
    registry.register(rule(role=ValidationRole.HARD_FAIL, result=ValidationStatus.FAIL, failure_code=code))
    report = ValidationEngine(registry).validate(context())
    assert not report.admissible and report.failures[0].code == code
    assert report.failures[0].evidence_ids == ('independent',)
    with pytest.raises(ValidationError, match='dropped'):
        ValidationReport.model_validate(report.model_dump() | {'failures':()})


@pytest.mark.parametrize('role', [ValidationRole.SUPPORT, ValidationRole.HARD_FAIL])
def test_missing_or_null_required_input_is_not_executed(role: ValidationRole) -> None:
    @dataclass(frozen=True)
    class ForbiddenRule(SyntheticRule):
        def execute(self, context: AnalyticalInput) -> RuleOutcome:
            raise AssertionError('Missing inputs must not execute the rule')
    registry = RuleRegistry('rules-v1')
    registry.register(ForbiddenRule(rule(role=role, required=('amount','missing')).definition))
    report = ValidationEngine(registry).validate(context(fields=(
        ValidationField(name='amount', value=NumericValue(value=None)),)))
    outcome = report.outcomes[0]
    assert outcome.result == ValidationStatus.INCONCLUSIVE
    assert outcome.structured_details[0].value.value == ('amount','missing')
    assert report.admissible == (role != ValidationRole.HARD_FAIL)


@pytest.mark.parametrize('status', [ValidationStatus.PASS, ValidationStatus.NOT_APPLICABLE])
def test_mandatory_rule_role_alone_does_not_fail(status: ValidationStatus) -> None:
    registry = RuleRegistry('rules-v1')
    registry.register(rule(role=ValidationRole.HARD_FAIL,result=status))
    assert ValidationEngine(registry).validate(context()).admissible


def test_unavailable_evidence_and_supplied_exclusions_are_not_erased() -> None:
    engine = ValidationEngine(RuleRegistry('empty-v1'))
    assert not engine.validate(context(evidence_ids=(),construction_evidence_ids=())).admissible
    report = engine.validate(context(availability_status=AvailabilityStatus.NON_COMPARABLE))
    assert report.failures[0].code == AdmissibilityReason.NON_COMPARABLE_PERIOD
    failure = AdmissionFailure(code=AdmissibilityReason.IDENTITY_FAILURE, reason='Identity mismatch')
    assert engine.validate(context(admission_failures=(failure,))).failures == (failure,)


def test_unknown_evidence_legacy_warning_and_bad_registry_metadata_rejected() -> None:
    registry = RuleRegistry('v1')
    registry.register(replace(rule(), evidence_ids=('fabricated',)))
    with pytest.raises(ValueError, match='outside'):
        ValidationEngine(registry).validate(context())
    with pytest.raises(ValidationError, match='M4 requires'):
        rule(result=ValidationStatus.WARNING).execute(context())
    with pytest.raises(ValueError):
        RuleRegistry(' ')
    with pytest.raises(ValidationError):
        RuleDefinition(rule_id='r', rule_version=' ', applies_to=(), role=ValidationRole.SUPPORT)


def test_engine_rejects_identity_mismatch_and_propagates_rule_errors() -> None:
    @dataclass(frozen=True)
    class BadRule(SyntheticRule):
        def execute(self, context: AnalyticalInput) -> RuleOutcome:
            return super().execute(context).model_copy(update={'rule_version':'wrong'})
    registry = RuleRegistry('v1')
    registry.register(BadRule(rule().definition))
    with pytest.raises(ValueError, match='mismatch'):
        ValidationEngine(registry).validate(context())
    @dataclass(frozen=True)
    class FailingRule(SyntheticRule):
        def execute(self, context: AnalyticalInput) -> RuleOutcome:
            raise RuntimeError('Synthetic rule implementation error')
    registry = RuleRegistry('v1')
    registry.register(FailingRule(rule().definition))
    with pytest.raises(RuntimeError, match='implementation error'):
        ValidationEngine(registry).validate(context())
