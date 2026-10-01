# Risk Model Specification v1.1 — Single-Period Extensible MVP

Status: **FROZEN FOR MVP v1.1 IMPLEMENTATION**
Date: 30 September 2026
Supersedes `risk-model-v1.md` for new MVP assessments only. Historical v1 remains immutable.

## 1. Product decision

MVP v1.1 deliberately minimizes temporal reconstruction. A user selects a company and one financial reporting year. Financial risk uses only facts belonging to that selected reporting year; it must not silently fall back to another year. Governance retains only variables that can be assessed from current/selected-as-of structured state without a dedicated multi-period trend or historical event-window metric.

The objective is to prove the complete evidence-grounded chain — evidence → validation → reliability → Low/High/Unknown → ER aggregation → explanation — with a small model that is easy to extend later.

## 2. Active leaf variables

| Domain | UI/explanation group | Variable | Definition | Low | High |
| --- | --- | --- | --- | --- | --- |
| Governance | Filing Compliance | G1.1 Accounts Filing Lateness | days late | 0 | >=90 |
| Governance | Filing Compliance | G1.2 Confirmation Statement Lateness | days late | 0 | >=30 |
| Governance | Management Stability | G2.2 Median Tenure of Active Directors | median years | >=5 | <=1 |
| Financial | Balance-Sheet Strength | F1.1 Net Asset Position | NET_ASSETS / TOTAL_ASSETS | >=0.10 | <=0 |
| Financial | Liquidity | F2.2 Current Ratio | CURRENT_ASSETS / CURRENT_LIABILITIES | >=1.50 | <=1.10 |
| Financial | Liquidity | F2.3 Quick Ratio | (CURRENT_ASSETS - INVENTORY) / CURRENT_LIABILITIES | >=1.00 | <=0.70 |
| Financial | Debt Exposure | F3.1 Interest-Bearing Debt / Total Assets | INTEREST_BEARING_DEBT / TOTAL_ASSETS | <=0.20 | >=0.60 |

The reference transformations and M4 reliability-to-Unknown treatment are unchanged from v1.

## 3. Deferred variables

The following implemented/historical variables are **not active in MVP v1.1**:

- G2.1 Director Turnover — 24 Months
- G2.3 Director Change Concentration — rolling 90-day windows over 24 months
- G3.1 PSC / Control Change Frequency — 36 Months
- F1.2 Net Asset Trend — cross-period comparison

They are deferred because they require explicit historical event-window or cross-period reasoning. Their historical code/specification may remain for future versioned reactivation; they must not be emitted as v1.1 leaves and their weights must not be redistributed at runtime.

## 4. Single reporting-year contract

Every v1.1 assessment persists an explicit `reporting_year` independently from `assessment_date`.

For F1.1/F2.2/F2.3/F3.1:

- all mandatory financial facts must belong to the selected reporting year;
- company, analytical scope, period shape, currency, unit and M4 usability must remain compatible;
- no automatic fallback to an earlier/later reporting year is allowed;
- if mandatory selected-year evidence is unavailable, the leaf remains present as `(Low, High, Unknown)=(0,0,1)` with its typed cause.

`assessment_date` remains the as-of boundary for evidence availability and governance state. It must not be used to infer the selected reporting year.

## 5. Weighting policy

Only domain importance is frozen in MVP v1.1:

- Governance = 0.40
- Financial = 0.60

Within each domain, all **active** variables are equally important. The policy identifier is:

`EQUAL_WEIGHT_ACTIVE_VARIABLES`

Therefore v1.1 uses 1/3 for each Governance leaf and 1/4 for each Financial leaf when performing domain ER aggregation. These fractions are consequences of the policy and active registry, not individually calibrated variable weights.

The UI grouping labels G1/G2/F1/F2/F3 are explanatory only in v1.1; they do not introduce an intermediate mathematical weighting layer.

The equal-weight policy is an MVP assumption, not an empirical claim. Future model versions may learn/calibrate variable or group weights from outcome data without rewriting historical assessments.

## 6. Extensibility requirement

The active variable set, domain membership and weighting policy must be model-version registry/configuration, not hard-coded assumptions that exactly seven variables exist.

Adding/reactivating a future variable should require, at most:

1. a versioned variable definition and domain registration;
2. its calculator/dependency resolver;
3. tests and documentation;
4. a new model version when the active set or weighting policy changes.

Persistence remains row-based (`assessment_id`, `variable_code`, result), so the schema must not create one column per variable. M5 iterates the active model registry. M6 consumes the active registry and must not assume fixed leaf counts. UI renders the persisted active results dynamically.

## 7. Version boundary

`risk-model-v1` remains the historical 11-variable model. `risk-model-v1.1` is the active seven-variable single-period MVP. Do not rewrite old v1 results into v1.1.
