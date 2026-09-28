# Risk Model Specification v1

Evidence-Grounded AI Risk Intelligence
MVP Core Model — Frozen Candidate Specification
26 September 2026

# 1. Scope and Assessment Frame

This document freezes the current MVP v1 design: 11 core variables, reference levels, belief-transformation formulas and provisional importance weights. Evidence reliability is governed separately by Evidence Reliability Scheme v1 (`docs/design-docs/evidence-reliability-v1.md`); hierarchical aggregation is governed by ER Aggregation Specification v1 (`docs/design-docs/er-aggregation-v1.md`).

Assessment frame: Θ = {Low Risk, High Risk, Unknown}. Low/High are evidential reference states, not probabilities of company failure. Unknown means incomplete or insufficiently reliable evidence, not medium risk.

# 2. Hierarchy and Weights

Overall Company Risk

Governance Risk — 0.40

G1 Filing & Regulatory Compliance — 0.30 within Governance

G1.1 Accounts Filing Lateness

G1.2 Confirmation Statement Lateness

G2 Management Stability — 0.45 within Governance

G2.1 Director Turnover — 24 Months

G2.2 Median Tenure of Active Directors

G2.3 Director Change Concentration — 90 Days

G3 Ownership & Control Stability — 0.25 within Governance

G3.1 PSC / Control Change Frequency — 36 Months

Financial Risk — 0.60

F1 Balance-Sheet Strength — 0.35 within Financial

F1.1 Net Asset Position — Equity / Total Assets

F1.2 Net Asset Trend

F2 Liquidity Position — 0.40 within Financial

F2.2 Current Ratio

F2.3 Quick Ratio

F3 Debt & Financing Exposure — 0.25 within Financial

F3.1 Interest-Bearing Debt / Total Assets

# 3. General Belief Transformation

Higher-is-riskier variable: βH=0 for x≤L; βH=(x−L)/(H−L) for L<x<H; βH=1 for x≥H. For complete evidence, βL=1−βH.

Lower-is-riskier variable: βH=1 for x≤H; βH=(L−x)/(L−H) for H<x<L; βH=0 for x≥L. For complete evidence, βL=1−βH.

MVP v1 Unknown rule: if required evidence is unavailable or cannot be reconciled, βU=1 and βL=βH=0; otherwise βU=0. Partial Unknown is governed by the existing Evidence Reliability Scheme v1, applied after the provisional risk transformation.

# 4. Frozen Variable Specification

# 5. Threshold Basis

- G1.1: statutory/regulatory anchor; late accounts penalties escalate with lateness.

- G1.2: statutory filing deadline; 30-day High boundary is an MVP heuristic.

- G2.1, G2.2, G2.3 and G3.1: risk direction is conceptually defensible, but numerical boundaries are explicitly MVP heuristics.

- F1.1: non-positive net assets provide a strong High-risk anchor; the 10% Low boundary is an MVP heuristic.

- F1.2: −20% High boundary is an MVP heuristic.

- F2.2: 1.1 is an externally supported UK corporate-vulnerability anchor; 1.5 Low boundary is an MVP assumption.

- F2.3: conventional finance reference levels, used here as MVP heuristics and potentially industry-sensitive.

- F3.1: higher interest-bearing leverage is a defensible risk direction; 20%/60% boundaries are MVP heuristics.

# 6. Weighting Summary

Domain weights: Governance = 0.40; Financial = 0.60. These are provisional expert-judgement importance weights, not empirically calibrated probabilities.

Governance indicator weights: G1 = 0.30; G2 = 0.45; G3 = 0.25. Financial indicator weights: F1 = 0.35; F2 = 0.40; F3 = 0.25.

Overall effective variable weight = Domain Weight × Indicator Weight × Variable Weight. The 11 effective weights sum to 100.00%.

# 7. Data-Source Policy

