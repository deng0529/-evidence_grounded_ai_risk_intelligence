# M5 v1.1 — Seven-Leaf Single-Period Amendment

Authority: `docs/design-docs/risk-model-v1.1.md`.

M5 v1.1 emits exactly the active registry for risk-model-v1.1: G1.1, G1.2, G2.2, F1.1, F2.2, F2.3, F3.1. Historical calculators for deferred variables may remain in source for future versioned reuse but are not invoked by v1.1 orchestration.

Every v1.1 assessment persists an explicit financial reporting year. Financial selection is restricted to that year and never silently falls back across years. M4 validation/reliability semantics and the one-time reliability-to-Unknown rule are unchanged.

The M5 service iterates the active model registry rather than a fixed seven-item service sequence. Persistence and M6 handoff validate against that registry.
