"""Derivation integrity and required completeness validation for financial facts."""

from decimal import Decimal, localcontext
from typing import Literal

from risk_intelligence.domain.common import Contract, Text
from risk_intelligence.domain.enums import (
    AdmissibilityReason, AvailabilityStatus, EvidenceUse, ExtractionMethod,
    ValidationRole, ValidationStatus, ValidationStrength,
)
from risk_intelligence.domain.facts import CodesValue, TextValue, FinancialFact
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from risk_intelligence.ingestion.accounts.models import CompletenessProof, SourceFinancialFact
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.connection import IntegrityError

from .engine import RuleRegistry
from .financial import FinancialGroundingRule, FinancialIdentityRule, _outcome, _provenance
from .financial_period import FinancialPeriodRule
from .financial_scope import FinancialScopeRule
from .financial_units import FinancialCurrencyRule, FinancialUnitScaleRule
from .financial_semantic import FinancialSemanticConsistencyRule


class FinancialDerivationEvidence(Contract):
    """SQL-restorable M3 lineage needed to reproduce a canonical derivation."""

    version: Literal["financial-derivation-evidence-v1"] = "financial-derivation-evidence-v1"
    canonical_fact_id: Text
    origin: Literal["DIRECT", "DERIVED"]
    mapping_version: Text
    derivation_version: Text | None = None
    derivation_rule: Text | None = None
    components: tuple[SourceFinancialFact, ...] = ()
    proof: CompletenessProof | None = None
    cross_checks: tuple[SourceFinancialFact, ...] = ()

    def attach(self, context: AnalyticalInput) -> AnalyticalInput:
        fields = context.fields + (
            ValidationField(
                name="financial_derivation_evidence",
                value=TextValue(value=self.model_dump_json()),
            ),
        )
        construction = (
            tuple(component.evidence_id for component in self.components)
            if self.origin == "DERIVED"
            else context.construction_evidence_ids
        )
        return AnalyticalInput(**(
            context.model_dump()
            | {
                "fields": fields,
                "construction_evidence_ids": construction,
            }
        ))


def load_derivation_evidence(
        repository: AccountsRepository,
        canonical_fact_id: str,
) -> FinancialDerivationEvidence:
    """Reconstruct M4 derivation evidence exclusively from immutable SQL state."""
    restored = repository.get_observation_lineage(canonical_fact_id)
    if restored is None:
        raise IntegrityError("Canonical financial observation has no persisted lineage")

    lineage, components = restored
    origin = lineage["origin"]
    proof = repository.get_derivation_proof(canonical_fact_id)
    cross_checks = ()
    if proof is not None:
        restored_checks = tuple(
            repository.get_source(identity)
            for identity in proof.cross_check_ids
        )
        if any(item is None for item in restored_checks):
            raise IntegrityError("Derivation proof references missing cross-check source fact")
        cross_checks = restored_checks

    if origin == "DIRECT":
        if proof is not None:
            raise IntegrityError("Direct financial observation cannot have derivation proof")
    elif origin != "DERIVED":
        raise IntegrityError("Unsupported financial observation lineage origin")

    # Missing proof is an admissibility outcome owned by FinancialCompletenessRule,
    # not corrupt SQL lineage. Preserve it so other company variables still run.
    return FinancialDerivationEvidence(
        canonical_fact_id=canonical_fact_id,
        origin=origin,
        mapping_version=lineage["mapping_version"],
        derivation_version=lineage["derivation_version"],
        derivation_rule=lineage["derivation_rule"],
        components=components,
        proof=proof,
        cross_checks=cross_checks,
    )


def _evidence(context: AnalyticalInput) -> FinancialDerivationEvidence:
    field = next(f for f in context.fields if f.name == "financial_derivation_evidence")
    if not isinstance(field.value, TextValue) or field.value.value is None:
        raise ValueError("Financial derivation evidence requires a typed JSON text payload")
    return FinancialDerivationEvidence.model_validate_json(field.value.value)


