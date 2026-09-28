# System Flow & Architecture v1

Evidence-Grounded AI Risk Intelligence
Pre-Codex MVP Design

# 1. Purpose

This document freezes the end-to-end logical flow of the MVP before implementation. It connects user interaction, source discovery, raw evidence preservation, extraction, validation, evidence reliability, risk-variable construction, ER aggregation, explanation and the Streamlit UI. It is an architectural contract, not an implementation script.

# 2. End-to-End System Flow

↓

↓

↓

↓

↓

↓

↓

↓

↓

↓

↓

↓

↓

# 3. Data-Lifecycle Principle

The architecture deliberately separates four data layers:

- RAW: source responses, documents and retrieval metadata. Preserve provenance; do not overwrite with cleaned values.

- STRUCTURED FACTS: normalized source-derived facts such as current_assets, director appointment dates and PSC records.

- DERIVED METRICS: calculated variables such as Current Ratio, Quick Ratio, Debt Burden and Director Turnover.

- ASSESSMENT RESULTS: Low/High/Unknown beliefs at variable, indicator, domain and overall levels.

A derived metric must never be stored as if it were a directly reported source fact.

# 4. LLM Boundary

# 5. Storage Boundary

Current MVP storage and application split:

- Local development: filesystem raw-evidence adapter behind the storage interfaces specified in `docs/implementation/M1-storage.md`; temporary downloads, parser artefacts and local fixtures remain under ignored data/cache directories.

- Turso for structured relational data: company metadata, source/document metadata, structured facts, validations, reliability values, variables, beliefs and processing-run records.

- Cloudflare R2: immutable raw evidence/object storage, linked to Turso metadata through source/document identifiers, retrieval timestamps and checksums. Raw PDFs, iXBRL and large JSON payloads belong in object storage, not Turso.

- Streamlit Community Cloud: MVP Python application and UI. FastAPI is deferred from the MVP.

- GitHub: code, schemas, migrations, tests, documentation and .env.example only. Never raw secrets or .env.

# 6. Reproducibility Contract

Every final risk result should be traceable through: assessment_run → variable_result → input facts → evidence records → source/document metadata. The system should record model/rule version, retrieval time and processing status. Re-running a company should create a new processing run rather than silently rewriting the audit trail.

# 7. UI Contract

The MVP UI must support both directions of traceability:

- Risk → Variable → Fact → Evidence

- Evidence → Fact → Variable → Risk

The UI should never present a single opaque AI score without Low/High/Unknown, evidence reliability and source drill-down.

# 8. Implementation Strategy for Codex

Give Codex the full architecture once, but implement it in bounded milestones. Codex should not be asked to create the entire MVP in one pass.

Milestone numbering follows `docs/implementation/roadmap-v1.md`:

- M0 Foundation and domain contracts.
- M1 Storage layer.
- M2 Companies House governance ingestion.
- M3 Accounts acquisition and financial extraction.
- M4 Validation and evidence reliability (Evidence Reliability Scheme v1).
- M5 — Risk Variable & Leaf Belief Engine.
- M6 — Hierarchical ER Aggregation Engine.
- M7 Streamlit UI.
- M8 Deployment, caching and public demo.

M5 produces the final Low / High / Unknown belief distribution for each of
G1.1, G1.2, G2.1, G2.2, G2.3, G3.1, F1.1, F1.2, F2.2, F2.3 and F3.1.
These 11 final distributions are M6 input, identified by variable code and
linked to the existing VariableResult records and assessment/model-version
context defined in `docs/design-docs/data-dictionary-v1.md`. Each distribution
is bounded in [0,1] and sums to 1 within the absolute tolerance defined in `docs/design-docs/er-aggregation-v1.md`, section 12.1.
Required-data failure remains (Low, High, Unknown) = (0, 0, 1); the leaf is
retained and its importance weight is not redistributed.

M5 ends at these final leaf distributions and performs no indicator-level,
domain-level or overall ER aggregation. M6 consumes them unchanged, applies
the frozen importance weights and aggregates Variables → Indicators → Domains
→ Overall, including frozen single-child pass-through. M6 must not recalculate
source facts, financial ratios, governance metrics, leaf thresholds, evidence
reliability or leaf belief distributions. S/E/V/C/r are not applied again by M6.
This interface clarifies responsibility only; it introduces no schema or
frozen-methodology change.

