# M7 — Deterministic Risk Explanation and Traceability

This milestone is the explanation layer; the later UI is M8 under the current
approved sequence. Earlier M7 UI plans remain historical. Frozen M4/M5/M6
mathematics, model v1.2 membership and importance weights are unchanged.

## API and architecture

```python
from risk_intelligence.services.explanation import ExplanationService

explanation = ExplanationService(database).for_assessment(assessment_id)
audit_json = explanation.model_dump_json(indent=2)
```

The service assembles a typed immutable application read model from existing SQL
records. It performs no writes, network requests, raw-evidence reads, scoring,
LLM calls or aggregation. No new table, migration or explanation snapshot is
needed. M8 receives resolved records; it need not query tables or rebuild lineage.

`AssessmentExplanation` contains assessment/version metadata, selected reporting
year, Overall, Governance/Financial domains and the six ordered variables.
`AggregationExplanation` carries the exact stored M6 result and ordered weighted
child edges. The hierarchy is Overall -> Governance/Financial -> registered M5
leaves. G1/G2/F1/F2 are never mathematical nodes. Overall edges retain 0.40/0.60;
domain edges retain stored equal weights. Nothing is averaged or recalculated.

Each `VariableExplanation.leaf` is the original M5 result and calculation,
including raw value, unit, reliability, availability, Low/High/Unknown, reasons,
trace, dates and version metadata. Names come from frozen risk-model-v1.2.
Financial variables retain the assessment's explicit reporting year.

Each input exposes its exact M4 fact, evidence-set or obligation record, including
validation/conflict state and reliability. Source observations, canonical mapping
or derivation components (where stored), evidence references, locators, source
retrieval metadata and optional documents are resolved using existing repositories.
Governance sets preserve their population members rather than pretending each
member is an individually validated financial fact. Obligation observation,
period, due and filing dates remain distinct in the original record.

M4 governance diagnostic evidence IDs include both field locators and resource
snapshots. M7 exposes locators in `evidence` and snapshot coverage/reuse records
in `snapshots`; it does not fabricate a field locator for a population snapshot.

## Integrity and missingness

M7 checks model/version identity, complete registered leaves and hierarchy,
child identities, input reliability/version agreement and structural provenance.
The additive `VariableRepository.get_persisted` reader checks SQL/JSON and input
edges without invoking M5 belief calculations. Existing `get`/save retain their
calculation verification. M7 performs structural checks, not a new M4 admission
or numerical risk assessment.

Unknown leaves retain availability, exact Unknown belief and persisted causes.
No estimates, hidden exclusions, weight redistribution or narrative judgments are
added. Absent optional document/financial lineage stays `None`; absent evidence
collections stay empty. A dangling required reference is an integrity error,
not evidence of absence. Missing assessments, M5/M6 results or reporting year
fail clearly. Historical v1/v1.1 requests explicitly fail as unsupported by M7;
their existing replay APIs remain unchanged.

## M8 limitations and operational boundaries

An input's evidence includes the supporting/diagnostic population recorded by M4;
not every cited item independently validates the target. Consult the retained
validation roles and reasons. Missing M3 semantic context is not reconstructed.
An absent normalization/derivation edge remains absent even if other provenance
exists. M7 exposes existing M4/M3 contracts and immutable retrieval metadata, not
raw documents or a fresh check of their availability in object storage.

## Real Golden verification

On 1 October 2026, the original v1.2 Pip & Nut assessment DB was copied to
`data/golden/pipnut-m7-20261001/assessment.sqlite3`, migrated with the existing
migration 013, and passed through the production M6 service. M7 then read its
persisted results. The original DB checksum remained unchanged.

`data/golden/pipnut-m7-20261001/explanation.json` contains all six variables and
three persisted parent nodes. F1.1 traces NET_ASSETS 1,083,960 and TOTAL_ASSETS
12,232,894, COMPANY scope, through their M4 results to PDF evidence locators,
retrieval/document identities and existing canonical lineage. Repeat calls and
JSON round-trip were identical; SQLite integrity and foreign-key checks passed.
These generated artifacts remain ignored/local. No cloud source was accessed.
