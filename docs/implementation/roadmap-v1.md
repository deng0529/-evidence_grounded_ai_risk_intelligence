# Implementation Roadmap v1

Status: FROZEN CANDIDATE FOR MVP IMPLEMENTATION

## Purpose

Implement the Evidence-Grounded AI Risk Intelligence MVP incrementally
without changing frozen methodology.

## Mandatory source-of-truth documents

Codex must read `AGENTS.md`, `PROJECT_SPEC.md`, `ARCHITECTURE.md`, and
the design/product specifications referenced by each milestone.

Expected frozen specifications: - `docs/design-docs/risk-model-v1.md` -
`docs/design-docs/evidence-reliability-v1.md` -
`docs/design-docs/er-aggregation-v1.md` -
`docs/design-docs/data-dictionary-v1.md` -
`docs/design-docs/system-architecture-v1.md` -
`docs/product-specs/mvp-scope.md` - `docs/product-specs/ui-spec-v1.md`

## Global implementation rules

1.  One milestone at a time.
2.  Inspect the repository before changing code.
3.  Do not change frozen specifications to make implementation easier.
4.  Preserve provenance from risk result back to original evidence.
5.  Raw evidence is immutable.
6.  Typed missing values use `NULL` plus `availability_status`; never
    store the string `UNKNOWN` in numeric/date fields.
7.  ER `Unknown` exists at the belief layer and is not the same as
    missing-source status.
8.  LLM output is never original evidence and never directly changes
    validated values, reliability, risk beliefs, or ER aggregation.
9.  UI code must not contain core ingestion, validation, reliability,
    risk, or ER logic.
10. Every milestone requires automated tests and a completion report.

## Milestones

-   M0 Foundation and domain contracts
-   M1 Storage layer: Turso + R2 + local adapters
-   M2 Companies House governance ingestion
-   M3 Accounts acquisition and financial extraction
-   M4 Validation and evidence reliability
-   M5 — Risk Variable & Leaf Belief Engine
-   M6 — Hierarchical ER Aggregation Engine
-   M7 Streamlit UI
-   M8 Deployment, caching and public demo

## M5 → M6 interface

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

See `docs/implementation/M5-risk-variable-leaf-belief-engine.md` and
`docs/implementation/M6-hierarchical-er-aggregation-engine.md` for implementation acceptance criteria.

## Gate rule

Do not begin milestone N+1 until milestone N acceptance criteria pass
and the user has approved progression.
