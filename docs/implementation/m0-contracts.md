# M0 contract implementation notes

Status: implemented, awaiting human review. These notes describe the M0 code;
they do not replace the frozen [data dictionary](../design-docs/data-dictionary-v1.md)
or authorize M1. See [M0 scope](M0-foundation.md) and the
[roadmap](roadmap-v1.md) for milestone boundaries.

## Representation and validation

The `risk_intelligence` package separates evidence, facts, validation results,
reliability results, leaf/parent results and run metadata. Frozen Pydantic records
reject extra fields and implicit Python coercion. Collections use tuples.
Normal constructors require typed values (Decimal, date, aware datetime, enum).
Use `model_dump_json()` / `model_validate_json()` for the JSON boundary: exact
Decimals are strings, dates are ISO dates, timestamps normalize to UTC. Floats
and booleans are rejected as numeric quantities. No display rounding is applied.

Missing fact values are `None` with an availability status. `AVAILABLE` and
`NON_COMPARABLE` source facts retain typed values; other statuses use `None`.
Failed extraction candidates can be retained separately with evidence links.
Non-comparable source data remains available for audit even though the future
affected leaf result has no usable raw value. Missingness never generates a
belief distribution in M0. Supplied belief totals are checked with absolute
tolerance `1e-8` using exact rational arithmetic independent of Decimal context;
no beliefs are calculated, repaired or rounded.

Present financial values require unit, reporting period and evidence references.
Currency is optional for non-currency units; supplying/validating the appropriate
currency and canonical concept is a later extraction/validation responsibility.
Document locations require document IDs. Missing retrievals need not invent
evidence IDs. A hard-failure reliability record can therefore have no evidence
IDs, but requires fact IDs, a reason and a supplied final reliability of zero.
Non-failed reliability records require evidence IDs. Reliability components are
range-checked, with final reliability capped at `0.99`; their formula relationships
are not evaluated. ER importance weights are separate aggregation input fields.

`VariableResult.reliability_r` is a reproducibility snapshot of the final evidence
reliability actually used for that leaf calculation, constrained to
`0 <= reliability_r <= 0.99`. Normally it must correspond to
`ReliabilityResult.final_reliability_r` referenced by `reliability_id`.
M0 validates the local range only; cross-record database/service integrity
validation belongs to the appropriate later milestone and is not implemented here.

Company numbers remain textual canonical identities, retaining leading zeroes.
The M0 eight-character uppercase alphanumeric check is format validation only,
not proof that a company exists or validation of registry prefix allocations.
Opaque internal IDs connect records; cross-record identity/foreign-key checks,
checksum verification, transactions and immutable object enforcement belong to
future adapters. Do not use Pydantic's unchecked `model_construct()` or
`model_copy(update=...)` at untrusted input boundaries; reconstruct via validation.

## Adopted M0 v1 implementation vocabulary

Frozen availability, extraction, period, comparability, assessment, validation,
severity, node and trigger vocabularies are represented directly. M0 also requires
named types whose exact member labels are not fully enumerated in the active
specifications. Human review has accepted the following software-level enum
vocabulary for M0 v1. Each member's stored string value is identical to its name.
This adoption does not modify the frozen methodological specifications.

| Type | M0 member labels |
| --- | --- |
| SourceType | COMPANIES_HOUSE_API, COMPANIES_HOUSE_IXBRL, COMPANIES_HOUSE_PDF, OFFICIAL_WEBSITE |
| FactType | NUMERIC, DATE, TEXT, BOOLEAN, CODES |
| ProcessingStatus | PENDING, RUNNING, COMPLETE, PARTIAL, FAILED |
| RetrievalStatus | SUCCESS, FAILED |
| FactRole | REQUIRED, SUPPORTING |

`CODES` stores source control labels as an immutable tuple. `StructuredFact`
uses a discriminated union of typed value records instead of an untyped JSON
payload. For a legitimately absent resignation/cessation date, callers can use
`None` with `NOT_APPLICABLE`; M0 does not infer active status from that null.
Human review should confirm that convention before officer ingestion begins.

Source URLs/identifiers and concepts are nonblank text, not network-validated.
Evidence locators cover API JSON paths, iXBRL concept/context and PDF regions.
An HTML-specific locator is intentionally deferred until an authorized website
extraction task establishes its requirements. No website scraper is provided.
Version fields are explicit supplied strings, with no guessed defaults.

## Interfaces and configuration

`CompanyRepository`, typed `RecordRepository`, `AssessmentRepository` and
`EvidenceStorage` are Protocols only. M1 supplies persistence adapters, including
local raw storage and the Turso/R2 boundaries. `AssessmentService` is the UI-facing
application port: later processing milestones implement orchestration and M7
consumes it. No fake engines or concrete adapters are included.

`load_settings()` accepts an explicit mapping for isolated tests or reads the
process environment when called without one. It does not read `.env`, write
files, validate credentials remotely or create connections. Optional secrets are
excluded from repr and serialization. No secrets are required for M0.

## Review and repeatable checks

From the repository root, run the commands in the [README](../../README.md).
The example prints a synthetic exact monetary fact, a missing numeric fact,
source/evidence lineage and a supplied future aggregation result, and demonstrates
rejection of numeric `UNKNOWN`. The tests cover all enum member sets, strict
types, null semantics, provenance, supplied result invariants, settings and
interfaces. No lint or static type-check tool is configured for M0; public type
annotations and docstrings are reviewed directly.

M0 leaves all business validations, reliability formulas, financial/governance
metrics, risk transformations, ER equations, explanations, persistence and UI
execution to their specified later milestones.