# 9. Design Gate Before M0

Before Codex begins M0, the following must be reviewed and frozen at MVP level: UI wireframe, Data Dictionary v1, Database Schema v1, raw/structured storage policy, LLM task list and output schemas, cloud/service boundary, secret names, required external accounts, and the implementation roadmap.

# 10. Status

STATUS: CANDIDATE FOR MVP ARCHITECTURE FREEZE

This flow should be updated only when the UI/Data Dictionary/Database Schema design reveals a missing architectural requirement. After that review it can be converted into repository Markdown and used as a standing contract for Codex.



| 1. USER / STREAMLIT UI<br>Search company name or enter Companies House number; select the legal entity; trigger analysis or open an existing analysis. |

| --- |





| 2. COMPANY RESOLUTION<br>Resolve company_number, legal name, status and core identity. The company number becomes the primary external identifier. |

| --- |





| 3. SOURCE DISCOVERY<br>Discover Companies House profile, officers, PSC, filing history, charges and accounts representations (iXBRL/PDF). Discover selected official-company-web sources only where required by the Data Dictionary. |

| --- |





| 4. RAW EVIDENCE INGESTION & PRESERVATION<br>Store source metadata and preserve retrievable raw payloads/documents or immutable references. No risk scoring occurs here. |

| --- |





| 5. DOCUMENT / DATA ROUTING<br>Route API JSON to structured parser; iXBRL to tag parser; native PDF to text/table parser; scanned pages to OCR; hybrid PDF page-by-page; narrative evidence to rule-based and, when needed, LLM-assisted extraction. |

| --- |





| 6. STRUCTURED FACT LAYER<br>Normalize extracted facts into typed records with value, unit, reporting period, source, extraction method and evidence location. Raw source facts remain distinct from derived metrics. |

| --- |





| 7. VALIDATION ENGINE<br>Run identity/period/currency checks, arithmetic checks, same-filing cross-representation checks and appropriate cross-source corroboration. Reconcile semantics before declaring conflict. |

| --- |





| 8. EVIDENCE RELIABILITY ENGINE<br>M4 applies Evidence Reliability Scheme v1: Source Quality S, Extraction Quality E, Validation V and Conflict C. Missing or unresolved evidence follows frozen fail-safe rules; M5 maps the resulting reliability and availability to final leaf Unknown. |

| --- |





| 9. M5 — Risk Variable & Leaf Belief Engine: variable values<br>Construct the 11 frozen risk variables from validated facts. Use latest complete period for current financial state; retain earlier comparable periods for trend/context. Governance variables use their defined event windows. |

| --- |





| 10. M5 — Risk Variable & Leaf Belief Engine: final leaf beliefs<br>Map each variable to provisional Low/High belief using frozen reference levels, then apply frozen Reliability-to-Unknown using M4 reliability results to obtain final Low/High/Unknown. These 11 leaf distributions are M5 output and M6 input. |

| --- |





| 11. M6 — Hierarchical ER Aggregation Engine<br>Accept final M5 leaf beliefs unchanged and aggregate them to six indicators, then Governance and Financial domains, then Overall Company Risk, using frozen importance weights and ER methodology. |

| --- |





| 12. EXPLANATION ENGINE<br>Generate deterministic explanation data first. Optional LLM produces readable explanations only from supplied structured results and evidence; it cannot alter facts, reliability, weights or risk beliefs. |

| --- |





| 13. PERSIST RESULTS<br>Store processing run, facts, validations, variable values, beliefs, indicator/domain/overall results and provenance so a result can be reproduced and audited. |

| --- |





| 14. STREAMLIT PRESENTATION<br>Present Overview, Risk Detail, Evidence Explorer, History and Methodology. Support drill-down Risk → Variable → Fact → Evidence. |

| --- |





| LLM MAY | LLM MUST NOT |

| --- | --- |

| Extract structured facts from difficult narrative when deterministic methods are insufficient. | Invent missing numeric values or treat inference as source evidence. |

| Classify/rewrite narrative disclosures into a controlled schema with evidence spans. | Set final S/E/V/C reliability values autonomously. |

| Generate user-facing explanations from deterministic risk results and evidence. | Change thresholds, weights, ER outputs or risk beliefs. |

| Assist with semantic matching subject to deterministic validation and evidence traceability. | Silently resolve material source conflicts. |
