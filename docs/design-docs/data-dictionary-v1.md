# Evidence-Grounded AI Risk Intelligence
Data Dictionary v1

FROZEN CANDIDATE FOR MVP IMPLEMENTATION

Purpose: define the end-to-end data contract from external source and immutable raw evidence through structured facts, validation, reliability, risk variables, hierarchical ER aggregation, assessment metadata and UI traceability.

# 1. Architecture and Storage Contract

Production storage is deliberately separated by responsibility. GitHub stores code, tests and implementation Markdown. Cloudflare R2 stores immutable raw evidence. Turso stores structured metadata, facts, validation, reliability and assessment results. Streamlit Community Cloud runs the Python application, risk/ER engines and UI. Local data/raw is a development cache only.

# 2. Layer 1 - Company, Source, Document and Raw Evidence

# 3. Layer 2 - Structured Governance Facts

# 4. Layer 2 - Structured Financial Facts

Financial numeric source priority: iXBRL direct extraction -> native PDF deterministic extraction -> OCR deterministic extraction -> LLM-assisted candidate extraction only when necessary. LLM output is never an original evidence source.

# 5. Financial Fact Record

# 6. Evidence Location and Extraction Methods

ExtractionMethod enum:

API_DIRECT; IXBRL_DIRECT; PDF_NATIVE_DETERMINISTIC; PDF_OCR_DETERMINISTIC; LLM_NATIVE_TEXT; LLM_OCR_TEXT; DERIVED.

# 7. Layer 3 - Validation Dictionary

# 8. Layer 4 - Evidence Reliability

Reliability is an evidence-quality measure applied at the leaf variable before hierarchical ER.

# 9. Missing, NULL and ER Unknown Semantics

A missing fact is never stored as the text 'UNKNOWN'. Typed value fields remain NULL and an availability_status records why the value is unavailable. ER Unknown is produced only at the risk variable belief layer. Missing source data and uncertainty belief are therefore distinct.

Rule: absence of a reported numeric value must never be automatically interpreted as zero. Supporting text or optional facts do not create ER Unknown unless they are required inputs to a risk variable.

# 10. Layer 5 - Risk Variable Dictionary

variable_result stores raw_value, references, raw Low/High belief, reliability r, final Low/High/Unknown, availability_status and model versions. variable_fact_link records the exact fact inputs and roles.

Reliability discount: beta_L = r * betaHat_L; beta_H = r * betaHat_H; beta_U = 1-r. If the variable is unusable due to required-data failure: Low=0, High=0, Unknown=1.

# 11. Layer 6 - Hierarchical ER Results

# 12. Layer 7 - Assessment, Processing and UI Metadata

# 13. Data Types and Precision

Stored computational results retain full practical numerical precision, not
UI-rounded beliefs. Apply the authoritative calculation, storage and numerical
comparison rules in `docs/design-docs/er-aggregation-v1.md`, section 12.1;
presentation formatting must not overwrite authoritative values.

# 14. Provenance and Lineage Contract

Every material risk result must be traceable in both directions: Risk Result -> Variable -> Derived Calculation -> Structured Fact -> Evidence Locator -> Document/Source -> Raw R2 Object -> Original public source. Conversely, a raw evidence object can be traced forward to facts and assessments that used it.

Raw evidence is immutable. Repeated retrievals retain retrieval timestamps and checksums. A registry source is authoritative for the filed/public record but is not treated as independent proof that every submitted company statement is true.

# 15. Model and Dictionary Versioning

# 16. Codex Implementation Rules

- Read AGENTS.md, ARCHITECTURE.md and the milestone specification before changes.

- Do not modify frozen risk, reliability, ER or data-dictionary semantics without an explicit design change.

- Preserve typed NULL + availability_status semantics; never write 'UNKNOWN' into numeric/date fields.

- Keep UI separate from application/domain logic.

- Raw evidence storage and structured database access must be behind interfaces so local development and cloud implementations can be swapped.

- Do not use LLM output as original evidence or allow LLMs to change validated values, reliability, beliefs or ER results.

- Implement one milestone at a time and add tests for acceptance criteria.

- Fail safely: partial/missing evidence produces controlled status and Unknown where required, never fabricated values.

