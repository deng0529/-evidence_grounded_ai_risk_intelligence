"""Pure financial identity and structured evidence-linkage admissibility rules."""

from datetime import date
from typing import Literal

from risk_intelligence.domain.common import Contract
from risk_intelligence.domain.enums import AdmissibilityReason, RetrievalStatus, ValidationRole, ValidationStatus
from risk_intelligence.domain.evidence import Document, EvidenceReference, Source
from risk_intelligence.domain.facts import CodesValue, FinancialFact, TextValue
from risk_intelligence.domain.validation import AnalyticalInput, RuleDefinition, RuleOutcome, ValidationField
from .engine import RuleRegistry


class FinancialProvenance(Contract):
    """SQL-compatible records for one fact; no storage operations or inferred data.

    None evidence means the lookup is incomplete/unknown. A tuple is the complete
    lookup result for the fact's claimed evidence IDs; an empty tuple establishes
    their absence. Missing source/document objects mean insufficient information,
    not proof that a database row does not exist. Duplicate evidence matches are
    retained so the rule can report ambiguity rather than silently choose one.
    """

    version: Literal['financial-provenance-v1'] = 'financial-provenance-v1'
    fact: FinancialFact
    source: Source | None = None
    document: Document | None = None
    evidence: tuple[EvidenceReference, ...] | None = None

    def analytical_input(self, company_number: str, assessment_date: date) -> AnalyticalInput:
        """Transport typed records through M4.1's existing TextValue JSON boundary.

        The payload is schema-validated on both sides; the generic engine stays
        unchanged. Evidence IDs are claims to verify, not proof of resolved rows.
        All claimed evidence is admission/construction evidence in these rules.
        """
        evidence_ids = tuple(sorted(set(self.fact.evidence_ids)))
        return AnalyticalInput(input_id=self.fact.financial_fact_id, input_type='FINANCIAL_FACT',
            company_number=company_number, assessment_date=assessment_date,
            availability_status=self.fact.availability_status, evidence_ids=evidence_ids,
            construction_evidence_ids=evidence_ids,
            fields=(ValidationField(name='financial_provenance', value=TextValue(value=self.model_dump_json())),))


def _provenance(context: AnalyticalInput) -> FinancialProvenance:
    field = next(field for field in context.fields if field.name == 'financial_provenance')
    if not isinstance(field.value, TextValue) or field.value.value is None:
        raise ValueError('Financial provenance requires a typed JSON text payload')
    records = FinancialProvenance.model_validate_json(field.value.value)
    if (context.input_id != records.fact.financial_fact_id
            or set(context.evidence_ids) != set(records.fact.evidence_ids)
            or context.availability_status != records.fact.availability_status):
        raise ValueError('Financial provenance differs from analytical input')
    return records


def _outcome(definition: RuleDefinition, context: AnalyticalInput, result: ValidationStatus,
             reason: str, details: tuple[ValidationField, ...],
             failure: AdmissibilityReason = AdmissibilityReason.MISSING_REQUIRED_EVIDENCE) -> RuleOutcome:
    return RuleOutcome(rule_id=definition.rule_id, rule_version=definition.rule_version,
        role=definition.role, result=result, reason=reason, structured_details=details,
        evidence_ids=tuple(sorted(context.evidence_ids)),
        failure_code=failure if result in (ValidationStatus.FAIL, ValidationStatus.INCONCLUSIVE) else None)