def _details(evidence: FinancialDerivationEvidence) -> tuple[ValidationField, ...]:
    return (
        ValidationField(name="origin", value=TextValue(value=evidence.origin)),
        ValidationField(name="derivation_version", value=TextValue(value=evidence.derivation_version)),
        ValidationField(name="derivation_rule", value=TextValue(value=evidence.derivation_rule)),
        ValidationField(
            name="component_source_fact_ids",
            value=CodesValue(value=tuple(component.source_fact_id for component in evidence.components)),
        ),
        ValidationField(
            name="completeness_proof_id",
            value=TextValue(value=evidence.proof.proof_id if evidence.proof else None),
        ),
    )


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = max(
            50,
            sum(len(value.as_tuple().digits) + abs(value.as_tuple().exponent) for value in values) + 10,
        )
        return sum(values, Decimal(0))


def reviewed_subtotal_value(lineage: FinancialDerivationEvidence, fact: FinancialFact) -> Decimal | None:
    """Reproduce only the existing M3 subtotal identities with exact source lineage."""
    from risk_intelligence.ingestion.accounts.derivation import (
        BALANCE_SHEET_DERIVATION_VERSION, derive_balance_sheet_subtotals,
    )
    if lineage.derivation_version != BALANCE_SHEET_DERIVATION_VERSION:
        return None
    for candidate, ids, rule in derive_balance_sheet_subtotals(lineage.components,
            company_id=fact.company_id, source_id=fact.source_id,
            run_id=fact.processing_run_id, mapping_version=lineage.mapping_version):
        if (candidate.canonical_concept == fact.canonical_concept
                and ids == tuple(c.source_fact_id for c in lineage.components)
                and rule == lineage.derivation_rule
                and candidate.evidence_ids == fact.evidence_ids):
            return candidate.value_numeric
    return None


class FinancialDerivationIntegrityRule:
    """Reproduce admitted M3 additive derivations from immutable SQL lineage."""

    @property
    def definition(self) -> RuleDefinition:
        return RuleDefinition(
            rule_id="financial.derivation_integrity",
            rule_version="v2",
            applies_to=("FINANCIAL_FACT",),
            required_inputs=("financial_provenance", "financial_derivation_evidence"),
            role=ValidationRole.HARD_FAIL,
        )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        records = _provenance(context)
        lineage = _evidence(context)
        fact = records.fact
        details = _details(lineage)

        if lineage.canonical_fact_id != fact.financial_fact_id:
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Derivation lineage belongs to a different canonical observation",
                details, AdmissibilityReason.IDENTITY_FAILURE,
            )
        if lineage.origin == "DIRECT":
            if lineage.derivation_version is not None or lineage.derivation_rule is not None:
                return _outcome(
                    self.definition, context, ValidationStatus.FAIL,
                    "Direct observation carries contradictory derivation metadata",
                    details, AdmissibilityReason.IDENTITY_FAILURE,
                )
            return _outcome(
                self.definition, context, ValidationStatus.NOT_APPLICABLE,
                "Direct observation requires no derivation reproduction", details,
            )

        if fact.extraction_method != ExtractionMethod.DERIVED:
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Derived lineage contradicts the canonical extraction method",
                details, AdmissibilityReason.IDENTITY_FAILURE,
            )
        if not lineage.derivation_version or not lineage.derivation_rule or not lineage.components:
            return _outcome(
                self.definition, context, ValidationStatus.INCONCLUSIVE,
                "Derived observation lacks required structured formula/component provenance", details,
            )

        component_ids = tuple(component.source_fact_id for component in lineage.components)
        if len(set(component_ids)) != len(component_ids):
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Derived observation repeats a source component and may double count it",
                details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
            )

        unresolved = False
        values: list[Decimal] = []
        component_evidence: list[str] = []
        for component in lineage.components:
            if component.value is None or component.availability_status != AvailabilityStatus.AVAILABLE:
                unresolved = True
                continue
            if (
                component.document_id != fact.document_id
                or component.entity_identifier != fact.company_number
                or component.period != fact.period
                or component.currency != fact.currency
                or component.unit != fact.unit
                or component.dimensions
            ):
                return _outcome(
                    self.definition, context, ValidationStatus.FAIL,
                    "A required derivation component has incompatible structured context",
                    details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
                )
            values.append(component.value)
            component_evidence.append(component.evidence_id)

        if unresolved or len(values) != len(lineage.components):
            return _outcome(
                self.definition, context, ValidationStatus.INCONCLUSIVE,
                "One or more derivation components are unavailable or unresolved", details,
            )

        claimed_prefix = tuple(fact.evidence_ids[: len(component_evidence)])
        if claimed_prefix != tuple(component_evidence):
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Canonical evidence order does not match persisted ordered derivation components",
                details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
            )

        reproduced = reviewed_subtotal_value(lineage, fact)
        if reproduced is None:
            reproduced = _sum(tuple(values))
        details += (
            ValidationField(name="reproduced_value", value=TextValue(value=str(reproduced))),
            ValidationField(name="stored_value", value=TextValue(value=str(fact.value_numeric))),
        )
        if fact.value_numeric is None:
            return _outcome(
                self.definition, context, ValidationStatus.INCONCLUSIVE,
                "Derived canonical observation has no numeric value to reproduce", details,
            )
        if reproduced != fact.value_numeric:
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Exact deterministic reproduction disagrees with the stored derived value",
                details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
            )
        return _outcome(
            self.definition, context, ValidationStatus.PASS,
            "Stored derived value is exactly reproducible from ordered grounded components", details,
        )


