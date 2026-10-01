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
