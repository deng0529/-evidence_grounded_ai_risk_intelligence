"""Exact numeric/context behavior and fail-closed controlled mappings."""

from datetime import date
from decimal import Decimal, localcontext

import pytest

from risk_intelligence.ingestion.accounts.ixbrl import extract_ixbrl
from risk_intelligence.ingestion.accounts.mapping import FinancialMappingRegistry, MappingRule
from risk_intelligence.ingestion.companies_house.client import ParseError


def registry() -> FinancialMappingRegistry:
    return FinancialMappingRegistry('synthetic-v1', (
        MappingRule(source_concept='{urn:synthetic:accounts:v1}NetAssets', canonical_concept='NET_ASSETS'),
        MappingRule(source_concept='{urn:synthetic:accounts:v1}Stocks', canonical_concept='INVENTORY'),
    ))


def test_exact_negative_scale_current_comparative_and_zero(ixbrl: bytes) -> None:
    with localcontext() as context:
        context.prec = 2
        result = extract_ixbrl(ixbrl, 'document', 'ZZ000003')
    assert result.complete
    current, comparative, inventory, unresolved = result.facts
    assert current.value == Decimal('-123400')
    assert current.raw_value == '123.40' and current.scale == 3 and current.sign == '-'
    assert current.decimals == '0' and current.currency == 'GBP'
    assert current.period.period_end == date(2025, 12, 31) and current.period_role == 'CURRENT'
    assert comparative.period.period_end == date(2024, 12, 31) and comparative.period_role == 'COMPARATIVE'
    assert inventory.value == Decimal(0)
    assert len(result.periods) == 2
    assert unresolved.source_concept.endswith('TotalAssetsLessCurrentLiabilities')


def test_mapping_never_guesses_total_assets_and_preserves_conflicts(ixbrl: bytes) -> None:
    result = extract_ixbrl(ixbrl, 'document', 'ZZ000003')
    mapped = [registry().map(fact, company_id='c', company_number='ZZ000003', source_id='s',
                            processing_run_id='run') for fact in result.facts]
    assert mapped[-1] is None
    assert [fact.canonical_concept for fact in mapped if fact] == ['NET_ASSETS', 'NET_ASSETS', 'INVENTORY']
    changed = ixbrl.replace(b'200000', b'210000').replace(b'2024-12-31', b'2025-12-31')
    other = extract_ixbrl(changed, 'other-document', 'ZZ000003')
    assert other.facts[0].period == other.facts[1].period
    assert other.facts[0].value != other.facts[1].value
    assert other.facts[0].source_fact_id != other.facts[1].source_fact_id


def test_absent_inventory_does_not_create_zero(ixbrl: bytes) -> None:
    content = ixbrl.replace(b'name="test:Stocks"', b'name="test:Unresolved"')
    result = extract_ixbrl(content, 'd', 'ZZ000003')
    mapped = [registry().map(f, company_id='c', company_number='ZZ000003', source_id='s', processing_run_id='r')
              for f in result.facts]
    assert not any(f and f.canonical_concept == 'INVENTORY' for f in mapped)


@pytest.mark.parametrize('old,new', [
    (b'ZZ000003', b'ZZ000004'), (b'contextRef="current"', b'contextRef="absent"'),
    (b'unitRef="gbp"', b'unitRef="absent"'), (b'scale="3"', b'scale="99"'),
    (b'123.40', b'not-a-number'), (b'2025-12-31', b'2025-99-99'),
    (b'sign="-"', b'sign="wrong"'), (b'scale="3"', b'format="test:unsupported"'),
])
def test_invalid_context_numeric_or_transform_fails_closed(ixbrl: bytes, old: bytes, new: bytes) -> None:
    with pytest.raises((ParseError, ValueError)):
        extract_ixbrl(ixbrl.replace(old, new), 'd', 'ZZ000003')


def test_xml_declarations_and_non_financial_xhtml_are_not_extractable(ixbrl: bytes) -> None:
    with pytest.raises(ParseError):
        extract_ixbrl(b'<!DOCTYPE html>' + ixbrl, 'd', 'ZZ000003')
    with pytest.raises(ParseError):
        extract_ixbrl(b'<html><body>Accounts 2025</body></html>', 'd', 'ZZ000003')


def test_ambiguous_registry_rejected() -> None:
    rule = MappingRule(source_concept='synthetic', canonical_concept='INVENTORY')
    with pytest.raises(ValueError, match='Ambiguous'):
        FinancialMappingRegistry('v1', (rule, rule))


def test_complete_extraction_with_explicit_nil_preserves_not_disclosed(ixbrl: bytes) -> None:
    content = ixbrl.replace(b'xmlns:test=', b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:test=')
    content = content.replace(b'name="test:Stocks" contextRef="current" unitRef="gbp">0',
                              b'name="test:Stocks" contextRef="current" unitRef="gbp" xsi:nil="true">')
    result = extract_ixbrl(content, 'd', 'ZZ000003')
    assert result.complete
    inventory = registry().map(result.facts[2], company_id='c', company_number='ZZ000003', source_id='s', processing_run_id='r')
    assert inventory.value_numeric is None and inventory.availability_status.value == 'NOT_DISCLOSED'
