# Codex Prompt Template - Specification Review

Review the implementation against `AGENTS.md`, the current milestone
specification and all referenced frozen specifications.

Focus on: - deviations from frozen methodology - provenance/lineage
breaks - incorrect NULL / availability / ER Unknown handling - LLM
crossing the allowed boundary - UI/domain coupling - missing tests -
secrets or raw-data storage mistakes - silent fallbacks or fabricated
values

Return findings first, ordered by severity, with file and code
references. Do not make unrelated refactors.

## M5 / M6 responsibility check

Use M5 — Risk Variable & Leaf Belief Engine and M6 — Hierarchical ER
Aggregation Engine as defined in `docs/implementation/roadmap-v1.md`.
Verify that M5 computes the 11 variable values and final leaf beliefs using
M4 reliability results, and M6 consumes those final beliefs unchanged for
weighted hierarchical ER. M6 must not recalculate facts, metrics, thresholds,
reliability or leaf beliefs; M5 must not aggregate parent nodes. Preserve all
frozen formulas, thresholds, weights, reliability rules and ER reference values.
