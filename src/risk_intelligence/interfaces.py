"""Ports only: adapters and orchestration are deliberately not implemented."""

from typing import Protocol, TypeVar

from .domain.evidence import Company, Document, EvidenceReference, RawEvidence, Source
from .domain.facts import FinancialFact, StructuredFact
from .domain.reliability import ReliabilityResult
from .domain.risk import AggregationInput, AggregationResult, VariableFactLink, VariableResult
from .domain.runs import Assessment, ProcessingRun
from .domain.validation import ValidationResult

RecordT = TypeVar(
    "RecordT",
    bound=(
        Source | Document | RawEvidence | EvidenceReference | StructuredFact
        | FinancialFact | ValidationResult | ReliabilityResult | VariableResult
        | VariableFactLink | AggregationResult | AggregationInput
    ),
)


class RecordRepository(Protocol[RecordT]):
    """Typed per-record M1 metadata port, never a generic untyped payload store.

    For example, RecordRepository[FinancialFact] accepts and returns only that
    contract. Keys for link records are assigned by the future storage adapter.
    Referential integrity and transactions belong to M1, not these signatures.
    """

    def get(self, record_id: str) -> RecordT | None:
        """Return a stored record or None, without extraction or calculation."""
        ...

    def save(self, record_id: str, record: RecordT) -> None:
        """Persist the supplied record under its explicit identity."""
        ...


class CompanyRepository(Protocol):
    """Canonical-identity repository; M1 will implement structured persistence."""

    def get_by_company_number(self, company_number: str) -> Company | None:
        """Return the stored company or None; do not infer a different identity."""
        ...

    def save(self, company: Company) -> None:
        """Persist an explicitly supplied company record."""
        ...


class EvidenceStorage(Protocol):
    """Raw-byte storage port for M1 local/R2 adapters, separate from metadata."""

    def put(self, evidence: RawEvidence, content: bytes) -> None:
        """Store immutable content; reject an existing key with different bytes."""
        ...

    def read(self, object_path: str) -> bytes:
        """Return exact bytes or raise FileNotFoundError for an absent object."""
        ...


class AssessmentRepository(Protocol):
    """M1 persistence boundary for versioned assessments and processing records."""

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        """Return metadata for one assessment without calculating a result."""
        ...

    def save_assessment(self, assessment: Assessment) -> None:
        """Persist a supplied assessment's metadata."""
        ...

    def save_processing_run(self, run: ProcessingRun) -> None:
        """Persist supplied run metadata without starting processing."""
        ...


class AssessmentService(Protocol):
    """Future application boundary consumed by M7 UI; no UI dependencies here.

    Later ingestion/calculation milestones supply orchestration. Defining this
    port does not provide a fake analysis engine or start any processing.
    """

    def request_analysis(self, company_number: str) -> ProcessingRun:
        """Request analysis of an already selected canonical company identity."""
        ...

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        """Read available assessment metadata for presentation."""
        ...
