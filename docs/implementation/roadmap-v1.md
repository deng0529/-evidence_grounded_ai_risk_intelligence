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

## M4 design authority and M4 → M5 interface

The [M4 frozen contract](../design-docs/m4-validation-evidence-reliability.md)
is authoritative for admissibility, versioned registry rules, conflict resolution
and explainable evidence reliability. The current step records that design only;
it does not authorize M4 production code, migrations or live data processing.

M4 persists validated facts and evidence sets with availability, provenance,
S/E/V/C/r, rule/policy versions and assessment context in Turso. Normal execution
uses structured M2/M3 records; unchanged evidence/version/context inputs support
deterministic reuse. M5 consumes those results and owns risk-variable calculation,
multi-input variable reliability and Reliability-to-Unknown. M4 does none of those
calculations. Follow the contract's authoritative clarifications for validation
independence, conservative classification and precision/selection. Inspect the
structured Turso handoff and report any required minimal extension before implementation.

## M5 → M6 interface

M5 v1.2 produces final Low / High / Unknown belief distributions for the active
registry: G1.1, G1.2, G2.2, F1.1, F2.2, F2.3. Financial leaves use the
explicitly selected reporting year and never fall back across years. Required-data
failure remains (0,0,1).

M6 consumes these leaves unchanged. It aggregates the three Governance leaves with
equal active-variable weights, the four Financial leaves with equal active-variable
weights, then combines Governance/Financial at 0.40/0.60. UI group labels are not
an intermediate mathematical layer in v1.2. M6 does not recompute M4/M5 outputs.

See `docs/implementation/M5-risk-variable-leaf-belief-engine.md` and
`docs/implementation/M6-hierarchical-er-aggregation-engine.md` for implementation acceptance criteria.

## Gate rule

Do not begin milestone N+1 until milestone N acceptance criteria pass
and the user has approved progression.
