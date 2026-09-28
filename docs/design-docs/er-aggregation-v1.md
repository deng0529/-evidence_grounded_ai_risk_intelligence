# ER Aggregation Specification v1

Evidence-Grounded AI Risk Intelligence
Hierarchical Evidential Reasoning for MVP
26 September 2026

Purpose. This specification freezes the MVP aggregation method that converts variable-level risk beliefs into indicator-, domain-, and overall company-risk belief distributions. It is designed to preserve evidence incompleteness explicitly and to keep risk importance separate from evidence reliability.

# 1. Decision

The MVP SHALL use hierarchical evidential reasoning rather than a single flat aggregation of all 11 variables. The hierarchy is Variable → Indicator → Domain → Overall Company Risk.

Evidence reliability is applied before aggregation as explicit uncertainty discounting. The MVP does NOT directly identify its Evidence Reliability r with the reliability parameter of the 2013 ER Rule/WBDR formulation.

# 2. Frozen Risk Hierarchy

# 3. Variable-Level Belief Construction

Each leaf variable first receives a deterministic provisional risk belief from its value and Low/High reference levels: (β̂L, β̂H), where β̂L + β̂H = 1 when the metric is computable.

Evidence Reliability r is calculated by Evidence Reliability Scheme v1. The reliability-adjusted variable belief is:

βL = r × β̂L

βH = r × β̂H

βU = 1 − r

Unknown represents evidence incompleteness/uncertainty. It is not Medium risk. A fail-safe condition with r = 0 therefore produces (Low, High, Unknown) = (0, 0, 1).

# 4. Aggregation Principle

At each parent node, child belief distributions are combined using their local importance weights. Importance weight is not evidence reliability. Weight-induced unassigned mass must not be presented to users as evidence Unknown. The implementation shall follow the analytical/recursive ER treatment of incomplete belief assessments rather than a naïve Dempster discount that equates 1 − weight with Unknown.

A single-child parent is an identity operation: G3 = G3.1 and F3 = F3.1. No artificial aggregation or additional uncertainty is introduced.

## 4.1 Analytical ER aggregation formula

For a parent node with L child inputs and N explicit evaluation grades,
i runs from 1 to L and n runs from 1 to N. Let w_i be the frozen local
importance weight and beta_(n,i) the final child belief in explicit grade n.
At the leaf-to-indicator boundary these are the final M5 beliefs; higher
levels consume the full-precision child aggregation results.

```text
s_i = sum_n beta_(n,i)
A_n = product_i [w_i beta_(n,i) + 1 - w_i s_i]
B = product_i (1 - w_i s_i)
mu = 1 / [sum_n A_n - (N - 1)B]
C = product_i (1 - w_i)
beta_n = mu(A_n - B) / (1 - mu C)
beta_U = 1 - sum_n beta_n
```

Here `sum_n` and `product_i` denote summation over grades and multiplication
over child inputs respectively; mu denotes the normalization factor.
For the MVP, N = 2, with explicit grades Low and High. Unknown is the
remaining evidence-incompleteness mass, not a third explicit grade in this
formula. The formula-local C is the importance-weight product above, not
the conflict penalty C in Evidence Reliability Scheme v1.

The normalization removes importance-weight unassigned mass from the final
belief assessment. Do not report that intermediate weight-generated mass
as direct evidence Unknown. Evidence reliability has already been applied
by M5 and must not be applied again here. The frozen single-child identity
rules, including G3 = G3.1 and F3 = F3.1, remain in force.

# 5. Hierarchical Aggregation Sequence

G1 = ER(G1.1, G1.2)

G2 = ER(G2.1, G2.2, G2.3)

G3 = G3.1

Governance = ER(G1, G2, G3)

F1 = ER(F1.1, F1.2)

F2 = ER(F2.2, F2.3)

F3 = F3.1

Financial = ER(F1, F2, F3)

Overall = ER(Governance, Financial)

# 6. Missing and Non-Comparable Data

- Missing required evidence is represented as (0, 0, 1); its importance weight is NOT redistributed to known siblings.

- If an entire indicator is unknown, the indicator result must be (0, 0, 1).

- NON_COMPARABLE time-dependent metrics (for example, F1.2 across unsuitable periods) are treated as Unknown for that metric.

- RETRIEVAL_FAILED is operationally distinct from NOT_DISCLOSED, although either may prevent a metric from being scored until resolved.

- If every child of a node is Unknown, the parent must be Unknown 100%.

# 7. Conflict / Disagreement

Aggregation should retain a diagnostic conflict/disagreement measure where available. This is separate from the evidence-source conflict penalty C used by the Reliability Scheme. The former describes disagreement between risk attributes; the latter describes conflicting evidence about a fact.

The UI may expose high aggregation disagreement as an explanation aid, but it must not silently modify source reliability or the frozen importance weights.

# 8. Why Hierarchical Rather Than Flat ER

- The risk ontology has meaningful intermediate constructs: Filing Compliance, Management Stability, Liquidity, Governance and Financial Risk.

- Hierarchical aggregation preserves an auditable explanation path: Overall → Domain → Indicator → Variable → Fact → Evidence.

- Related attributes such as Current Ratio and Quick Ratio are contained within a local construct rather than mixed directly with unrelated governance attributes.

- Flat and hierarchical ER are not generally equivalent because ER combination is nonlinear; the chosen hierarchy is therefore part of the model specification, not merely a UI grouping.

# 9. Independence / Dependence Limitation

The MVP treats the 11 measures as distinct risk attributes but does not claim that they are statistically independent. Some share underlying information (for example Current Ratio and Quick Ratio; director turnover and director-change concentration). Dependence analysis and empirical calibration are future validation work. This limitation must be stated in methodology documentation.

