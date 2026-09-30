# M5 — Risk Variable & Leaf Belief Engine

## Objective

Compute the 11 risk-variable values from validated structured facts using
Risk Model v1 formulas, risk directions, thresholds and leaf-level rules.
Consume M4 evidence reliability results and apply the frozen
Reliability-to-Unknown treatment to produce final Low / High / Unknown
beliefs, including missing, unavailable and non-comparable input handling.
M5 does not recalculate M4 evidence reliability.

## Read before starting

- `docs/design-docs/m5-risk-variable-leaf-belief.md` — approved operational policies and the approved additive validated-obligation handoff
- `docs/design-docs/risk-model-v1.md`
- `docs/design-docs/evidence-reliability-v1.md`
- `docs/design-docs/er-aggregation-v1.md` (leaf construction and invariants)
- `docs/design-docs/data-dictionary-v1.md`

## Output and responsibility boundary

M5 produces the final Low / High / Unknown belief distribution for each of
G1.1, G1.2, G2.1, G2.2, G2.3, G3.1, F1.1, F1.2, F2.2, F2.3 and F3.1.
These 11 final distributions are M6 input, identified by variable code and
linked to the existing VariableResult records and assessment/model-version
context defined in `docs/design-docs/data-dictionary-v1.md`. Each distribution
is bounded in [0,1] and sums to 1 within the absolute tolerance defined in `docs/design-docs/er-aggregation-v1.md`, section 12.1.
Required-data failure remains (Low, High, Unknown) = (0, 0, 1); the leaf is
retained and its importance weight is not redistributed.

M5 ends at these final leaf distributions and performs no indicator-level,
domain-level or overall ER aggregation. M6 consumes them unchanged, applies
the frozen importance weights and aggregates Variables → Indicators → Domains
→ Overall, including frozen single-child pass-through. M6 must not recalculate
source facts, financial ratios, governance metrics, leaf thresholds, evidence
reliability or leaf belief distributions. S/E/V/C/r are not applied again by M6.
This interface clarifies responsibility only; it introduces no schema or
frozen-methodology change.

## Variables

G1.1, G1.2, G2.1, G2.2, G2.3, G3.1, F1.1, F1.2, F2.2, F2.3, F3.1.

## Implement

-   Fact dependency resolution.
-   Exact formulas from Risk Model v1.
-   Comparable-period rule for F1.2.
-   Higher-is-riskier and lower-is-riskier interpolation.
-   Apply Reliability-to-Unknown once at the leaf using M4 reliability results.
-   VariableFactLink provenance.
-   Versioned VariableResult persistence.

## Rules

-   Do not redistribute weight because a variable is missing.
-   Required-data failure =\> raw_value NULL and final Low=0, High=0,
    Unknown=1.
-   Optional/supporting fact absence does not automatically create ER
    Unknown.

## Acceptance criteria

-   Boundary and interpolation tests pass.
-   Missing/conflict/non-comparable tests pass.
-   Every variable result traces to required facts.
-   All 11 final leaf distributions satisfy the M6 input contract; no parent
    aggregation is performed.
