"""Explicit versioned concept mapping; no substring inference or risk arithmetic."""

from hashlib import sha256
from typing import Literal

from risk_intelligence.domain.common import Contract, Text
from risk_intelligence.domain.enums import PeriodType
from risk_intelligence.domain.facts import FinancialFact
from .models import CanonicalConcept, SourceFinancialFact


def default_registry() -> 'FinancialMappingRegistry':
    """Reviewed FRC 2024 exact concepts and qualified PDF labels only.

    FRC taxonomy suite 2024 v1.0.0, frc-core-2024-01-01.xsd supplies these
    instant monetary concepts. Generic Creditors and TotalBorrowings are not
    sufficient for current/interest-bearing classification and are excluded.
    """
    from .pdf import LABELS
    # Companies House filings can legitimately use more than one annual FRC
    # taxonomy suite.  Namespace is part of the source concept identity, so each
    # reviewed annual core namespace is admitted explicitly; local-name matching
    # remains forbidden.  This is a mapping-rule change and therefore has a new
    # immutable mapping version.
    namespaces = tuple(
        f'{{http://xbrl.frc.org.uk/fr/{year}-01-01/core}}'
        for year in (2021, 2022, 2023, 2024, 2025, 2026)
    )
    entries: tuple[tuple[str, CanonicalConcept], ...] = (
        ('CurrentAssets', 'CURRENT_ASSETS'), ('CurrentLiabilities', 'CURRENT_LIABILITIES'),
        ('TotalInventories', 'INVENTORY'), ('CurrentInventories', 'INVENTORY'), ('Stocks', 'INVENTORY'),
        ('NetAssetsLiabilities', 'NET_ASSETS'), ('TotalAssets', 'TOTAL_ASSETS'),
    )
    rules = tuple(
        MappingRule(source_concept=namespace + source, canonical_concept=target)
        for namespace in namespaces for source, target in entries
    )
    rules += tuple(MappingRule(source_concept='pdf-label:' + label, canonical_concept=target)
                   for label, target in LABELS.items())
    # Semantic fallback is intentionally concept-scoped rather than label-scoped.
    # The label/row remains preserved on SourceFinancialFact and is admitted only
    # after deterministic locator/value/scope/date checks in fallback.py.
    rules += tuple(MappingRule(source_concept='llm-semantic:' + concept, canonical_concept=concept)
                   for concept in ('CURRENT_ASSETS','CURRENT_LIABILITIES','INVENTORY','NET_ASSETS','TOTAL_ASSETS'))
    return FinancialMappingRegistry('financial-concepts-v4', rules)


class MappingRule(Contract):
    """Reviewed exact concept/context mapping, with an explicit sign convention."""

    source_concept: Text
    canonical_concept: CanonicalConcept
    dimensions: tuple[tuple[Text, Text], ...] = ()
    sign_multiplier: Literal[1, -1] = 1


class FinancialMappingRegistry:
    """A supplied reviewed registry version; ambiguous rule sets are rejected.

    Namespace-qualified source concepts include taxonomy version. No fallback
    based on the local name exists. Unmatched dimensions remain unresolved.
    """

    def __init__(self, version: str, rules: tuple[MappingRule, ...]) -> None:
        if not version.strip():
            raise ValueError("Mapping version is required")
        keys = [(rule.source_concept, rule.dimensions) for rule in rules]
        if len(set(keys)) != len(keys):
            raise ValueError("Ambiguous mapping registry")
        self.version, self.rules = version, rules

    def map(self, fact: SourceFinancialFact, *, company_id: str, company_number: str,
            source_id: str, processing_run_id: str) -> FinancialFact | None:
        """Return one direct observation, or None for unresolved source semantics."""
        if fact.entity_identifier != company_number or fact.period.period_type != PeriodType.INSTANT:
            return None
        rule = next((rule for rule in self.rules if rule.source_concept == fact.source_concept
                     and rule.dimensions == fact.dimensions), None)
        if rule is None:
            return None
        value = fact.value
        if value is not None and rule.sign_multiplier == -1:
            value = value.copy_negate()
        # Source identity remains part of canonical identity: conflicts never overwrite.
        identity = sha256(f"{fact.source_fact_id}:{self.version}:{rule.model_dump_json()}".encode()).hexdigest()
        return FinancialFact(financial_fact_id=identity, company_id=company_id,
            company_number=company_number, canonical_concept=rule.canonical_concept,
            source_concept=fact.source_concept, value_numeric=value, currency=fact.currency,
            unit=fact.unit, period=fact.period, source_id=source_id, document_id=fact.document_id,
            evidence_ids=(fact.evidence_id,), extraction_method=fact.extraction_method,
            availability_status=fact.availability_status, processing_run_id=processing_run_id)