class FinancialIdentityRule:
    """Check the intended company against linked fact/source/document identities."""

    @property
    def definition(self) -> RuleDefinition:
        """Stable mandatory gate; never an independent corroboration rule."""
        return RuleDefinition(rule_id='financial.identity', rule_version='v1',
            applies_to=('FINANCIAL_FACT',), required_inputs=('financial_provenance',),
            role=ValidationRole.HARD_FAIL)

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Definite disagreement fails; missing identity provenance stays inconclusive."""
        records = _provenance(context)
        fact, source, document = records.fact, records.source, records.document
        observed = [('fact', fact), ('source', source), ('document', document)]
        details = (ValidationField(name='intended_company', value=TextValue(value=context.company_number)),)
        details += tuple(ValidationField(name=name + '_company_number',
            value=TextValue(value=item.company_number if item else None)) for name, item in observed)
        details += tuple(ValidationField(name=name + '_company_id',
            value=TextValue(value=item.company_id if item else None)) for name, item in observed)
        mismatch = tuple(name for name, item in observed if item is not None and (
            item.company_number != context.company_number or item.company_id != fact.company_id))
        if mismatch:
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Structured company identities disagree with the intended company or fact company ID',
                details + (ValidationField(name='mismatched_records', value=CodesValue(value=mismatch)),),
                AdmissibilityReason.IDENTITY_FAILURE)
        if source is None or document is None or fact.document_id is None:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Source/document identity evidence is incomplete', details)
        if (source.source_id != fact.source_id or document.document_id != fact.document_id
                or document.source_id != source.source_id):
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Supplied identity records do not belong to the financial fact provenance', details,
                AdmissibilityReason.IDENTITY_FAILURE)
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'Fact and linked source/document identify the intended company', details)


class FinancialGroundingRule:
    """Check required evidence IDs, typed locators and source/document edges only.

    This establishes structured traceability, not byte existence, checksum
    verification, numeric entailment, derivation integrity or corroboration.
    """

    @property
    def definition(self) -> RuleDefinition:
        """Stable mandatory structured-grounding gate."""
        return RuleDefinition(rule_id='financial.evidence_grounding', rule_version='v1',
            applies_to=('FINANCIAL_FACT',), required_inputs=('financial_provenance',),
            role=ValidationRole.HARD_FAIL)

    def execute(self, context: AnalyticalInput) -> RuleOutcome:
        """Separate demonstrably absent/broken links from incomplete/ambiguous lookup."""
        records = _provenance(context)
        fact, source, document = records.fact, records.source, records.document
        details = (ValidationField(name='source_id', value=TextValue(value=fact.source_id)),
            ValidationField(name='document_id', value=TextValue(value=fact.document_id)),
            ValidationField(name='required_evidence_ids', value=CodesValue(value=tuple(sorted(fact.evidence_ids)))))
        if not fact.evidence_ids or fact.document_id is None:
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Required financial evidence/document linkage is absent on the fact', details)
        if source is not None and (source.source_id != fact.source_id
                or source.retrieval_status != RetrievalStatus.SUCCESS):
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Supporting source is mismatched or retrieval did not succeed', details)
        if document is not None and (document.document_id != fact.document_id
                or document.source_id != fact.source_id):
            return _outcome(self.definition, context, ValidationStatus.FAIL,
                'Document linkage contradicts the financial fact', details)
        if records.evidence is not None:
            missing = tuple(sorted(set(fact.evidence_ids) - {e.evidence_id for e in records.evidence}))
            if missing:
                return _outcome(self.definition, context, ValidationStatus.FAIL,
                    'Complete structured lookup found required evidence references absent',
                    details + (ValidationField(name='missing_evidence_ids', value=CodesValue(value=missing)),))
            matches = [e for e in records.evidence if e.evidence_id in fact.evidence_ids]
            if len({e.evidence_id for e in matches}) != len(matches):
                return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                    'Required evidence IDs resolve ambiguously to multiple records', details)
            if any(e.source_id != fact.source_id or e.document_id != fact.document_id for e in matches):
                return _outcome(self.definition, context, ValidationStatus.FAIL,
                    'Evidence reference belongs to a different source/document', details)
        if source is None or document is None or records.evidence is None:
            return _outcome(self.definition, context, ValidationStatus.INCONCLUSIVE,
                'Structured source/document/evidence lookup is incomplete', details)
        return _outcome(self.definition, context, ValidationStatus.PASS,
            'All required typed evidence locators link to the fact source and document', details)


def financial_identity_grounding_registry() -> RuleRegistry:
    """Register only these two v1 gates in the existing deterministic M4.1 registry."""
    registry = RuleRegistry('financial-identity-grounding-v1')
    registry.register(FinancialIdentityRule())
    registry.register(FinancialGroundingRule())
    return registry
