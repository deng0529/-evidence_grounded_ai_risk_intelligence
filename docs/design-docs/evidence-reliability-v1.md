# Evidence Reliability Scheme v1

Formula background: Evidence Reliability Scheme v1. The later authoritative
[M4 frozen contract](m4-validation-evidence-reliability.md) governs M4 execution.
It refines critical-transformation E classification, independent validation V,
resolved/unresolved conflict handling and fact/evidence-set outputs. Older route-
based E tables and rule-count examples below must not override those refinements.
Unknown conversion and multi-input variable reliability belong to M5; ER belongs
to M6. Historical tables/examples are retained, not silently rewritten. See the
M4 contract's repository-review appendix for remaining implementation questions.

Evidence-Grounded AI Risk Intelligence
MVP Evidence Reliability and Uncertainty Method
26 September 2026

Purpose. This document defines a deliberately simple initial method for converting evidence quality into an Evidence Reliability value r, which is then represented explicitly as Unknown belief in the risk model. The method is intended for the MVP and is designed so that it can later be replaced by a more empirically calibrated reliability model without changing the overall system architecture.

# 1. Core Principle

Risk importance and evidence reliability are separate concepts. Importance weights describe how much a risk variable matters to the overall assessment. Evidence reliability describes how strongly the system can rely on the evidence used for a particular observation.

The LLM is never treated as the evidence source. An LLM may be an extraction or interpretation method, but the underlying evidence remains the Companies House API, iXBRL filing, filed PDF, official website, or other traceable source.

# 2. MVP Reliability Components

Metric-validity issues such as missing required components or clearly non-comparable reporting periods are not separately scored in this scheme. They are handled by explicit fail-safe rules that can force the derived metric to Unknown.

# 3. Source Quality (S) — Initial Heuristic Values

Native and scanned versions of the same official filed PDF have the same Source Quality. The difference between native text and OCR is represented in Extraction Quality, not Source Quality.

# 4. Extraction Quality (E) — Initial Heuristic Values

# 5. PDF Classification and Extraction Routing

The ingestion pipeline should automatically classify PDF pages as Native, Scanned, or Hybrid. Native pages contain meaningful extractable text objects. Scanned pages are predominantly page images with little or no usable text. Hybrid documents contain a mixture or an unreliable OCR text layer.

Routing rule: use direct text/table parsing for usable native pages; OCR only where needed; and retain page-level classification so that extraction reliability can reflect the actual path used. Where structured iXBRL is available for numeric financial facts, iXBRL should normally be the primary extraction route and the PDF should support narrative extraction and/or validation.

# 6. Base Reliability Formula

Base reliability:  r_base = S × E

This intentionally requires both a credible source and a credible extraction path. A highly authoritative source does not make an incorrectly extracted value reliable.

# 7. Validation Strength (V)

Validated reliability:  r_v = r_base + (1 − r_base) × V

Validation therefore removes a proportion of the remaining uncertainty rather than adding an arbitrary fixed number of reliability points.

# 8. Cross-Validation Rules

- Structural validation: company number, company name, reporting period, currency and document type must match the intended record.

- Internal arithmetic validation: test identities such as Current Assets − Current Liabilities = Net Current Assets where the filing supplies the relevant fields.

- Same-filing cross-representation validation: compare iXBRL and PDF values from the same filing. This is useful confirmation but is not treated as an independent source.

- Cross-source corroboration: use another source only when it supports the same proposition. For example, a Charges register record may corroborate the existence of secured financing, but does not automatically validate a debt amount.

- Semantic reconciliation must occur before declaring a conflict. Cash and cash equivalents, group and company figures, or total debt and bank loans must not be treated as identical concepts without evidence.

# 9. Conflict Penalty (C)

Final reliability:  r = r_v × (1 − C), capped at 0.99

# 10. Fail-Safe Rules

# 11. Interface with ER Aggregation

Evidence Reliability r is a leaf-variable evidence-quality measure. In the MVP it is converted explicitly into variable-level Unknown BEFORE hierarchical ER aggregation. It is not passed directly as, or claimed to be mathematically identical to, the reliability parameter of the 2013 ER Rule/WBDR formulation.

The sequence is: provisional risk belief → evidence reliability discount → variable belief (Low, High, Unknown) → Hierarchical ER. Once a leaf belief has been reliability-adjusted, S, E, V, C and r are not applied again at indicator, domain or overall levels; this prevents double-counting evidence quality.

Importance weights used by ER remain conceptually separate from evidence reliability. Weight-generated unassigned mass must not be reported to users as evidence Unknown. The aggregation implementation is governed by ER Aggregation Specification v1.

# 12. Reliability to ER Belief

The risk transformation is performed independently first, producing provisional Low and High beliefs (β̂L, β̂H). Evidence reliability then discounts those beliefs and transfers the unsupported portion to Unknown.

βL = r × β̂L

βH = r × β̂H

βU = 1 − r

Therefore βL + βH + βU = 1.

Unknown is evidence uncertainty, not medium risk. Reliability is also not a probability that the company will fail.

# 13. Worked MVP Examples

## 13.1 LODI — Current Ratio via iXBRL

