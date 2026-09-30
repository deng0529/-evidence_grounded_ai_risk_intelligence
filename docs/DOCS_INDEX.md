# Documentation Index — Codex Construction Pack v1

## Implementation source of truth

For MVP implementation, use the following precedence:

1. `AGENTS.md`
2. Frozen/versioned design and product specifications listed below
3. Current milestone under `docs/implementation/`
4. `PROJECT_SPEC.md` and `ARCHITECTURE.md` for project-level context
5. `docs/archive/pre-freeze/` for historical context only; archived files are NOT implementation authority

## Frozen design specifications
- `docs/design-docs/m5-risk-variable-leaf-belief.md` — authoritative M5 operational policies; approved additive validated deadline/obligation handoff
- `docs/design-docs/m4-validation-evidence-reliability.md` — authoritative M4 admissibility, validation registry, conflicts, S/E/V/C/r, validated facts/evidence sets and reuse; current step is documentation only
- `docs/design-docs/m3-accounts-financial-ingestion.md` — M3 accounts acquisition, source/canonical facts, reuse and Data Readiness Report contract
- `docs/design-docs/risk-model-v1.md`
- `docs/design-docs/evidence-reliability-v1.md` — formula background; the later M4 contract governs refined M4 classification, independence and stage boundaries
- `docs/design-docs/er-aggregation-v1.md`
- `docs/design-docs/data-dictionary-v1.md`
- `docs/design-docs/system-architecture-v1.md`

## Frozen product specifications
- `docs/product-specs/mvp-scope.md`
- `docs/product-specs/ui-spec-v1.md`

## Construction plan
- `docs/implementation/roadmap-v1.md`
- `docs/implementation/M0-foundation.md`
- `docs/implementation/M1-storage.md`
- `docs/implementation/m1-storage-notes.md` — implemented storage usage and boundaries; does not replace frozen specifications
- `docs/implementation/M2-governance-ingestion.md`
- `docs/implementation/m2-ingestion-notes.md` - expanded Companies House API scope, compatibility and usage
- `docs/implementation/M3-accounts-extraction.md`
- `docs/implementation/m3-ingestion-notes.md` — implemented routes, reuse, operational limits and smoke verification
- `docs/implementation/M4-validation-reliability.md`
- `docs/implementation/M5-risk-variable-leaf-belief-engine.md` — M5 — Risk Variable & Leaf Belief Engine
- `docs/implementation/M6-hierarchical-er-aggregation-engine.md` — M6 — Hierarchical ER Aggregation Engine
- `docs/implementation/M7-streamlit-ui.md`
- `docs/implementation/M8-deployment.md`
- reusable prompts in `docs/implementation/prompts/`

## Risk implementation boundary

M4 computes evidence reliability. M5 computes all 11 variable values and final
Low / High / Unknown leaf beliefs, applying Reliability-to-Unknown once.
Those final leaf distributions are M6 input. M6 applies frozen importance
weights and hierarchical ER only; it does not recompute facts, metrics,
thresholds, reliability or leaf beliefs. The complete handoff is documented
in `docs/implementation/roadmap-v1.md`.

## Important rule
If an archived/pre-freeze document conflicts with a frozen/versioned specification, the frozen/versioned specification governs. Codex must not resolve such conflicts by changing the frozen specification.