class FinancialCompletenessRule:
    """Require the existing parser-verified proof for derivations that claim completeness."""

    REQUIRED_RELATIONSHIP = {
        "TOTAL_ASSETS": "ASSET_SIDE",
        "INTEREST_BEARING_DEBT": "EXHAUSTIVE_INTEREST_BEARING",
    }

    @property
    def definition(self) -> RuleDefinition:
        return RuleDefinition(
            rule_id="financial.completeness",
            rule_version="v2",
            applies_to=("FINANCIAL_FACT",),
            required_inputs=("financial_provenance", "financial_derivation_evidence"),
            role=ValidationRole.HARD_FAIL,
        )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        records = _provenance(context)
        lineage = _evidence(context)
        fact = records.fact
        details = _details(lineage)
        required = self.REQUIRED_RELATIONSHIP.get(fact.canonical_concept)

        if lineage.origin == "DIRECT" or required is None:
            return _outcome(
                self.definition, context, ValidationStatus.NOT_APPLICABLE,
                "This observation does not require a derivation completeness proof", details,
            )
        # Explicit reported subtotal identities are not an exhaustive sum of rows.
        # They need exact formula/source reproduction, not a fabricated row proof.
        subtotal = reviewed_subtotal_value(lineage, fact)
        if subtotal is not None and subtotal == fact.value_numeric:
            return _outcome(self.definition, context, ValidationStatus.PASS,
                "Reviewed reported balance-sheet subtotal identity reproduces exactly", details)
        proof = lineage.proof
        if proof is None:
            return _outcome(
                self.definition, context, ValidationStatus.INCONCLUSIVE,
                "Required structured completeness proof is not available in the M3 handoff",
                details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
            )
        component_ids = tuple(component.source_fact_id for component in lineage.components)
        if (
            proof.target != fact.canonical_concept
            or proof.relationship != required
            or proof.document_id != fact.document_id
            or proof.source_fact_ids != component_ids
        ):
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Completeness proof contradicts the canonical target, document, relationship or component population",
                details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
            )
        if proof.proof_id not in fact.evidence_ids:
            return _outcome(
                self.definition, context, ValidationStatus.FAIL,
                "Canonical observation does not retain its required completeness-proof evidence",
                details, AdmissibilityReason.REQUIRED_COMPLETENESS_FAILURE,
            )
        return _outcome(
            self.definition, context, ValidationStatus.PASS,
            "Parser-verified completeness proof matches the exact non-overlapping derivation population", details,
        )


