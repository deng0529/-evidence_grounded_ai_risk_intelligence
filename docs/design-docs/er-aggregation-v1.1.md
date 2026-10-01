# ER Aggregation Specification v1.1 — Simplified MVP Hierarchy

Status: **FROZEN FOR MVP v1.1 IMPLEMENTATION**
This amendment reuses the analytical ER formula, Unknown semantics, precision and invariants from `er-aggregation-v1.md`; it changes only the active hierarchy and weighting policy for risk-model-v1.1.

## Active aggregation hierarchy

M5 supplies seven final Low/High/Unknown leaf distributions.

Governance domain children: G1.1, G1.2, G2.2.
Financial domain children: F1.1, F2.2, F2.3, F3.1.

Within each domain, active children use equal importance weights:

- Governance: 1/3 each
- Financial: 1/4 each

The domain results are then combined into Overall using Governance=0.40 and Financial=0.60.

```text
Governance = ER(G1.1, G1.2, G2.2; equal active-variable weights)
Financial  = ER(F1.1, F2.2, F2.3, F3.1; equal active-variable weights)
Overall    = ER(Governance, Financial; 0.40, 0.60)
```

G1/G2/F1/F2/F3 remain UI/explanation group labels only; v1.1 does not mathematically aggregate them as intermediate nodes.

## Missing evidence

The existing rule is unchanged: a required-data failure is a retained leaf `(0,0,1)` and its importance is not redistributed because it is Unknown. Equal weights are determined from the model's active registry, not from which leaves happen to be available in a particular assessment.

## Extensibility

M6 must read domain membership and weighting policy from the model registry. It must not contain a seven-variable special case. A future model version may add groups/variables or use calibrated weights while preserving the same ER engine.