# 17. Implementation Readiness

This Data Dictionary v1 is intended to be converted into docs/design-docs/data-dictionary-v1.md after human review. The repository Markdown becomes the implementation source of truth. Next artifact: Implementation Roadmap v1 with M0-M8 milestone specifications and reusable Codex prompt templates.



| Asset | Production location | Rule |

| --- | --- | --- |

| Code / tests / docs | GitHub | Implementation source of truth is repository Markdown. |

| Raw API JSON / PDF / iXBRL / XHTML / optional HTML | Cloudflare R2 | Immutable; timestamped retrieval; checksum retained. |

| Structured metadata and facts | Turso | Typed, queryable, provenance-linked. |

| Validation / reliability / variable / ER / assessment results | Turso | Versioned and reproducible. |

| Application execution + UI | Streamlit Community Cloud | Runs server-side Python; FastAPI not required for MVP v1. |

| Local raw files | data/raw/ | Development cache; not production evidence store. |





| Entity | Key fields | Notes |

| --- | --- | --- |

| Company | company_id; company_number; company_name; company_status; company_type; incorporation_date; registered_office; sic_codes | company_number is canonical external identity and must be TEXT. |

| Source | source_id; company_id; source_type; source_name; source_url; retrieved_at; retrieval_status; http_status; checksum; processing_run_id | Represents where information was obtained. |

| Document | document_id; company_id; source_id; filing_id; document_type; representation_type; period_start/end; filing_date; object_path; checksum | Metadata points to raw object in R2. |

| Raw Evidence | R2 object + retrieval event | Raw content is never overwritten; repeated retrievals retain timestamp/checksum even if deduplicated physically. |





| Canonical fact | Type | Required by | Primary | Fallback | Validation | Failure mapping |

| --- | --- | --- | --- | --- | --- | --- |

| ACCOUNTS_PERIOD_END | DATE | G1.1 / financial period | CH filing history/accounts | iXBRL/PDF | Period and document consistency | Unavailable -> affected calculation Unknown |

| ACCOUNTS_DUE_DATE | DATE | G1.1 | CH profile where available + statutory rule | filing metadata | company type + period rule | Cannot establish -> variable Unknown |

| ACCOUNTS_FILED_DATE | DATE | G1.1 | CH filing history | document metadata | filing/document consistency | Retrieval failure -> variable Unknown |

| CONFIRMATION_DUE_DATE | DATE | G1.2 | CH current data + statutory logic | filing history | filing chronology | Cannot establish -> variable Unknown |

| CONFIRMATION_FILED_DATE | DATE | G1.2 | CH filing history | - | type/date consistency | Retrieval failure -> variable Unknown |

| DIRECTOR_APPOINTED_ON | DATE | G2.1/G2.2/G2.3 | CH Officers API | filing history | identity + chronology | Unresolved required record -> affected variable Unknown |

| DIRECTOR_RESIGNED_ON | DATE/NULL | G2.1/G2.3 | CH Officers API | filing history | chronology | NULL may legitimately mean active |

| DIRECTOR_ACTIVE_STATUS | BOOLEAN | G2.1/G2.2/G2.3 | Derived from officer record | - | appointment/resignation logic | Conflict -> affected variable Unknown |

| PSC_NOTIFIED_ON | DATE/NULL | G3.1 | CH PSC API | filing history | identity + chronology | Insufficient history -> G3.1 Unknown |

| PSC_CEASED_ON | DATE/NULL | G3.1 | CH PSC API | filing history | chronology | NULL may legitimately mean active |

| PSC_NATURE_OF_CONTROL | ENUM/JSON | G3.1 support | CH PSC API | filing document | allowed/control values | Missing support fact retained; does not automatically create ER Unknown |





| Canonical concept | Type | Required by | Primary | Fallback | Validation |

| --- | --- | --- | --- | --- | --- |

| CURRENT_ASSETS | NUMERIC | F2.2,F2.3 | iXBRL | PDF | period/currency; BS arithmetic; cross-source |

| CURRENT_LIABILITIES | NUMERIC | F2.2,F2.3 | iXBRL | PDF | period/currency; BS arithmetic; cross-source |

