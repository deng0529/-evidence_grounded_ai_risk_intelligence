# M4 - Validation and Evidence Reliability

The authoritative [M4 frozen design and execution specification](../design-docs/m4-validation-evidence-reliability.md)
governs this milestone and refines the earlier outline below. Its 35 sections
define the rule registry, admissibility, explainable S/E/V/C/r, conflict resolution,
ValidatedFact/ValidatedEvidenceSet, versioning, Turso-first processing and acceptance.
M4.0 inspection and the M4.0a semantic-support handoff are complete. M4.1 adds
the reusable in-memory framework and frozen policies described below; domain
rules and final persistence/integration remain later steps.
The bounded [M4.2a-0 source-scope handoff](M4.2a-0-source-scope.md) preserves
deterministic PDF heading provenance in existing SQL evidence locators before
financial validation rules are implemented.
Read its authoritative pre-freeze clarifications and repository-review appendix
before implementation; inspect the structured Turso handoff and report any required
minimal extension before implementing it.

## Objective

Implement deterministic validation and Evidence Reliability Scheme v1.

## Read before starting

-   `docs/design-docs/m4-validation-evidence-reliability.md` — primary M4 authority
-   `docs/design-docs/evidence-reliability-v1.md`
-   `docs/design-docs/data-dictionary-v1.md`

## Implement

-   ValidationResult framework.
-   Period, currency, arithmetic, temporal and cross-source validation.
-   S/E/V/C/r calculation exactly as frozen.
-   Hard-fail rules.
-   Availability/failure mapping.
-   Reliability audit trail.

## Critical semantics

-   Missing status is not ER Unknown.
-   M4 produces S/E/V/C/r and its reliability audit trail for M5.
-   M5 — Risk Variable & Leaf Belief Engine consumes those results and applies
    Reliability-to-Unknown at the leaf before M6 aggregation. M4 does not
    construct risk-variable values or leaf beliefs.
-   Do not pass S/E/V/C/r again into higher ER levels.
-   Unsupported LLM numeric fact =\> hard fail.

## Acceptance criteria

-   Frozen reliability examples/tests pass.
-   Hard failures produce r=0.
-   Validation evidence is inspectable.
-   No risk/ER aggregation yet.

## M4.1 framework implementation

The `validation` package contains an explicit rule registry/engine and pure frozen
`m4-reliability-v1` policies. No database, object-storage, provider or filesystem
access is part of this framework. No migration is required.

Shared domain contracts retain the historical M0 ValidationResult and
ReliabilityResult unchanged. ValidationStatus gains INCONCLUSIVE/NOT_APPLICABLE;
legacy WARNING remains readable but is rejected for M4 RuleOutcome. New execution
contracts carry rule identity/version, role, strength candidate, evidence purpose,
independence group, typed details and exclusion reasons without inventing the
persisted M4.4 output identity/schema. SourceType is reused: COMPANIES_HOUSE_PDF
means FILED_PDF, and OFFICIAL_WEBSITE means COMPANY_WEBSITE in the frozen S table.

Rules register explicitly under immutable metadata. Execution sorts by rule ID;
one version/implementation per ID is allowed per ruleset. Exact re-registration
is idempotent; incompatible duplicates are rejected. Membership seals at first
applicability query/execution. New rules require a new versioned registry after
that point. There is no dynamic loading or production example/domain rule.

Missing required rule inputs yield INCONCLUSIVE. For a HARD_FAIL gate this is a
typed MISSING_REQUIRED_EVIDENCE exclusion; for an optional support rule it supplies
no validation bonus. Failed mandatory gates and supplied exclusions preserve
typed reasons. Unavailable analytical inputs cannot become admitted numeric
evidence. Informational FAIL and a gate's PASS/NOT_APPLICABLE are not hard failures.
Rule errors, mismatched identities and unsupported evidence references fail
explicitly. Reports retain company, assessment date, availability, supplied
evidence IDs, rule versions and ruleset version.

V selects explicit PASS/SUPPORT candidates marked INDEPENDENT_VALIDATION with
evidence beyond the construction-only population. It retains one strongest
representative per independence group, with stable identity tie-breaking. It does
not promote multiple MEANINGFUL results to STRONG merely by counting groups or
passes. A future domain rule may substantiate an explicit STRONG candidate for
an independent identity/composite relationship. Independent corroboration is not
disqualified merely because M3 also used it during admission. These distinctions
must be supplied honestly by later evidence-grounded domain rules; M4.1 does not
discover accounting relationships.

Conflict classifications are supplied, not discovered. Resolved classifications
retain reason/evidence and receive C=0; unresolved level/resolution inconsistencies
are rejected. Serious unresolved conflict and unsupported LLM numeric evidence
force explicit exclusion and r=0. No later consumer may treat that as an admitted
low-confidence numeric fact.

S/E/V/C tables are immutable mappings. Unknown source/transformation classes are
rejected, never guessed. The full supplied transformation chain is retained while
E uses only the critical class. Exact Decimal arithmetic uses an independent
precision context, exposes r_base and r_v, caps final r at 0.99, and overrides
hard-failed r to zero. Structured classifications, selected rule outcomes,
reasons, policy version and formula inputs/results provide deterministic
explanations. These remain heuristic policies, not calibrated probabilities.

M4.2 financial rules, M4.3 governance rules, M4.4 persistence/integration and
M5–M7 functionality are not implemented by this step. M4.1 tests are synthetic,
offline, and cover policy values, independence, exact arithmetic, registry order,
exclusions and compatibility with historical contracts.
