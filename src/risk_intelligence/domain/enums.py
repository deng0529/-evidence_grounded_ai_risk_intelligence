"""Frozen status vocabularies and documented M0 contract labels."""

from enum import StrEnum


class AvailabilityStatus(StrEnum):
    """Why a typed fact is usable or unavailable; never a risk belief."""

    AVAILABLE = "AVAILABLE"
    NOT_DISCLOSED = "NOT_DISCLOSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    NON_COMPARABLE = "NON_COMPARABLE"


class ExtractionMethod(StrEnum):
    """Recorded extraction route, including derivation without computing it."""

    API_DIRECT = "API_DIRECT"
    IXBRL_DIRECT = "IXBRL_DIRECT"
    PDF_NATIVE_DETERMINISTIC = "PDF_NATIVE_DETERMINISTIC"
    PDF_OCR_DETERMINISTIC = "PDF_OCR_DETERMINISTIC"
    LLM_NATIVE_TEXT = "LLM_NATIVE_TEXT"
    LLM_OCR_TEXT = "LLM_OCR_TEXT"
    DERIVED = "DERIVED"


class SourceType(StrEnum):
    """M0 labels for the source families named in Reliability Scheme v1."""

    COMPANIES_HOUSE_API = "COMPANIES_HOUSE_API"
    COMPANIES_HOUSE_IXBRL = "COMPANIES_HOUSE_IXBRL"
    COMPANIES_HOUSE_PDF = "COMPANIES_HOUSE_PDF"
    OFFICIAL_WEBSITE = "OFFICIAL_WEBSITE"


class FactType(StrEnum):
    """Typed value categories; JSON-like control lists use immutable tuples."""

    NUMERIC = "NUMERIC"
    DATE = "DATE"
    TEXT = "TEXT"
    BOOLEAN = "BOOLEAN"
    CODES = "CODES"


class PeriodType(StrEnum):
    """Whether a reporting period describes a point or duration."""

    INSTANT = "INSTANT"
    DURATION = "DURATION"


class ComparabilityStatus(StrEnum):
    """Recorded period comparability, not a computed trend assessment."""

    COMPARABLE = "COMPARABLE"
    NON_COMPARABLE = "NON_COMPARABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssessmentStatus(StrEnum):
    """Completeness of a stored assessment."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ProcessingStatus(StrEnum):
    """M0 lifecycle labels; no pipeline execution is provided."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RetrievalStatus(StrEnum):
    """M0 labels for an attempted retrieval, distinct from fact availability."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ValidationType(StrEnum):
    """Dictionary validation categories, not validation implementations."""

    SOURCE_CONSISTENCY = "SOURCE_CONSISTENCY"
    PERIOD_CONSISTENCY = "PERIOD_CONSISTENCY"
    CURRENCY_CONSISTENCY = "CURRENCY_CONSISTENCY"
    ARITHMETIC = "ARITHMETIC"
    CROSS_SOURCE = "CROSS_SOURCE"
    TEMPORAL = "TEMPORAL"
    DUPLICATE = "DUPLICATE"


class ValidationStatus(StrEnum):
    """Outcome reported by a future validation rule."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValidationRole(StrEnum):
    """Rule purpose, distinct from legacy diagnostic severity."""

    INFORMATIONAL = 'INFORMATIONAL'
    SUPPORT = 'SUPPORT'
    HARD_FAIL = 'HARD_FAIL'


class ValidationStrength(StrEnum):
    """Explicit substantive support; never inferred from pass counts."""

    NONE = 'NONE'
    MEANINGFUL = 'MEANINGFUL'
    STRONG = 'STRONG'


class EvidenceUse(StrEnum):
    """Distinguish construction/admission-only checks from independent support."""

    CONSTRUCTION = 'CONSTRUCTION'
    ADMISSION_ONLY = 'ADMISSION_ONLY'
    INDEPENDENT_VALIDATION = 'INDEPENDENT_VALIDATION'


class ConflictLevel(StrEnum):
    """Unresolved uncertainty level, supplied by later domain rules."""

    NONE = 'NONE'
    PARTIAL_UNRESOLVED = 'PARTIAL_UNRESOLVED'
    SERIOUS_UNRESOLVED = 'SERIOUS_UNRESOLVED'


class ConflictResolution(StrEnum):
    """Recorded explanation; resolution is not automatic latest-value selection."""

    NONE = 'NONE'
    RESTATEMENT = 'RESTATEMENT'
    SUPERSEDED = 'SUPERSEDED'
    EXTRACTION_ERROR = 'EXTRACTION_ERROR'
    ROUNDING_EXPLAINED = 'ROUNDING_EXPLAINED'
    SCOPE_DIFFERENCE = 'SCOPE_DIFFERENCE'
    PERIOD_DIFFERENCE = 'PERIOD_DIFFERENCE'
    UNIT_DIFFERENCE = 'UNIT_DIFFERENCE'
    UNRESOLVED = 'UNRESOLVED'


class CriticalTransformation(StrEnum):
    """Material transformation classification, not a product of pipeline stages."""

    STRUCTURED_DETERMINISTIC = 'STRUCTURED_DETERMINISTIC'
    TAGGED_IXBRL_DETERMINISTIC = 'TAGGED_IXBRL_DETERMINISTIC'
    NATIVE_PDF_DETERMINISTIC = 'NATIVE_PDF_DETERMINISTIC'
    OCR_DETERMINISTIC = 'OCR_DETERMINISTIC'
    GROUNDED_LLM_SEMANTIC = 'GROUNDED_LLM_SEMANTIC'
    COMPLEX_LLM_INTERPRETATION = 'COMPLEX_LLM_INTERPRETATION'
    UNSUPPORTED_LLM_NUMERIC = 'UNSUPPORTED_LLM_NUMERIC'


class AdmissibilityReason(StrEnum):
    """Typed reasons for withholding supported analytical evidence."""

    MISSING_REQUIRED_EVIDENCE = 'MISSING_REQUIRED_EVIDENCE'
    UNSUPPORTED_LLM_NUMERIC = 'UNSUPPORTED_LLM_NUMERIC'
    SERIOUS_UNRESOLVED_CONFLICT = 'SERIOUS_UNRESOLVED_CONFLICT'
    NON_COMPARABLE_PERIOD = 'NON_COMPARABLE_PERIOD'
    INCOMPATIBLE_SCOPE = 'INCOMPATIBLE_SCOPE'
    INCOMPATIBLE_UNIT_CURRENCY = 'INCOMPATIBLE_UNIT_CURRENCY'
    REQUIRED_COMPLETENESS_FAILURE = 'REQUIRED_COMPLETENESS_FAILURE'
    IDENTITY_FAILURE = 'IDENTITY_FAILURE'


class Severity(StrEnum):
    """Validation diagnostic severity, separate from its outcome."""

    INFO = "INFO"
    WARNING = "WARNING"
    FAIL = "FAIL"


class NodeType(StrEnum):
    """Parent aggregation levels; leaf variables have a separate contract."""

    INDICATOR = "INDICATOR"
    DOMAIN = "DOMAIN"
    OVERALL = "OVERALL"


class TriggerType(StrEnum):
    """Dictionary trigger vocabulary for future processing runs."""

    LIVE = "LIVE"
    REFRESH = "REFRESH"
    DEMO_PRECOMPUTE = "DEMO_PRECOMPUTE"


class FactRole(StrEnum):
    """M0 lineage labels distinguishing required and supporting inputs."""

    REQUIRED = "REQUIRED"
    SUPPORTING = "SUPPORTING"
