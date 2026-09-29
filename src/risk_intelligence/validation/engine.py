"""Explicit rule registration and deterministic, in-memory validation execution."""

from typing import Protocol

from risk_intelligence.domain.enums import AdmissibilityReason, AvailabilityStatus, ValidationRole, ValidationStatus
from risk_intelligence.domain.facts import CodesValue
from risk_intelligence.domain.validation import (
    AdmissionFailure, AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField, ValidationReport,
)


class ValidationRule(Protocol):
    """A pure, individually testable rule supplied by application code, never loaded dynamically."""

    @property
    def definition(self) -> RuleDefinition:
        """Immutable identity, applicability, required fields and role."""
        ...

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Return a diagnostic without changing context or performing external I/O."""
        ...


class RuleRegistry:
    """One implementation/version per rule ID in an explicitly versioned ruleset.

    Re-registering the identical object/definition is an idempotent no-op. Any
    other registration for that ID fails; select a new registry/ruleset to change
    versions. Rule IDs determine order, independent of registration order.
    """

    def __init__(self, ruleset_version: str) -> None:
        if not isinstance(ruleset_version, str) or not ruleset_version.strip():
            raise ValueError('Ruleset version must be nonblank text')
        self._version = ruleset_version
        self._rules: dict[str, tuple[RuleDefinition, ValidationRule]] = {}
        self._sealed = False

    @property
    def ruleset_version(self) -> str:
        """Version copied into every report; callers cannot replace it in place."""
        return self._version

    def register(self, rule: ValidationRule) -> None:
        """Register a trusted implementation, rejecting ambiguous or changed identities."""
        definition = RuleDefinition.model_validate(rule.definition)
        existing = self._rules.get(definition.rule_id)
        if existing is not None and (existing[0] != definition or existing[1] is not rule):
            raise ValueError('Incompatible duplicate rule registration')
        if self._sealed and existing is None:
            raise ValueError('Ruleset already used; create a new versioned registry')
        self._rules[definition.rule_id] = (definition, rule)

    def applicable(self, input_type: str) -> tuple[ValidationRule, ...]:
        """Seal membership and return stable ID order, detecting metadata mutation."""
        self._sealed = True
        applicable = []
        for identity in sorted(self._rules):
            definition, rule = self._rules[identity]
            if RuleDefinition.model_validate(rule.definition) != definition:
                raise ValueError('Registered rule definition changed')
            if input_type in definition.applies_to:
                applicable.append(rule)
        return tuple(applicable)


class ValidationEngine:
    """Collect rule outcomes and typed exclusions without assigning risk or reliability."""

    def __init__(self, registry: RuleRegistry) -> None:
        self.registry = registry

    def validate(self, context: AnalyticalInput) -> ValidationReport:
        """Execute applicable rules; missing required inputs remain inconclusive.

        A missing mandatory gate input is an explicit hard exclusion, whereas a
        missing optional supporting input supplies no bonus. Rule exceptions and
        malformed diagnostics propagate; they never become a passing result.
        """
        context = AnalyticalInput.model_validate(context)
        available = {field.name for field in context.fields if field.value.value is not None}
        failures = list(context.admission_failures)
        if context.availability_status != AvailabilityStatus.AVAILABLE or not context.evidence_ids:
            code = (AdmissibilityReason.NON_COMPARABLE_PERIOD
                    if context.availability_status == AvailabilityStatus.NON_COMPARABLE
                    else AdmissibilityReason.MISSING_REQUIRED_EVIDENCE)
            failures.append(AdmissionFailure(code=code,
                reason='Analytical evidence unavailable: '+context.availability_status.value
                    if context.availability_status != AvailabilityStatus.AVAILABLE
                    else 'No evidence identifiers supplied for analytical input'))
        outcomes = []
        for rule in self.registry.applicable(context.input_type):
            definition = RuleDefinition.model_validate(rule.definition)
            missing = tuple(sorted(set(definition.required_inputs) - available))
            if missing:
                outcome = RuleOutcome(rule_id=definition.rule_id, rule_version=definition.rule_version,
                    result=ValidationStatus.INCONCLUSIVE, role=definition.role,
                    reason='Required rule inputs are missing',
                    structured_details=(ValidationField(name='missing_inputs', value=CodesValue(value=missing)),),
                    failure_code=AdmissibilityReason.MISSING_REQUIRED_EVIDENCE
                        if definition.role == ValidationRole.HARD_FAIL else None)
            else:
                outcome = RuleOutcome.model_validate(rule.execute(context))
            if (rule.definition != definition or outcome.rule_id != definition.rule_id
                    or outcome.rule_version != definition.rule_version or outcome.role != definition.role):
                raise ValueError('Rule outcome/definition identity or role mismatch')
            if not set(outcome.evidence_ids) <= set(context.evidence_ids):
                raise ValueError('Rule refers to evidence outside supplied context')
            outcomes.append(outcome)
            if outcome.hard_fail:
                failures.append(AdmissionFailure(code=outcome.failure_code,
                    reason=outcome.reason, evidence_ids=outcome.evidence_ids))
        failures = sorted(set(failures), key=lambda failure: failure.model_dump_json())
        return ValidationReport(context=context, ruleset_version=self.registry.ruleset_version,
                                outcomes=tuple(outcomes), failures=tuple(failures))
