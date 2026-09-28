# Codex Prompt Template - Milestone Start

Read `AGENTS.md`, `PROJECT_SPEC.md`, `ARCHITECTURE.md`,
`docs/implementation/roadmap-v1.md`, and the current milestone
specification, including every frozen specification referenced by that
milestone.

Before changing code: 1. Inspect the existing repository. 2. Summarize
your understanding of the milestone. 3. List the files you propose to
create or modify. 4. List the tests you will add or update. 5. Identify
any ambiguity or conflict with a frozen specification.

Do not implement work outside the current milestone. Do not modify
frozen specifications unless explicitly instructed.

After the plan is clear, implement the milestone and run the relevant
tests.

## M5 / M6 responsibility check

Use M5 — Risk Variable & Leaf Belief Engine and M6 — Hierarchical ER
Aggregation Engine as defined in `docs/implementation/roadmap-v1.md`.
Verify that M5 computes the 11 variable values and final leaf beliefs using
M4 reliability results, and M6 consumes those final beliefs unchanged for
weighted hierarchical ER. M6 must not recalculate facts, metrics, thresholds,
reliability or leaf beliefs; M5 must not aggregate parent nodes. Preserve all
frozen formulas, thresholds, weights, reliability rules and ER reference values.
