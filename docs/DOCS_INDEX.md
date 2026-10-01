# Documentation Index — Codex Construction Pack v1

## Implementation source of truth

For MVP implementation, use the following precedence:

1. `AGENTS.md`
2. Frozen/versioned design and product specifications listed below
3. Current milestone under `docs/implementation/`
4. `PROJECT_SPEC.md` and `ARCHITECTURE.md` for project-level context
5. `docs/archive/pre-freeze/` for historical context only; archived files are NOT implementation authority

## Frozen design specifications
- `docs/design-docs/risk-model-v1.2.md` — active MVP model: six leaves, explicit single reporting year, 0.40/0.60 domains, equal active-variable weights
- `docs/design-docs/er-aggregation-v1.2.md` — active MVP aggregation hierarchy; reuses ER v1 mathematics
- `docs/design-docs/m5-risk-variable-leaf-belief.md` — historical v1 M5 operational policies; retained for deferred-variable implementation history
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
- `docs/implementation/M7-explanation-traceability.md` — current M7 deterministic explanation layer; M8 owns the later UI
- `docs/implementation/M7-streamlit-ui.md` — historical milestone numbering; superseded for current M7 scope
- `docs/implementation/M8-application-streamlit.md` — current M8 application/UI integration; M9 owns deployment
- `docs/implementation/M8-deployment.md` — historical milestone numbering
- reusable prompts in `docs/implementation/prompts/`

## Risk implementation boundary

M4 computes evidence reliability. For active risk-model-v1.2, M5 computes the six registered variable values and final
Low / High / Unknown leaf beliefs, applying Reliability-to-Unknown once.
Those final leaf distributions are M6 input. M6 applies equal active-variable weights within each domain, the frozen 0.40/0.60 domain weights, and ER only; it does not recompute facts, metrics,
thresholds, reliability or leaf beliefs. The complete handoff is documented
in `docs/implementation/roadmap-v1.md`.

## Important rule
If an archived/pre-freeze document conflicts with a frozen/versioned specification, the frozen/versioned specification governs. Codex must not resolve such conflicts by changing the frozen specification.

## Historical model amendments

- `docs/design-docs/risk-model-v1.1.md` — preserved seven-variable model, superseded for new assessments by v1.2.
- `docs/design-docs/er-aggregation-v1.1.md` — historical seven-leaf hierarchy.
- `docs/implementation/M5-risk-variable-leaf-belief-engine-v1.1.md` — historical amendment.
- `docs/implementation/M5-risk-variable-leaf-belief-engine-v1.2.md` — current six-leaf M5 contract.
- `docs/implementation/m5-golden-example.md` — versioned real evidence Golden results and reproduction.
