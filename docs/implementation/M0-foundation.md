# M0 - Foundation and Domain Contracts

## Objective

Create the application foundation and typed domain contracts. Do not
retrieve live company data and do not implement risk calculations.

## Read before starting

-   `AGENTS.md`
-   `PROJECT_SPEC.md`
-   `ARCHITECTURE.md`
-   `docs/design-docs/data-dictionary-v1.md`
-   `docs/implementation/roadmap-v1.md`

## Implement

-   Configuration/settings module with environment-variable loading.
-   Core enums: AvailabilityStatus, ExtractionMethod, SourceType,
    FactType, PeriodType, ComparabilityStatus, AssessmentStatus,
    ProcessingStatus.
-   Typed domain models for Company, Source, Document, structured facts,
    ValidationResult, ReliabilityResult, VariableResult,
    AggregationResult, Assessment and ProcessingRun.
-   Repository/storage interfaces only; no cloud-specific implementation
    yet.
-   Application/service boundary so Streamlit is not coupled to domain
    logic.
-   Unit tests for enum constraints, typed NULL semantics and model
    validation.

## Do not implement

-   Live Companies House calls.
-   Turso/R2 network access.
-   Risk thresholds or ER equations.
-   Streamlit screens.

## Acceptance criteria

-   Package imports cleanly.
-   Tests pass.
-   Numeric/date fields cannot contain literal `UNKNOWN`.
-   Missing facts are represented by typed NULL plus AvailabilityStatus.
-   Domain layer has no Streamlit dependency.
