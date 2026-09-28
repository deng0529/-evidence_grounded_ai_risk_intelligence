# M6 — Hierarchical ER Aggregation Engine

## Objective

Accept M5 final leaf beliefs and apply frozen importance weights to perform
hierarchical Evidential Reasoning aggregation:
Variables → Indicators → Domains → Overall.
Produce Low / High / Unknown distributions for all six indicators,
Governance, Financial and Overall.

## Input and responsibility boundary

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

## Read before starting

-   `docs/design-docs/er-aggregation-v1.md`
-   `docs/design-docs/risk-model-v1.md`
-   `docs/design-docs/data-dictionary-v1.md`
-   `docs/implementation/M5-risk-variable-leaf-belief-engine.md` (final leaf output contract)

## Implement

-   Analytical ER formula from the frozen specification.
-   Indicator aggregation G1/G2/G3/F1/F2/F3.
-   Domain aggregation GOVERNANCE/FINANCIAL.
-   Overall aggregation.
-   Single-child pass-through behavior.
-   AggregationInput persistence with actual importance weights/model
    version.

## Regression tests

Encode the frozen stress tests, including: - all High - all Low -
Governance Low vs Financial High - one missing leaf - whole F2 missing -
reliability sweep - mixed-belief reference case - single-child
pass-through - deterministic/order-invariant behavior

Reliability-sweep fixtures supply already adjusted final leaf distributions
from the M5 contract. M6 tests aggregation of those inputs; they do not
implement reliability calculation or leaf discounting inside M6.

## Mixed-case input fixture requiring human review

`docs/design-docs/er-aggregation-v1.md` now explicitly supplies the analytical
ER formula (section 4.1), frozen mixed-case expected output (section 10.1)
and absolute numerical tolerance (section 12.1). These are implementation
authority; the prior formula, expected-output and tolerance gaps are resolved.

The exact mixed-case input fixture was not found in active authoritative
Markdown and still requires human review. Do not invent it or claim that
specific regression test passes until approved inputs are supplied. Preserve
all existing stress-test cases and single-child pass-through requirements.

## Acceptance criteria

All frozen numerical regression tests pass within documented tolerance.