| INVENTORY | NUMERIC | F2.3 | iXBRL | PDF | period; current-assets composition |

| NET_ASSETS | NUMERIC | F1.1,F1.2 | iXBRL | PDF | BS arithmetic; cross-source |

| TOTAL_ASSETS | NUMERIC | F1.1,F3.1 | iXBRL | PDF | component arithmetic; period |

| INTEREST_BEARING_DEBT | NUMERIC/COMPOSITE | F3.1 | iXBRL + notes | PDF borrowing notes | component reconciliation; exclude ordinary trade/tax/accrual items |

| FIXED_ASSETS | NUMERIC | support | iXBRL | PDF | arithmetic support |

| CASH | NUMERIC | support | iXBRL | PDF | period/currency |

| DEBTORS | NUMERIC | support | iXBRL | PDF | period/currency |

| TOTAL_LIABILITIES | NUMERIC | support | iXBRL | PDF | BS arithmetic |

| BANK_LOANS | NUMERIC | F3.1 component | iXBRL/notes | PDF | debt classification |

| OTHER_LOANS | NUMERIC | F3.1 component | iXBRL/notes | PDF | debt classification |

| INVOICE_FINANCING | NUMERIC | F3.1 component | iXBRL/notes | PDF | debt classification |

| OTHER_INTEREST_BEARING_BORROWINGS | NUMERIC | F3.1 component | iXBRL/notes | PDF | debt classification |





| Field | Type / rule |

| --- | --- |

| financial_fact_id | internal ID |

| company_id | FK |

| canonical_concept | internal controlled concept |

| source_concept | original iXBRL/PDF label |

| value_numeric | DECIMAL/INTEGER; NULL when unavailable |

| currency / unit | e.g. GBP |

| period_start / period_end | DATE |

| period_type | INSTANT / DURATION |

| period_length_days | INTEGER where applicable |

| comparability_status | COMPARABLE / NON_COMPARABLE / REVIEW_REQUIRED / NOT_APPLICABLE |

| source_id / document_id | provenance FK |

| evidence_location | structured locator |

| extraction_method | controlled enum |

| availability_status | controlled enum |

| processing_run_id | FK |





| Source form | Locator |

| --- | --- |

| API | JSON_PATH + endpoint/reference |

| iXBRL | IXBRL_FACT + concept + context_id |

| PDF | PDF_REGION + page + section/table + label |





| Field | Meaning |

| --- | --- |

| validation_id | unique result ID |

| fact_id | validated fact/candidate |

| validation_type | SOURCE_CONSISTENCY / PERIOD_CONSISTENCY / CURRENCY_CONSISTENCY / ARITHMETIC / CROSS_SOURCE / TEMPORAL / DUPLICATE |

| rule_code | specific deterministic rule |

| status | PASS / WARNING / FAIL |

| expected_value / observed_value | optional typed comparison values |

| tolerance | optional numeric tolerance |

| severity | INFO / WARNING / FAIL |

| details | human-readable result |

| validated_at | UTC timestamp |

| processing_run_id | FK |





| Field | Rule |

| --- | --- |

| source_quality_s | S |

| extraction_quality_e | E |

| validation_factor_v | V |

| conflict_factor_c | C |

| base_reliability | S x E |

| validated_reliability | r_v = r_base + (1-r_base)V |

| final_reliability_r | r = r_v(1-C), capped 0..0.99 |

| hard_fail | boolean |

| hard_fail_reason | controlled reason |

| reliability_model_version | v1 |





| Availability status | Meaning | Value handling | Risk mapping |

| --- | --- | --- | --- |

| AVAILABLE | usable fact available | typed value present | calculate normally |

| NOT_DISCLOSED | source does not disclose required fact | NULL | if required -> affected variable Unknown |

| NOT_APPLICABLE | fact does not apply | NULL | apply variable-specific rule; never invent zero |

| RETRIEVAL_FAILED | source could not be retrieved | NULL | if required -> affected variable Unknown |

| EXTRACTION_FAILED | evidence retrieved but extraction failed | NULL/candidate retained separately | if required -> affected variable Unknown |

