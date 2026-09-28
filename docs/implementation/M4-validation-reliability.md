# M4 - Validation and Evidence Reliability

## Objective

Implement deterministic validation and Evidence Reliability Scheme v1.

## Read before starting

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
