# M6 — ER Aggregation Engine for MVP v1.2

## Objective

Consume the six final M5 leaf beliefs for risk-model-v1.2 and apply the unchanged analytical ER formula from `docs/design-docs/er-aggregation-v1.md` using the simplified hierarchy in `docs/design-docs/er-aggregation-v1.2.md`.

## v1.2 hierarchy

- Governance = ER(G1.1, G1.2, G2.2), equal active-variable weights.
- Financial = ER(F1.1, F2.2, F2.3), equal active-variable weights.
- Overall = ER(Governance, Financial), weights 0.40 / 0.60.

G1/G2/F1/F2 are explanation/UI groups, not mathematical aggregation nodes in v1.2.

## Architecture requirement

The ER implementation must be generic. Domain membership, active variables and weighting policy come from the versioned model registry. Do not hard-code a six-variable algorithm. Equal weights are calculated from the active variables registered in a domain, not from available/non-Unknown leaves, so missing evidence never causes runtime weight redistribution.

M6 must not recalculate facts, ratios, governance metrics, thresholds, M4 reliability or M5 leaf beliefs.

## Verification

Retain the analytical ER numerical invariants and 1e-8 absolute tolerance from ER v1. Add v1.2 tests for all-Low, all-High, all-Unknown, one Unknown leaf without redistribution, equal-weight domain aggregation, 0.40/0.60 top aggregation, order invariance and registry-driven extension with a synthetic extra variable.

## Implemented persistence and audit contract

M6 persists only parent beliefs and exact weighted child edges. Migration `013_m6_aggregation_results.sql` creates immutable `m6_aggregation_result` and `m6_aggregation_input` tables. The stored parent record contains full-precision Low/High/Unknown, node identity and ER model version; each input edge records child code, child result identity and importance weight.

The engine is split into three boundaries:

1. `risk_intelligence.aggregation.er_aggregate` implements only the frozen analytical ER mathematics.
2. `AggregationService` reads the versioned YAML registry, consumes the complete persisted M5 handoff, constructs Governance/Financial and then Overall, and never recalculates evidence or leaves.
3. `AggregationRepository` provides immutable persistence and replayable child lineage.

For v1.2, only `GOVERNANCE`, `FINANCIAL`, and `OVERALL` are mathematical parent nodes. UI group labels G1/G2/F1/F2 are deliberately not persisted as aggregation results.

The ER model version is explicitly configured as `er_model_version: "1.2"` in the same versioned YAML model specification. Importance weights must sum to one at each parent. Equal within-domain weights are calculated from registered children, including Unknown children, so evidence missingness never redistributes importance.
