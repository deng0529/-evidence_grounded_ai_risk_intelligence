"""Focused offline financial identity/grounding gates through the M4.1 engine."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from risk_intelligence.domain.enums import (
    AdmissibilityReason, AvailabilityStatus, ComparabilityStatus, EvidenceUse,
    ExtractionMethod, PeriodType, RetrievalStatus, SourceType, ValidationStrength,
)
from risk_intelligence.domain.evidence import Document, EvidenceReference, PdfLocator, Source
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.validation.engine import RuleRegistry, ValidationEngine
from risk_intelligence.validation.financial import (
    FinancialGroundingRule, FinancialIdentityRule, FinancialProvenance,
    financial_identity_grounding_registry,
)
from risk_intelligence.validation.policy import classify_support


@pytest.fixture
def provenance() -> FinancialProvenance:
    source = Source(source_id='s', company_id='c', company_number='ZZ000003',
        source_type=SourceType.COMPANIES_HOUSE_PDF, source_name='Synthetic', source_identifier='synthetic',
        retrieved_at=datetime(2026, 9, 29, tzinfo=UTC), retrieval_status=RetrievalStatus.SUCCESS,
        processing_run_id='r')
    document = Document(document_id='d', company_id='c', company_number='ZZ000003', source_id='s',
        document_type='ACCOUNTS', representation_type='application/pdf')
    evidence = tuple(EvidenceReference(evidence_id=identity, source_id='s', document_id='d',
        location=PdfLocator(page=1, label='Synthetic row')) for identity in ('e1', 'e2'))
    fact = FinancialFact(financial_fact_id='f', company_id='c', company_number='ZZ000003',
        canonical_concept='NET_ASSETS', value_numeric=Decimal('10'), currency='GBP', unit='GBP',
        period=ReportingPeriod(period_type=PeriodType.INSTANT, period_end=date(2025, 12, 31),
                               comparability_status=ComparabilityStatus.REVIEW_REQUIRED),
        source_id='s', document_id='d', evidence_ids=('e1', 'e2'),
        extraction_method=ExtractionMethod.PDF_NATIVE_DETERMINISTIC,
        availability_status=AvailabilityStatus.AVAILABLE, processing_run_id='r')
    return FinancialProvenance(fact=fact, source=source, document=document, evidence=evidence)


def report(records: FinancialProvenance):
    return ValidationEngine(financial_identity_grounding_registry()).validate(
        records.analytical_input('ZZ000003', date(2026, 9, 29)))


def outcome(records: FinancialProvenance, rule_id: str):
    return next(item for item in report(records).outcomes if item.rule_id == 'financial.' + rule_id)


def test_matching_identity_and_grounding_pass_without_strength(provenance) -> None:
    result = report(provenance)
    assert result.admissible and len(result.outcomes) == 2
    for item in result.outcomes:
        assert item.result.value == 'PASS' and not item.hard_fail
        assert item.evidence_ids == ('e1', 'e2') and item.reason and item.structured_details
        assert item.validation_strength_candidate == ValidationStrength.NONE
        assert item.evidence_use == EvidenceUse.ADMISSION_ONLY and item.independence_group is None
    assert not result.support_outcomes
    assert classify_support(result.outcomes, result.context.construction_evidence_ids).strength == ValidationStrength.NONE


@pytest.mark.parametrize('record', ['fact', 'source', 'document'])
@pytest.mark.parametrize('field,value', [('company_number', 'ZZ000004'), ('company_id', 'other')])
def test_definite_identity_mismatch_is_typed_hard_failure(provenance, record, field, value) -> None:
    changed = provenance.model_copy(update={record: getattr(provenance, record).model_copy(update={field: value})})
    result = report(changed)
    item = next(o for o in result.outcomes if o.rule_id == 'financial.identity')
    assert item.result.value == 'FAIL' and item.hard_fail
    assert item.failure_code == AdmissibilityReason.IDENTITY_FAILURE
    assert item.evidence_ids == ('e1', 'e2') and 'identities' in item.reason
    assert any(d.name == 'mismatched_records' for d in item.structured_details)
    assert not result.admissible
    assert any(f.code == AdmissibilityReason.IDENTITY_FAILURE and f.evidence_ids == item.evidence_ids
               for f in result.failures)


@pytest.mark.parametrize('record', ['source', 'document'])
def test_missing_identity_evidence_is_inconclusive(provenance, record) -> None:
    item = outcome(provenance.model_copy(update={record: None}), 'identity')
    assert item.result.value == 'INCONCLUSIVE' and item.hard_fail
    assert item.failure_code == AdmissibilityReason.MISSING_REQUIRED_EVIDENCE
    assert item.evidence_ids == ('e1', 'e2') and 'incomplete' in item.reason


def test_value_and_concept_cannot_repair_missing_identity(provenance) -> None:
    fact = provenance.fact.model_copy(update={'canonical_concept': 'ZZ000003', 'value_numeric': Decimal('3')})
    assert outcome(provenance.model_copy(update={'fact': fact, 'source': None}), 'identity').result.value == 'INCONCLUSIVE'


@pytest.mark.parametrize('evidence', [(), None])
def test_absent_and_unknown_evidence_are_distinguished(provenance, evidence) -> None:
    result = report(provenance.model_copy(update={'evidence': evidence}))
    item = next(o for o in result.outcomes if o.rule_id == 'financial.evidence_grounding')
    assert item.result.value == ('FAIL' if evidence == () else 'INCONCLUSIVE')
    assert item.hard_fail and not result.admissible
    assert item.failure_code == AdmissibilityReason.MISSING_REQUIRED_EVIDENCE
    assert item.evidence_ids == ('e1', 'e2') and item.reason and item.structured_details
    assert any(f.reason == item.reason for f in result.failures)


def test_partial_complete_lookup_identifies_the_missing_evidence(provenance) -> None:
    item = outcome(provenance.model_copy(update={'evidence': provenance.evidence[:1]}), 'evidence_grounding')
    assert item.result.value == 'FAIL'
    assert next(d.value.value for d in item.structured_details if d.name == 'missing_evidence_ids') == ('e2',)


def test_ambiguous_grounding_remains_inconclusive(provenance) -> None:
    changed = provenance.model_copy(update={'evidence': provenance.evidence + (provenance.evidence[0],)})
    item = outcome(changed, 'evidence_grounding')
    assert item.result.value == 'INCONCLUSIVE' and 'ambiguously' in item.reason
    assert item.evidence_ids == ('e1', 'e2')


@pytest.mark.parametrize('field', ['source_id', 'document_id'])
def test_broken_evidence_edge_fails(provenance, field) -> None:
    evidence = provenance.evidence[0].model_copy(update={field: 'different'})
    item = outcome(provenance.model_copy(update={'evidence': (evidence, provenance.evidence[1])}), 'evidence_grounding')
    assert item.result.value == 'FAIL' and item.hard_fail


def test_absent_document_link_is_demonstrable_failure(provenance) -> None:
    changed = provenance.model_copy(update={'fact': provenance.fact.model_copy(update={'document_id': None})})
    assert outcome(changed, 'evidence_grounding').result.value == 'FAIL'


def test_registry_and_evidence_order_are_deterministic(provenance) -> None:
    context = provenance.analytical_input('ZZ000003', date(2026, 9, 29))
    reports = []
    for rules in ((FinancialIdentityRule(), FinancialGroundingRule()),
                  (FinancialGroundingRule(), FinancialIdentityRule())):
        registry = RuleRegistry('financial-identity-grounding-v1')
        for rule in rules:
            registry.register(rule)
        reports.append(ValidationEngine(registry).validate(context))
    assert reports[0] == reports[1]
    assert [o.rule_id for o in reports[0].outcomes] == ['financial.evidence_grounding', 'financial.identity']
    reversed_records = provenance.model_copy(update={'evidence': tuple(reversed(provenance.evidence)),
        'fact': provenance.fact.model_copy(update={'evidence_ids': ('e2', 'e1')})})
    assert report(reversed_records).outcomes == reports[0].outcomes