class FinancialAccountingCrossCheckRule:
    """Use an independently reported accounting subtotal to corroborate TOTAL_ASSETS."""

    @property
    def definition(self) -> RuleDefinition:
        return RuleDefinition(
            rule_id="financial.accounting_cross_check",
            rule_version="v1",
            applies_to=("FINANCIAL_FACT",),
            required_inputs=("financial_provenance", "financial_derivation_evidence"),
            role=ValidationRole.SUPPORT,
        )

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        records = _provenance(context)
        lineage = _evidence(context)
        fact = records.fact
        details = _details(lineage)

        if (
            lineage.origin != "DERIVED"
            or fact.canonical_concept != "TOTAL_ASSETS"
            or lineage.proof is None
            or lineage.proof.relationship != "ASSET_SIDE"
            or not lineage.proof.cross_check_ids
        ):
            return RuleOutcome(
                rule_id=self.definition.rule_id,
                rule_version=self.definition.rule_version,
                role=self.definition.role,
                result=ValidationStatus.NOT_APPLICABLE,
                reason="No independent TOTAL_ASSETS accounting cross-check is available",
                structured_details=details,
            )

        if len(lineage.proof.cross_check_ids) != 2 or len(lineage.cross_checks) != 2:
            return RuleOutcome(
                rule_id=self.definition.rule_id,
                rule_version=self.definition.rule_version,
                role=self.definition.role,
                result=ValidationStatus.INCONCLUSIVE,
                reason="Accounting cross-check does not contain the required two structured observations",
                structured_details=details,
            )

        if tuple(item.source_fact_id for item in lineage.cross_checks) != lineage.proof.cross_check_ids:
            return RuleOutcome(
                rule_id=self.definition.rule_id,
                rule_version=self.definition.rule_version,
                role=self.definition.role,
                result=ValidationStatus.FAIL,
                reason="Accounting cross-check observations differ from the persisted proof",
                structured_details=details,
            )

        liability, reported = lineage.cross_checks
        checks = (liability, reported)
        if any(
            item.value is None
            or item.availability_status != AvailabilityStatus.AVAILABLE
            or item.document_id != fact.document_id
            or item.entity_identifier != fact.company_number
            or item.period != fact.period
            or item.currency != fact.currency
            or item.unit != fact.unit
            or item.dimensions
            for item in checks
        ):
            return RuleOutcome(
                rule_id=self.definition.rule_id,
                rule_version=self.definition.rule_version,
                role=self.definition.role,
                result=ValidationStatus.INCONCLUSIVE,
                reason="Accounting cross-check observations are unavailable or context-incompatible",
                structured_details=details,
            )

        if fact.value_numeric is None:
            return RuleOutcome(
                rule_id=self.definition.rule_id,
                rule_version=self.definition.rule_version,
                role=self.definition.role,
                result=ValidationStatus.INCONCLUSIVE,
                reason="TOTAL_ASSETS has no numeric value for accounting cross-check",
                structured_details=details,
            )

        expected = fact.value_numeric - liability.value
        details += (
            ValidationField(
                name="cross_check_current_liabilities",
                value=TextValue(value=str(liability.value)),
            ),
            ValidationField(
                name="cross_check_expected_subtotal",
                value=TextValue(value=str(expected)),
            ),
            ValidationField(
                name="cross_check_reported_subtotal",
                value=TextValue(value=str(reported.value)),
            ),
        )

        evidence_ids = tuple(item.evidence_id for item in checks)
        if expected != reported.value:
            return RuleOutcome(
                rule_id=self.definition.rule_id,
                rule_version=self.definition.rule_version,
                role=self.definition.role,
                result=ValidationStatus.FAIL,
                reason="Independent reported subtotal disagrees with the TOTAL_ASSETS accounting identity",
                structured_details=details,
                evidence_ids=evidence_ids,
            )

        return RuleOutcome(
            rule_id=self.definition.rule_id,
            rule_version=self.definition.rule_version,
            role=self.definition.role,
            result=ValidationStatus.PASS,
            reason="Independent reported subtotal exactly corroborates TOTAL_ASSETS",
            structured_details=details,
            evidence_ids=evidence_ids,
            evidence_use=EvidenceUse.INDEPENDENT_VALIDATION,
            validation_strength_candidate=ValidationStrength.STRONG,
            independence_group="accounting-identity:assets-less-current-liabilities",
        )


def financial_derivation_registry() -> RuleRegistry:
    """Compose M4.2a core gates with derivation integrity and completeness."""
    registry = RuleRegistry("financial-core-derivation-v1")
    for rule in (
        FinancialIdentityRule(),
        FinancialGroundingRule(),
        FinancialPeriodRule(),
        FinancialScopeRule(),
        FinancialCurrencyRule(),
        FinancialUnitScaleRule(),
        FinancialSemanticConsistencyRule(),
        FinancialDerivationIntegrityRule(),
        FinancialCompletenessRule(),
        FinancialAccountingCrossCheckRule(),
    ):
        registry.register(rule)
    return registry