Governance variables are primarily sourced from Companies House structured register/API data: Company Profile, Filing History, Officers and PSC. Financial variables are primarily sourced from iXBRL where available, with filed accounts PDF used as fallback, narrative source and cross-validation evidence. A source must never be treated as supplying a field it does not actually contain.

# 8. Explicitly Removed Variables

G1.3 Repeated Filing Irregularity: Removed to avoid double-counting late-filing evidence represented by G1.1/G1.2.

F2.1 Working-Capital Position: Removed because WC/Current Assets = 1 − 1/Current Ratio, making it mathematically dependent on F2.2.

F1.3 Liabilities / Assets: Removed because it is the mathematical complement of Equity / Assets under the balance-sheet identity.

F3.2 Secured Financing Exposure: Removed from Core v1 because charge/security signals are strongly industry- and context-dependent.

# 9. Not Yet Frozen

Evidence reliability and partial-Unknown transformation are governed by the existing Evidence Reliability Scheme v1. Hierarchical ER aggregation is governed by the existing ER Aggregation Specification v1; outstanding specification gaps are recorded in `docs/implementation/M6-hierarchical-er-aggregation-engine.md` and must not be filled by assumption. Empirical calibration, industry adjustments, sensitivity analysis and validation against observed outcomes remain future work.

# 10. Version Status

FROZEN CANDIDATE — Risk Model Specification v1

The 11-variable set, reference levels, transformation logic and provisional importance weights are frozen for the next development stage. Future changes should be versioned and justified.



| ID | Variable | Primary source | Low reference | High reference | Transformation / definition | Variable weight | Effective weight |

| --- | --- | --- | --- | --- | --- | --- | --- |

| G1.1 | Accounts Filing Lateness | CH Profile + Filing History API | 0 days | ≥90 days | Days late; higher is riskier; linear 0–90 days | 0.60 within G1 | 7.20% |

| G1.2 | Confirmation Statement Lateness | CH Profile + Filing History API | 0 days | ≥30 days | Days late; higher is riskier; linear 0–30 days | 0.40 within G1 | 4.80% |

| G2.1 | Director Turnover — 24 Months | Officers API + Filing History | 0% | ≥50% | Departures over 24m / relevant director population; higher is riskier | 0.40 within G2 | 7.20% |

| G2.2 | Median Tenure of Active Directors | Officers API | ≥5 years | ≤1 year | Median active-director tenure; lower is riskier; linear 1–5 years | 0.25 within G2 | 4.50% |

| G2.3 | Director Change Concentration — 90 Days | Officers API + Filing History | 0% | ≥50% | Max departures / pre-window directors in any rolling 90-day window | 0.35 within G2 | 6.30% |

| G3.1 | PSC / Control Change Frequency — 36 Months | PSC API + Filing History | 0 | ≥2 | Substantive changes only: 0→Low; 1→50/50; ≥2→High | 1.00 within G3 | 10.00% |

| F1.1 | Net Asset Position — Equity / Total Assets | iXBRL; PDF fallback | ≥10% | ≤0% | Net Assets / Total Assets; lower is riskier; linear 0–10% | 0.65 within F1 | 13.65% |

| F1.2 | Net Asset Trend | iXBRL; PDF fallback | ≥0% | ≤−20% | (NA_t−NA_t−1)/|NA_t−1|; lower is riskier; special handling near zero | 0.35 within F1 | 7.35% |

| F2.2 | Current Ratio | iXBRL; PDF fallback | ≥1.5 | ≤1.1 | Current Assets / Current Liabilities; lower is riskier | 0.60 within F2 | 14.40% |

| F2.3 | Quick Ratio | iXBRL; PDF fallback | ≥1.0 | ≤0.7 | (Current Assets−Inventory)/Current Liabilities; lower is riskier | 0.40 within F2 | 9.60% |

| F3.1 | Interest-Bearing Debt / Total Assets | iXBRL + Accounts Notes/PDF | ≤20% | ≥60% | Interest-bearing debt / Total Assets; higher is riskier | 1.00 within F3 | 15.00% |