| VALIDATION_FAILED | candidate found but failed validation | candidate retained, not promoted as validated fact | if unresolved and required -> Unknown |

| CONFLICT_UNRESOLVED | material source conflict unresolved | candidate values retained | hard fail r=0 -> variable Unknown |

| NON_COMPARABLE | facts valid but periods not comparable | facts retained | time-dependent variable Unknown |





| Code | Variable | Required facts | Unit | Direction |

| --- | --- | --- | --- | --- |

| G1.1 | Accounts Filing Lateness | accounts_due_date; accounts_filed_date | days | HIGHER_IS_RISKIER |

| G1.2 | Confirmation Statement Lateness | confirmation_due_date; confirmation_filed_date | days | HIGHER_IS_RISKIER |

| G2.1 | Director Turnover - 24m | director appointment/resignation events | ratio | HIGHER_IS_RISKIER |

| G2.2 | Median Tenure of Active Directors | active directors; appointed_on | years | LOWER_IS_RISKIER |

| G2.3 | Director Change Concentration - 90d | director events; active population | ratio | HIGHER_IS_RISKIER |

| G3.1 | PSC / Control Change Frequency - 36m | PSC/control events | count | HIGHER_IS_RISKIER |

| F1.1 | Equity / Total Assets | NET_ASSETS; TOTAL_ASSETS | ratio | LOWER_IS_RISKIER |

| F1.2 | Net Asset Trend | NET_ASSETS(t); NET_ASSETS(t-1) | ratio | LOWER_IS_RISKIER |

| F2.2 | Current Ratio | CURRENT_ASSETS; CURRENT_LIABILITIES | ratio | LOWER_IS_RISKIER |

| F2.3 | Quick Ratio | CURRENT_ASSETS; INVENTORY; CURRENT_LIABILITIES | ratio | LOWER_IS_RISKIER |

| F3.1 | Debt Burden | INTEREST_BEARING_DEBT; TOTAL_ASSETS | ratio | HIGHER_IS_RISKIER |





| Entity | Fields / rule |

| --- | --- |

| aggregation_result | assessment_id; node_code; node_type; node_name; low_belief; high_belief; unknown_belief; er_model_version; calculated_at |

| node_type | INDICATOR / DOMAIN / OVERALL |

| aggregation_input | aggregation_result_id; child_code; child_result_id; importance_weight |

| Hierarchy | Variables -> G1/G2/G3/F1/F2/F3 -> GOVERNANCE/FINANCIAL -> OVERALL |

| Weight rule | Importance weight remains separate from reliability; weight-generated unassigned mass must not be labelled evidence Unknown. |





| Entity | Key fields |

| --- | --- |

| assessment | assessment_id; company_id; assessment_date; status COMPLETE/PARTIAL/FAILED; data_current_to; risk_model_version; reliability_model_version; er_model_version; data_dictionary_version |

| processing_run | processing_run_id; company_id; started_at; completed_at; status; current_stage; trigger_type LIVE/REFRESH/DEMO_PRECOMPUTE; error_code; error_message; app_version |

| risk_driver | assessment_id; variable_result_id; rank; driver_metric; driver_value; method (MVP: WEIGHT_X_HIGH_BELIEF) |

| explanation | assessment_id; scope; generated_text; model_name; prompt_version; generated_at. Explanation is never a Fact and never changes scores. |





| Type | Rule |

| --- | --- |

| Company number | TEXT; never integer (e.g. SC137690). |

| Money | INTEGER in smallest appropriate reporting unit or exact DECIMAL; never binary float. |

| Ratio / belief / reliability | DECIMAL; belief and reliability constrained to 0..1. |

| Date | ISO YYYY-MM-DD. |

| Timestamp | UTC ISO-8601. |

| Text | TEXT; NULL if unavailable, not the literal string UNKNOWN. |

| Boolean | BOOLEAN / constrained integer representation. |

| Enum | controlled values defined by application/domain model. |

| JSON | only where structure is inherently variable (e.g. nature_of_control); not a substitute for typed core facts. |





| Version field | MVP value |

| --- | --- |

| data_dictionary_version | 1.0 |

| risk_model_version | 1 |

| reliability_model_version | 1 |

| er_model_version | 1 |