# 10. Stress-Test Acceptance Results

## 10.1 Frozen mixed-belief hierarchical regression reference

The approved final Overall distribution is:

```text
Low     = 0.26649306
High    = 0.68917167
Unknown = 0.04433527
```

These expected outputs are frozen for implementation testing, subject to
section 12.1. No complete associated input fixture was found in the active
authoritative Markdown documentation. The exact child/leaf input beliefs
and associated fixture context still require human review before this
specific regression test can be implemented or declared reproducible.
Do not infer or reverse-engineer fixture inputs from these expected outputs.
The existing stress-test and reliability-sweep tables are preserved and
are not substitutes for the missing mixed-case fixture.

# 11. Reliability Monotonicity Example

These values are stress-test outputs for the artificial all-High scenario and are acceptance examples, not empirical company-risk probabilities.

# 12. Required Software Invariants / Unit Tests

- Every belief distribution is bounded in [0,1] and sums to 1 within numerical tolerance.

- All-High reliable inputs produce all-High output; all-Low reliable inputs produce all-Low output.

- All-Unknown children produce all-Unknown parent.

- Single-child parent returns the child unchanged.

- Missing child weights are not redistributed.

- Reducing evidence reliability for otherwise identical inputs must not reduce Unknown in the defined monotonicity test.

- Repeated aggregation must not reinterpret importance residual as evidence Unknown.

- Results must be reproducible for identical inputs, weights and model version.

## 12.1 Numerical tolerance and computational precision

The approved absolute tolerance for ER numerical comparisons is 1e-8.
Regression/unit tests must compare each belief component using:

```text
abs(actual - expected) <= 1e-8
```

This absolute criterion applies unless a test explicitly requires exact
symbolic/logical equality. A relative-tolerance allowance must not relax
this criterion.

Internal calculations and stored authoritative computational results must
preserve full practical numerical precision. Do not prematurely round leaf,
indicator, domain or Overall beliefs, including before subsequent aggregation.
The test tolerance is an acceptance bound, not an instruction to round or
quantize stored or intermediate values.

Human-facing Low / High / Unknown values normally display two decimal
places. Percentage rendering multiplies the full-precision belief by 100
for display only: 0.26649306 / 0.68917167 / 0.04433527 displays as
26.65% / 68.92% / 4.43%. Unknown must remain visible.

UI formatting is presentation-only. Rounded UI values must never feed back
into variable calculations, reliability calculations, ER aggregation,
validation or stored authoritative computational results. Detailed UI
presentation remains governed by `docs/product-specs/ui-spec-v1.md`.

# 13. Model Versioning and Auditability

Every stored assessment must record risk_model_version, reliability_model_version and er_aggregation_version. Variable, indicator, domain and overall results should be persisted so the UI can reproduce the exact calculation path used at the time of assessment.

# 14. Relationship to Existing Specifications

Risk Model Specification v1 remains authoritative for hierarchy, variables, thresholds and importance weights. Evidence Reliability Scheme v1 remains authoritative for S/E/V/C and r and specifies that r is converted into variable-level Unknown before ER aggregation and is not the 2013 ER Rule reliability parameter. The phrase 'ER aggregation' in earlier documents should refer to the hierarchical method defined here.

# 15. Status

Status: FROZEN FOR MVP IMPLEMENTATION — ER Aggregation Specification v1

Future research may compare the MVP approach with the full reliability-aware ER Rule/WBDR formulation, alternative dependence-aware evidence combination, or empirically calibrated aggregation. Such work should be versioned rather than silently changing historical assessments.



| Domain | Indicator | Child Variables |

| --- | --- | --- |

| Governance (0.40) | G1 Filing & Regulatory Compliance (0.30) | G1.1 Accounts Filing Lateness (0.60); G1.2 Confirmation Statement Lateness (0.40) |

| Governance (0.40) | G2 Management Stability (0.45) | G2.1 Director Turnover 24m (0.40); G2.2 Median Active-Director Tenure (0.25); G2.3 Director Change Concentration 90d (0.35) |

| Governance (0.40) | G3 Ownership & Control Stability (0.25) | G3.1 PSC / Control Change Frequency 36m (1.00) |

| Financial (0.60) | F1 Balance-Sheet Strength (0.35) | F1.1 Equity / Total Assets (0.65); F1.2 Net Asset Trend (0.35) |

| Financial (0.60) | F2 Liquidity Position (0.40) | F2.2 Current Ratio (0.60); F2.3 Quick Ratio (0.40) |

| Financial (0.60) | F3 Debt & Financing Exposure (0.25) | F3.1 Interest-Bearing Debt / Total Assets (1.00) |





| Stress Test | Required/Observed Behaviour | Status |

| --- | --- | --- |

| All leaf variables High=100%, r=1 | Overall High=100% | PASS |

| All leaf variables Low=100%, r=1 | Overall Low=100% | PASS |

| Governance fully Low vs Financial fully High | Conflict retained; with 0.40/0.60 top weights illustrative result ≈ Low 30.8%, High 69.2% | PASS |

| One leaf variable completely missing | Local Unknown increases; missing weight is not redistributed | PASS |

| Entire F2 Liquidity indicator missing | F2 Unknown=100%; Financial retains material Unknown | PASS |

| Common reliability decreases 1.0→0.8→0.5→0.2→0 | Overall Unknown increases monotonically; r=0 yields Unknown=100% | PASS |





| Common Evidence Reliability | Overall High | Overall Unknown |

| --- | --- | --- |

| 1.00 | 100.0% | 0.0% |

| 0.80 | 92.1% | 7.9% |

| 0.50 | 72.8% | 27.2% |

| 0.20 | 38.1% | 61.9% |

| 0.00 | 0.0% | 100.0% |
