# Codex Prompt Template - Milestone Completion

Review the current milestone against its acceptance criteria and the
frozen specifications.

1.  Run the relevant automated tests.
2.  Report pass/fail results.
3.  List files changed.
4.  Explain how provenance, missing-data semantics and fail-safe
    behavior are preserved where applicable.
5.  Identify unresolved issues, assumptions or technical debt.
6.  Confirm that no work from the next milestone was implemented.

Do not begin the next milestone.

## M5 / M6 responsibility check

Use M5 — Risk Variable & Leaf Belief Engine and M6 — Hierarchical ER
Aggregation Engine as defined in `docs/implementation/roadmap-v1.md`.
Verify that M5 computes the 11 variable values and final leaf beliefs using
M4 reliability results, and M6 consumes those final beliefs unchanged for
weighted hierarchical ER. M6 must not recalculate facts, metrics, thresholds,
reliability or leaf beliefs; M5 must not aggregate parent nodes. Preserve all
frozen formulas, thresholds, weights, reliability rules and ER reference values.
