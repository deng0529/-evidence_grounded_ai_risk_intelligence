"""Source observations preserve financial semantics before canonical mapping."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from risk_intelligence.domain.common import Contract, ExactDecimal, Text
from risk_intelligence.domain.enums import AvailabilityStatus, ExtractionMethod
from risk_intelligence.domain.facts import ReportingPeriod

CanonicalConcept = Literal[
    "CURRENT_ASSETS", "CURRENT_LIABILITIES", "INVENTORY", "NET_ASSETS",
    "TOTAL_ASSETS", "INTEREST_BEARING_DEBT",
]
CONCEPTS: tuple[CanonicalConcept, ...] = (
    "CURRENT_ASSETS", "CURRENT_LIABILITIES", "INVENTORY", "NET_ASSETS",
    "TOTAL_ASSETS", "INTEREST_BEARING_DEBT",
)


class SourceFinancialFact(Contract):
    """One source occurrence; unresolved semantics never acquire a guessed concept.

    Evidence and document IDs are assigned after immutable publication. Currency
    and reporting context are required for admitted monetary observations.
    """

    source_fact_id: Text
    document_id: Text
    evidence_id: Text
    source_concept: Text
    source_label: Text | None = None
    raw_value: Text | None = None
    value: ExactDecimal | None
    availability_status: AvailabilityStatus
    currency: Text | None = None
    unit: Text | None = None
    unit_ref: Text | None = None
    context_ref: Text
    entity_identifier: Text
    entity_scheme: Text
    dimensions: tuple[tuple[Text, Text], ...] = ()
    period: ReportingPeriod
    period_role: Literal["CURRENT", "COMPARATIVE"]
    scale: int = Field(default=0, ge=-18, le=18)
    sign: Literal["+", "-"] = "+"
    decimals: Text | None = None
    precision: Text | None = None
    transformation: Text | None = None
    extraction_method: ExtractionMethod
    parser_version: Text
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_available_value(self) -> Self:
        """Keep source missingness explicit without making M4 judgments."""
        if self.availability_status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.NON_COMPARABLE):
            if self.value is None or not self.currency or not self.unit:
                raise ValueError("An available financial source fact requires value and currency/unit")
        elif self.value is not None:
            raise ValueError("Unavailable source value must be NULL")
        return self


class FilingInput(Contract):
    """Existing M2 filing handoff, never an independently discovered filing."""

    filing_fact_id: Text
    filing_id: Text
    metadata_url: Text
    filing_date: date


class ExtractionResult(Contract):
    """Extraction completion is independent of concept disclosure."""

    facts: tuple[SourceFinancialFact, ...]
    periods: tuple[ReportingPeriod, ...]
    complete: bool
    reason: Text | None = None
    debt_schedules: tuple['DebtSchedule', ...] = ()
    fallback: 'FallbackAudit | None' = None
    asset_schedules: tuple['AssetSideSchedule', ...] = ()
    completeness_notes: tuple[Text, ...] = ()
    contexts: tuple['FinancialContext', ...] = ()
    proofs: tuple['CompletenessProof', ...] = ()
    interpretations: tuple['InterpretationDecision', ...] = ()
    interpretation_artifact_id: Text | None = None


class AssetSideSchedule(Contract):
    """Historical v1 artifact shape; new admission uses generic completeness proofs."""

    source_fact_ids: tuple[Text, ...]
    evidence_id: Text
    page: int = Field(ge=1)
    row_start: int = Field(ge=1)
    row_end: int = Field(ge=1)
    evidence_text: Text
    rule_version: Text


class CandidateDecision(Contract):
    """Admission outcome references retained model output without trusting its value."""

    candidate_index: int
    concept: CanonicalConcept
    kind: Literal['DIRECT', 'COMPONENT'] = 'DIRECT'
    period_end: str
    status: Literal['AVAILABLE', 'VALIDATION_FAILED', 'EXTRACTION_FAILED']
    reason: Text
    source_fact_id: Text | None = None


class FallbackAudit(Contract):
    """Inspectable bounded fallback attempt, including unavailable/unresolved outcomes."""

    targets: tuple[CanonicalConcept, ...]
    pages: tuple[int, ...]
    status: Literal['UNAVAILABLE', 'NO_RELEVANT_EVIDENCE', 'COMPLETE', 'EXTRACTION_FAILED']
    decisions: tuple[CandidateDecision, ...] = ()


class DebtSchedule(Contract):
    """Explicit exhaustive financing disclosure, not an inferred component list."""

    source_fact_ids: tuple[Text, ...]
    completeness_quote: Text
    page: int = Field(ge=1)


class FinancialContext(Contract):
    """Deterministically located statement hierarchy, never supplied by a model."""

    source_fact_id: Text
    statement: Text
    section: Text
    supporting_text: Text
    compatible_concepts: tuple[CanonicalConcept, ...] = ()


class SemanticSupport(Contract):
    """SQL-only contextual support for one accepted semantic interpretation."""

    interpretation_id: Text
    schema_version: Literal['financial-semantic-support-v1'] = 'financial-semantic-support-v1'
    rationale: Text
    context: FinancialContext


class GroundedOperand(Contract):
    """Untrusted copied source operand; admission compares every field to its source."""

    source_fact_id: Text
    source_label: Text
    value: ExactDecimal
    evidence_id: Text
    page: int | None
    operation: Literal['ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE'] = 'ADD'


class CompletenessProof(Contract):
    """A source-verified accounting relationship and its non-overlapping population."""

    proof_id: Text
    target: CanonicalConcept
    source_fact_ids: tuple[Text, ...]
    document_id: Text
    page: int
    row_start: int
    row_end: int
    evidence_text: Text
    relationship: Literal['ASSET_SIDE', 'EXHAUSTIVE_INTEREST_BEARING']
    cross_check_ids: tuple[Text, ...] = ()


class InterpretationProposal(Contract):
    """Located semantic mapping or bounded arithmetic plan; never executable code."""

    target: CanonicalConcept
    kind: Literal['NORMALIZATION', 'DERIVATION']
    method: Literal['DETERMINISTIC_MAPPING', 'DETERMINISTIC_DERIVATION', 'LLM_SEMANTIC', 'LLM_DERIVATION']
    scope: Literal['COMPANY', 'GROUP']
    period_end: date
    currency: Text
    unit: Text
    operands: tuple[GroundedOperand, ...]
    proof_id: Text | None = None
    rationale: Text
    version: Text


class InterpretationDecision(Contract):
    """Immutable proposal, deterministic outcome and optional model-artifact linkage."""

    proposal: InterpretationProposal
    status: Literal['AVAILABLE', 'VALIDATION_FAILED', 'SUPERSEDED']
    reason: Text
    value: ExactDecimal | None = None
    llm_artifact_id: Text | None = None


class InterpretationResponse(Contract):
    """Bounded provider output; unresolved concepts are allowed to have no proposal."""

    proposals: tuple[InterpretationProposal, ...] = Field(max_length=24)


ExtractionResult.model_rebuild()
