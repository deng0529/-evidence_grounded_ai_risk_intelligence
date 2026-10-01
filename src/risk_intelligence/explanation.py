"""Typed M7 application views composed from immutable M4/M5/M6 records.

These are read models, not new persisted facts or calculation contracts.
"""

from typing import Literal

from risk_intelligence.domain.common import Contract, Text
from risk_intelligence.domain.evidence import Document, EvidenceReference, Source
from risk_intelligence.domain.facts import FinancialFact, StructuredFact
from risk_intelligence.domain.risk import AggregationInput, AggregationResult
from risk_intelligence.domain.runs import Assessment
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from risk_intelligence.persistence.validated_repository import (
    PersistedValidatedEvidenceSet, PersistedValidatedFact,
)
from risk_intelligence.persistence.ingestion_repository import Snapshot
from risk_intelligence.risk_variables.core import LeafAssessment, ValidatedInput
from risk_intelligence.validation.obligations import ValidatedObligation


class EvidenceExplanation(Contract):
    """SQL locator and retrieval metadata only; absent optional documents stay null."""

    reference: EvidenceReference
    source: Source
    document: Document | None


class FinancialLineageExplanation(Contract):
    """Existing canonical mapping/derivation and ordered source occurrences."""

    origin: Text
    mapping_version: Text
    derivation_version: Text | None
    derivation_rule: Text | None
    components: tuple[SourceFinancialFact, ...]


class InputExplanation(Contract):
    """Exact M4 input, source observations and evidence; no reassessment.

    Set members are source observations belonging to the validated population,
    not individually validated financial facts. Empty evidence is not invented.
    """

    reference: ValidatedInput
    record: PersistedValidatedFact | PersistedValidatedEvidenceSet | ValidatedObligation
    observations: tuple[FinancialFact | StructuredFact, ...]
    financial_lineage: FinancialLineageExplanation | None = None
    evidence: tuple[EvidenceExplanation, ...]
    snapshots: tuple[Snapshot, ...] = ()


class VariableExplanation(Contract):
    """Frozen variable name, exact M5 result/calculation and its resolved M4 inputs."""

    name: Text
    domain: Literal["GOVERNANCE", "FINANCIAL"]
    reporting_year: int | None
    leaf: LeafAssessment
    inputs: tuple[InputExplanation, ...]


class AggregationExplanation(Contract):
    """Stored M6 belief and ordered child references/weights, without ER execution."""

    result: AggregationResult
    children: tuple[AggregationInput, ...]


class AssessmentExplanation(Contract):
    """Deterministic assessment tree for M8; no generated time or narrative claims."""

    assessment: Assessment
    reporting_year: int
    overall: AggregationExplanation
    domains: tuple[AggregationExplanation, ...]
    variables: tuple[VariableExplanation, ...]
