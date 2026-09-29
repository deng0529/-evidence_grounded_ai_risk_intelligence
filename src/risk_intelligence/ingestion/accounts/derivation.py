"""Legacy exhaustive interest-bearing schedule admission; dynamic plans use interpretation."""

from decimal import Decimal, localcontext
from hashlib import sha256

from risk_intelligence.domain.enums import AvailabilityStatus, ExtractionMethod
from risk_intelligence.domain.facts import FinancialFact
from risk_intelligence.ingestion.companies_house.client import ParseError
from .models import DebtSchedule, SourceFinancialFact

DERIVATION_VERSION = 'complete-interest-bearing-sum-v1'
COMPLETENESS_QUOTE = 'Interest-bearing debt comprises only:'
COMPONENT_LABELS = {'bank loans', 'finance lease liabilities', 'hire purchase liabilities',
                    'other interest-bearing financing'}
def derive_debt(schedule: DebtSchedule, facts: tuple[SourceFinancialFact, ...], *,
                company_id: str, source_id: str, run_id: str, mapping_version: str) -> FinancialFact:
    """Sum non-overlapping components only under an explicit exhaustive disclosure.

    Callers must locate the retained completeness quote on the same source page;
    this function checks the component/context contract, not source reliability.
    """
    if schedule.completeness_quote != COMPLETENESS_QUOTE or not schedule.source_fact_ids:
        raise ParseError('No supported exhaustive interest-bearing debt disclosure')
    if len(set(schedule.source_fact_ids)) != len(schedule.source_fact_ids):
        raise ParseError('Repeated debt component')
    by_id = {fact.source_fact_id: fact for fact in facts}
    if any(identity not in by_id for identity in schedule.source_fact_ids):
        raise ParseError('Missing debt component')
    components = [by_id[identity] for identity in schedule.source_fact_ids]
    first = components[0]
    if first.dimensions:
        raise ParseError('Derived company debt requires an unambiguous standalone entity scope')
    labels = [fact.source_label for fact in components]
    if len(set(labels)) != len(labels) or any(label not in COMPONENT_LABELS for label in labels):
        raise ParseError('Overlapping or unsupported interest-bearing components')
    for fact in components:
        if (fact.availability_status != AvailabilityStatus.AVAILABLE or fact.value is None
                or fact.period != first.period or fact.currency != first.currency or fact.unit != first.unit
                or fact.document_id != first.document_id or fact.entity_identifier != first.entity_identifier
                or fact.dimensions != first.dimensions or fact.page != schedule.page):
            raise ParseError('Incomplete or inconsistent interest-bearing debt components')
    with localcontext() as context:
        context.prec = max(50, sum(len(f.value.as_tuple().digits) + abs(f.value.as_tuple().exponent) for f in components) + 10)
        total = sum((fact.value for fact in components), Decimal(0))
    identity = sha256((DERIVATION_VERSION + mapping_version + ':'.join(schedule.source_fact_ids)).encode()).hexdigest()
    return FinancialFact(financial_fact_id=identity, company_id=company_id,
        company_number=first.entity_identifier, canonical_concept='INTEREST_BEARING_DEBT',
        source_concept='complete-interest-bearing-components', value_numeric=total,
        currency=first.currency, unit=first.unit, period=first.period, source_id=source_id,
        document_id=first.document_id, evidence_ids=tuple(f.evidence_id for f in components),
        extraction_method=ExtractionMethod.DERIVED, availability_status=AvailabilityStatus.AVAILABLE,
        processing_run_id=run_id)
