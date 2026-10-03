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

BALANCE_SHEET_DERIVATION_VERSION = 'balance-sheet-subtotals-v1'
_FRC_CORE_NAMESPACES = tuple(f'{{http://xbrl.frc.org.uk/fr/{year}-01-01/core}}' for year in (2023, 2024, 2025, 2026))


def _reviewed_core_local(fact: SourceFinancialFact) -> str | None:
    """Return a local name only after exact admission to a reviewed FRC core namespace."""
    for namespace in _FRC_CORE_NAMESPACES:
        if fact.source_concept.startswith(namespace):
            return fact.source_concept[len(namespace):]
    # PDF/LLM facts reach here only after deterministic page/row/year/unit/value admission.
    # Keep the bridge explicit: TALCL is never mapped directly to TOTAL_ASSETS.
    if fact.source_concept == 'pdf-component:total assets less current liabilities':
        return 'TotalAssetsLessCurrentLiabilities'
    if fact.source_concept == 'llm-semantic:CURRENT_LIABILITIES':
        return 'CurrentLiabilities'
    return None


def derive_balance_sheet_subtotals(facts: tuple[SourceFinancialFact, ...], *, company_id: str,
                                    source_id: str, run_id: str,
                                    mapping_version: str) -> tuple[tuple[FinancialFact, tuple[str, ...], str], ...]:
    """Derive CL and TA from explicit UK balance-sheet subtotals, fail closed.

    Supported identities are exact arithmetic, not accounting estimates:
      CURRENT_LIABILITIES = CURRENT_ASSETS - NET_CURRENT_ASSETS_LIABILITIES
      TOTAL_ASSETS = TOTAL_ASSETS_LESS_CURRENT_LIABILITIES + CURRENT_LIABILITIES
                   = TALCL + CURRENT_ASSETS - NET_CURRENT_ASSETS_LIABILITIES
    Only un-dimensioned AVAILABLE monetary facts from the same document/entity/
    period/currency/unit and reviewed annual FRC core namespaces are admitted.
    """
    by_period: dict[str, dict[str, SourceFinancialFact]] = {}
    wanted = {'CurrentAssets', 'NetCurrentAssetsLiabilities', 'TotalAssetsLessCurrentLiabilities', 'CurrentLiabilities'}
    for fact in facts:
        local = _reviewed_core_local(fact)
        if (local not in wanted or fact.availability_status != AvailabilityStatus.AVAILABLE
                or fact.value is None or fact.dimensions):
            continue
        key = fact.period.model_dump_json()
        bucket = by_period.setdefault(key, {})
        if local in bucket:  # duplicate source semantics are ambiguous; fail closed for this period
            bucket[local] = None  # type: ignore[assignment]
        else:
            bucket[local] = fact

    derived = []
    for bucket in by_period.values():
        ca = bucket.get('CurrentAssets')
        nca = bucket.get('NetCurrentAssetsLiabilities')
        talcl = bucket.get('TotalAssetsLessCurrentLiabilities')
        direct_cl = bucket.get('CurrentLiabilities')
        first = direct_cl or ca or talcl
        if first is None:
            continue
        current_liabilities = direct_cl.value if direct_cl is not None else None
        if current_liabilities is None and ca is not None and nca is not None:
            components = (ca, nca)
            if any((f.document_id != ca.document_id or f.entity_identifier != ca.entity_identifier
                    or f.period != ca.period or f.currency != ca.currency or f.unit != ca.unit)
                   for f in components):
                continue
            with localcontext() as context:
                context.prec = max(50, *(len(f.value.as_tuple().digits) + abs(f.value.as_tuple().exponent) + 10
                                         for f in components if f.value is not None))
                current_liabilities = ca.value - nca.value
            if current_liabilities < 0:
                continue
            cl_ids = tuple(f.source_fact_id for f in components)
            cl_identity = sha256((BALANCE_SHEET_DERIVATION_VERSION + mapping_version
                                  + ':CURRENT_LIABILITIES:' + ':'.join(cl_ids)).encode()).hexdigest()
            cl = FinancialFact(financial_fact_id=cl_identity, company_id=company_id,
                company_number=ca.entity_identifier, canonical_concept='CURRENT_LIABILITIES',
                source_concept='derived:CurrentAssets-NetCurrentAssetsLiabilities',
                value_numeric=current_liabilities, currency=ca.currency, unit=ca.unit,
                period=ca.period, source_id=source_id, document_id=ca.document_id,
                evidence_ids=tuple(f.evidence_id for f in components), extraction_method=ExtractionMethod.DERIVED,
                availability_status=AvailabilityStatus.AVAILABLE, processing_run_id=run_id)
            derived.append((cl, cl_ids, 'CurrentAssets - NetCurrentAssetsLiabilities'))
        if talcl is None or current_liabilities is None:
            continue
        cl_source = direct_cl
        reference = cl_source or ca
        if reference is None or (talcl.document_id != reference.document_id
                or talcl.entity_identifier != reference.entity_identifier or talcl.period != reference.period
                or talcl.currency != reference.currency or talcl.unit != reference.unit or talcl.dimensions
                or talcl.availability_status != AvailabilityStatus.AVAILABLE or talcl.value is None):
            continue
        if cl_source is not None:
            ta_components = (talcl, cl_source)
            ta_rule = 'TotalAssetsLessCurrentLiabilities + CurrentLiabilities'
        else:
            ta_components = (talcl, ca, nca)
            ta_rule = 'TotalAssetsLessCurrentLiabilities + CurrentAssets - NetCurrentAssetsLiabilities'
        with localcontext() as context:
            context.prec = max(50, *(len(f.value.as_tuple().digits) + abs(f.value.as_tuple().exponent) + 10
                                     for f in ta_components if f is not None and f.value is not None))
            total_assets = talcl.value + current_liabilities
        if total_assets < 0:
            continue
        ta_ids = tuple(f.source_fact_id for f in ta_components)
        ta_identity = sha256((BALANCE_SHEET_DERIVATION_VERSION + mapping_version
                              + ':TOTAL_ASSETS:' + ':'.join(ta_ids)).encode()).hexdigest()
        ta = FinancialFact(financial_fact_id=ta_identity, company_id=company_id,
            company_number=reference.entity_identifier, canonical_concept='TOTAL_ASSETS',
            source_concept='derived:TotalAssetsLessCurrentLiabilities+CurrentAssets-NetCurrentAssetsLiabilities',
            value_numeric=total_assets, currency=reference.currency, unit=reference.unit, period=reference.period,
            source_id=source_id, document_id=first.document_id,
            evidence_ids=tuple(f.evidence_id for f in ta_components), extraction_method=ExtractionMethod.DERIVED,
            availability_status=AvailabilityStatus.AVAILABLE, processing_run_id=run_id)
        derived.append((ta, ta_ids,
                        ta_rule))
    return tuple(derived)