Illustrative path: S = 0.97 (Companies House iXBRL), E = 0.98 (direct tag), strong validation V = 0.60, no material conflict C = 0. r_base = 0.9506; r ≈ 0.980. If the raw Current Ratio maps to Low = 100%, the reliability-adjusted belief is approximately Low 98.0%, High 0%, Unknown 2.0%.

## 13.2 Pip & Nut — Quick Ratio

If a reliably extracted Quick Ratio produces provisional risk belief Low = 0.16 and High = 0.84, and the final evidence reliability is r = 0.95, the final belief becomes Low = 0.152, High = 0.798, Unknown = 0.050.

## 13.3 Incomplete Debt Disclosure

If total interest-bearing debt cannot be established because required components are incomplete, the MVP does not treat known partial debt as total debt. The Debt Burden metric is marked unavailable and produces Low = 0, High = 0, Unknown = 1.

# 14. Historical Data Policy for MVP

Financial ingestion should retain the latest three comparable reporting periods where available. The latest complete reporting period is the primary current-risk state. Earlier periods support F1.2 Net Asset Trend, basic temporal sanity checks and dashboard explanation. Historical Current Ratio, Quick Ratio and Debt Burden values are not independently re-weighted into ER in this scheme, avoiding double counting.

Governance variables continue to use their defined event windows, such as 24 months for director turnover, 90 days for director-change concentration and 36 months for PSC/control changes.

# 15. Minimum Status Codes

A missing numeric value must carry a reason code rather than being represented only as NULL. Minimum MVP codes: AVAILABLE, NOT_DISCLOSED, NOT_APPLICABLE, RETRIEVAL_FAILED, EXTRACTION_FAILED, VALIDATION_FAILED, CONFLICT_UNRESOLVED, NON_COMPARABLE.

# 16. Implementation Boundary

For the MVP, document classification, deterministic extraction where possible, validation checks, conflict handling, reliability calculation and ER discounting should be implemented in code. LLMs may assist with semantic extraction and narrative interpretation, but should not directly assign final reliability or risk beliefs.

Aggregation dependency. All parent-node aggregation, missing-child handling and ER stress-test invariants are defined in ER Aggregation Specification v1. This reliability document governs evidence quality only.

# 17. Version Status and Future Work

Status: FROZEN FOR MVP IMPLEMENTATION — Evidence Reliability Scheme v1

The architecture and initial heuristic parameters above are sufficient for the first working prototype. They are not empirically calibrated accuracy probabilities. A later version may introduce dynamic OCR quality, fact-level validation strength, explicit metric-validity scoring, taxonomy mapping confidence, larger stratified company samples and human gold-standard calibration. Those enhancements should refine rather than replace the current Source → Extraction → Validation → Conflict → Reliability → Unknown architecture.



| Symbol | Component | Question |

| --- | --- | --- |

| S | Source Quality | How authoritative and traceable is the original source? |

| E | Extraction Quality | How reliably was the fact extracted from that source? |

| V | Validation Strength | How much additional checking supports the extracted fact? |

| C | Conflict Penalty | Is there a material unresolved conflict in the evidence? |





| Source Type | S | MVP Rationale |

| --- | --- | --- |

| Companies House structured API | 0.98 | Official structured statutory-register data |

| Companies House filed iXBRL | 0.97 | Official structured filed accounts |

| Companies House filed PDF | 0.95 | Official filing; extraction may be less structured |

| Official company website/document | 0.85 | First-party but generally non-statutory |





| Extraction Method | E |

| --- | --- |

| Direct API field | 0.99 |

| Direct iXBRL tag | 0.98 |

| Deterministic native-PDF extraction | 0.95 |

| High-quality OCR + deterministic extraction | 0.85 |

| Native text + LLM structured extraction | 0.85 |

| OCR + LLM structured extraction | 0.75 |

| Unsupported LLM-generated/inferred value | 0.00 |





| Validation Level | V | Meaning |

| --- | --- | --- |

| No additional validation | 0.00 | The fact is supported only by its source and extraction path. |

| One meaningful validation passed | 0.30 | Example: arithmetic identity passes or a matching representation agrees. |

| Strong / multiple validation passed | 0.60 | Example: arithmetic validation plus PDF/iXBRL agreement or other strong corroboration. |





| Conflict Level | C | Treatment |

| --- | --- | --- |

| No material conflict | 0.00 | Normal processing |

| Material but partially reconcilable conflict | 0.30 | Reliability is discounted while preserving some evidence |

| Serious unresolved conflict | 1.00 | The metric is not trusted for risk scoring; Unknown = 100% |





| Condition | MVP Treatment |

| --- | --- |

| Required core component missing | r = 0; Unknown = 100% |

| Serious unresolved evidence conflict | r = 0; Unknown = 100% |

| LLM value has no traceable supporting evidence | r = 0; value must not enter the core risk model |

| Reporting periods clearly non-comparable for a trend-dependent metric | r = 0 for that derived metric; Unknown = 100% |

| Retrieval failure | Do not treat as data not disclosed; record RETRIEVAL_FAILED and retry/fallback |

| Data genuinely not disclosed | Record NOT_DISCLOSED; do not substitute zero |
