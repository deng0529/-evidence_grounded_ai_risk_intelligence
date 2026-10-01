# UI Specification v1

> **MVP v1.2 amendment (1 Oct 2026):** For new assessments, `risk-model-v1.2.md` supersedes the older 11-variable UI/architecture references below. The active MVP has six leaves, an explicit selected financial reporting year, no cross-period trend/event-window leaves, Governance/Financial weights 0.40/0.60, and equal active-variable weighting within each domain. Older sections are retained as historical v1 context.


Status: FROZEN FOR MVP IMPLEMENTATION


---

## Step 1

# UI Specification - Step 1 v1

Evidence-Grounded AI Risk Intelligence
Public Entry, Company Search and Analysis Launch

Status: FROZEN FOR MVP DESIGN. Step 1 defines the simplest public entry flow for an independent user opening the deployed MVP without assistance. The interface is intentionally minimal, while the backend architecture must preserve room for later expansion.

# 1. Step 1 Objective

Allow a user to open a public web link, identify a UK company, launch an analysis, and reach the Overview page with the fewest possible interactions.

Frozen user journey:

Search  ->  Select  ->  Analyse  ->  Overview

# 2. Home / Search Page

The first screen should not expose ER mathematics, reliability formulas, data pipelines, or implementation details. It should communicate the product purpose and provide one obvious action.

- Product title: Evidence-Grounded AI Risk Intelligence

- Short subtitle: Evidence-traceable company risk assessment

- One search field accepting company name or Companies House number

- One Search button

- Optional demo-company shortcuts: Pip & Nut, LODI UK, Westpoint Homes

Conceptual layout:

Evidence-Grounded AI Risk Intelligence

Evidence-traceable company risk assessment

[ Company name or company number                  ] [ Search ]

Try a demo:  [ Pip & Nut ]  [ LODI UK ]  [ Westpoint Homes ]

# 3. Search Results

Company resolution must be deterministic. Search results should use Companies House identity data and allow the user to select the intended legal entity. An LLM must not decide which legal entity the user meant.

Each result needs only:

- Company name

- Company number

- Company status

- Analyse button

# 4. Analyse Action

After the user selects Analyse, the MVP should show a simple controlled loading state rather than exposing the full internal pipeline.

Analysing <Company Name>...
Retrieving and validating public evidence.
This may take a moment.

Internally, the application may check for a valid cached assessment before running live ingestion. This cache decision is an implementation detail and does not need to complicate the Step 1 user interface.

# 5. Controlled-Response Principle

Every user interaction must produce a controlled response. No dead clicks, unhandled exceptions, broken navigation, or raw backend error messages may be exposed to the user.

# 6. Standard UI States

Components should be designed around a small common state model so later pages can reuse the same behaviour.

READY / LOADING / SUCCESS / PARTIAL / EMPTY / INVALID_INPUT / ERROR / NOT_IMPLEMENTED

These states are UI/application states. They do not replace the evidence availability/status codes defined in the Evidence Reliability specification.

# 7. Examples of Safe Responses

# 8. Extensibility Requirements

The Step 1 interface remains simple, but implementation should leave clear extension points for future features without redesigning the entry flow.

- Cached vs live assessment handling

- Last analysed / data-current timestamps

- Refresh analysis

- Detailed processing-stage progress

- Company comparison

- Assessment history and versioning

- More advanced search filters

Future features should be added progressively. The MVP should not display many inactive controls merely to advertise future work.

# 9. Backend Support Required by Step 1

- Company resolution by Companies House company number

- Processing-run status and controlled error handling

- Ability to distinguish successful, partial and failed assessments

- Persistent assessment/cache lookup

- No unhandled exception propagated to the public UI

# 10. Acceptance Criteria

- A new user can reach an assessment from the public landing page through Search -> Select -> Analyse -> Overview.

- Every visible interactive control has a defined response.

- No empty click or broken navigation is permitted.

- Invalid input and no-result searches are handled without application failure.

- Unimplemented visible features return a controlled development/coming-soon message.

- Backend/API/database errors are converted to user-friendly states.

- A processing failure cannot be presented as a valid risk assessment.

- Partial evidence is distinguishable from processing failure.

- The UI remains minimal while the implementation preserves extension points.

# 11. Frozen Step 1 Flow

PUBLIC LINK
   |
   v
SEARCH COMPANY
   |
   v
SELECT LEGAL ENTITY
   |
   v
ANALYSE
   |
   v
OVERVIEW

Every interaction -> Controlled Response

Next UI design stage: Step 2 - Overview Dashboard. Step 2 should follow the same principles: minimal first view, clear drill-down, controlled interaction states, and easy future expansion.



| Situation | Required UI Behaviour |

| --- | --- |

| Implemented action | Execute normally and show progress/result. |

| Feature not implemented | Show a concise 'This feature is under development' or 'Coming soon' response. |

| Empty/invalid input | Explain what the user should enter or correct. |

| No company match | State that no matching UK company was found and allow another search. |

| Temporary API/database failure | Show a friendly error and a Try Again action where appropriate. |

| Partial but valid evidence | Continue with a Partial Assessment and reflect incompleteness as Unknown. |

| Processing failure that invalidates assessment | Do not generate a normal-looking risk result; report that analysis could not be completed. |





| Trigger | Example Response |

| --- | --- |

| Search pressed with no input | Please enter a company name or Companies House number. |

| No result | No matching UK companies were found. Please check the name or company number and try again. |

| Future comparison button | Coming soon - company comparison is planned for a future release. |

| Analysis system failure | We couldn't complete this analysis. No risk result has been generated from incomplete processing. |

| Partial evidence | Partial assessment - some required evidence was unavailable. Uncertainty is reflected in the risk assessment. |



---

## Step 2 — Overview Dashboard

# UI Specification - Step 2 v1

Evidence-Grounded AI Risk Intelligence
Overview Dashboard

Status: FROZEN FOR MVP DESIGN, subject to final implementation choice for Key Risk Driver ranking. The Overview is intentionally concise and should answer four questions: What is the overall assessment? Which domain drives it? What are the main risk drivers? How much uncertainty remains?

# 1. Design Principles

- Minimal first view: do not expose detailed methodology or raw evidence unless the user drills down.

- Faithfully display Low / High / Unknown belief rather than converting the model into a conventional 0–100 risk score.

- Unknown must remain visible because explicit uncertainty is a core feature of the product.

- Every interactive element must return a controlled response, following UI Specification Step 1 v1.

- Keep the layout simple while preserving clear extension points for future features.

# 2. Overview Structure

1. COMPANY HEADER
        ↓
2. OVERALL RISK
        ↓
3. GOVERNANCE RISK  |  FINANCIAL RISK
        ↓
4. KEY RISK DRIVERS

# 3. Company Header

The header should show only essential company and assessment identity:

- Legal company name

- Companies House company number

- Current company status

- Assessment date

- New Search action

Use 'Assessment date' rather than a single 'Data date', because different evidence sources and financial reporting periods may have different dates. Source-specific dates belong in the Evidence view.

A Refresh action may be added later. It should not be shown merely as an inactive control unless there is a clear roadmap reason; if shown before implementation it must return a controlled under-development response.

# 4. Overall Risk

The primary result is a belief distribution over Low, High and Unknown. The Overview should not convert this into a generic risk score such as 72/100.

LOW  27%      HIGH  69%      UNKNOWN  4%

A simple horizontal belief bar may accompany the percentages. Avoid presenting 'High 69%' as a probability that the company will fail. An information control should explain that belief degrees are the model's evidence-based assessment, not probabilities of company failure.

# 5. Domain Cards

The Overview displays only the two top-level domains. Indicator-level detail (G1/G2/G3 and F1/F2/F3) belongs in the Risk Detail page.

# 6. Key Risk Drivers

Display no more than three principal risk drivers. Each driver should show the variable name, observed/derived value, High-risk belief, evidence reliability, and a direct Evidence action.

Example:

Current Ratio                    1.05

High belief 90%  •  Reliability 96%      [View evidence]

Equity / Total Assets            8.3%

High belief 58%  •  Reliability 97%      [View evidence]

# 7. Driver Ranking Method

Driver selection must be deterministic; an LLM must not decide which variables are the principal risk drivers.

Simple MVP candidate: DriverImportance_i = EffectiveWeight_i × HighBelief_i. This is easy to audit, but because ER aggregation is nonlinear it must be described as a ranking heuristic rather than the exact contribution of a variable to Overall High belief.

Preferred explainability extension: leave-one-out ER sensitivity. Recalculate the overall assessment after neutralising/removing each variable under a precisely specified missing/neutral policy and measure the change in the final result. This can provide a stronger model-impact explanation, but its exact definition must be validated before implementation. Until then, the simple deterministic heuristic is acceptable for MVP display.

# 8. Unknown / Partial Assessment

Unknown is a first-class output and must never be hidden. When material uncertainty is present, the Overview should show a concise notice such as:

Partial assessment — some required evidence was unavailable.
Uncertainty is reflected in the risk assessment.

A View uncertainty action may lead to Risk Detail or Evidence Explorer. Detailed availability codes such as NOT_DISCLOSED, EXTRACTION_FAILED or NON_COMPARABLE need not clutter the Overview.

# 9. Information Deliberately Excluded from Overview v1

- S / E / V / C reliability components

- ER equations and threshold tables

- All 11 variables at once

- PDF page numbers and iXBRL tags

- Extraction method and detailed validation diagnostics

- Historical charts

- Long AI-generated explanations

- Raw Companies House API data

These belong in later drill-down pages, especially Risk Detail, Evidence, History and Methodology.

# 10. Interaction Behaviour

# 11. Conceptual MVP Layout

PIP & NUT LTD
08624397 • Active
Assessment: 27 Sep 2026                         [New Search]

OVERALL RISK
------------------------------------------------------------
Low 27%                 High 69%              Unknown 4%
[ belief distribution bar ]

GOVERNANCE                              FINANCIAL
Low      53%                            Low      16%
High     40%                            High     79%
Unknown   7%                            Unknown   5%
[View details]                          [View details]

KEY RISK DRIVERS
------------------------------------------------------------
Current Ratio                    1.05
High belief 90% • Reliability 96%               [Evidence]

Equity / Total Assets            8.3%
High belief 58% • Reliability 97%               [Evidence]

Director Change Concentration    42%
High belief 68% • Reliability 98%               [Evidence]

# 12. Extensibility

- Refresh/re-analysis control and assessment version history

- Interactive uncertainty drill-down

- More rigorous ER sensitivity-based driver attribution

- Additional risk domains in later model versions

- Company comparison

- Exportable assessment report

- Richer visualisations without changing the core page hierarchy

# 13. Acceptance Criteria

- The user can understand the overall Low/High/Unknown assessment without reading methodology documentation.

- Governance and Financial beliefs are visible separately.

- No more than three key risk drivers are shown in the primary Overview.

- Unknown is visible and material uncertainty triggers a clear Partial Assessment message.

- Belief values are not described as probabilities of company failure.

- Driver ranking is deterministic and auditable, not selected by an LLM.

- Every visible interactive control has defined behaviour.

- No raw exception or broken navigation is exposed.

- Detailed evidence/methodology remains accessible through drill-down rather than cluttering the first view.

# 14. Relationship to Other Specifications

Step 1 governs public entry, search, selection and controlled-response behaviour. Risk Model Specification v1 defines the hierarchy, variables, thresholds and weights. Evidence Reliability Scheme v1 defines evidence quality and leaf-level uncertainty. ER Aggregation Specification v1 defines hierarchical aggregation. Step 2 renders those outputs; it does not independently calculate or modify them.



| Domain Card | Displayed Result | Action |

| --- | --- | --- |

| Governance | Low / High / Unknown belief | View details → Governance section in Risk Detail |

| Financial | Low / High / Unknown belief | View details → Financial section in Risk Detail |





| Interaction | Required Response |

| --- | --- |

| New Search | Return to the company search/home flow. |

| View details | Open the appropriate section of Risk Detail. |

| View evidence | Open the evidence chain for that variable. |

| Information icon | Show a concise explanation without navigating away where practical. |

| Unimplemented feature | Return a controlled Coming Soon / Under Development response. |

| Backend error | Show a friendly error state; never expose a raw traceback. |

| Missing evidence | Represent through Unknown / Partial rather than fabricate a result. |



---

## Steps 3–5 and Global

# UI Specification - Steps 3-5 & Global UI v1

Evidence-Grounded AI Risk Intelligence
Risk Detail • Evidence Explorer • Methodology • Global Interaction

Status: FROZEN FOR MVP DESIGN. This specification completes the remaining MVP UI after Step 1 (Search / Select / Analyse) and Step 2 (Overview Dashboard). The design prioritises evidence traceability, explicit uncertainty, controlled interactions, and a simple interface that can expand later without redesign.

# 1. Complete MVP Navigation

HOME / SEARCH
     |
     v
SELECT COMPANY -> ANALYSE
     |
     v
OVERVIEW
  |       \
  v        v
RISK DETAIL <----> EVIDENCE
      \           /
       \         /
        METHODOLOGY

Persistent navigation:
Overview | Risk Detail | Evidence | Methodology | New Search

History is deliberately deferred from MVP v1. Assessment history may be stored in the backend now and exposed later without changing the primary navigation.

# 2. Step 3 - Risk Detail

Purpose: explain how the Overall result decomposes into Domains, Indicators and Variables. This page answers: 'Why did the system produce this risk assessment?'

## 2.1 Page hierarchy

Overall
├─ Governance
│  ├─ G1 Filing & Regulatory Compliance
│  │  ├─ G1.1 Accounts Filing Lateness
│  │  └─ G1.2 Confirmation Statement Lateness
│  ├─ G2 Management Stability
│  │  ├─ G2.1 Director Turnover - 24 Months
│  │  ├─ G2.2 Median Tenure of Active Directors
│  │  └─ G2.3 Director Change Concentration - 90 Days
│  └─ G3 Ownership & Control Stability
│     └─ G3.1 PSC / Control Change Frequency - 36 Months
└─ Financial
   ├─ F1 Balance-Sheet Strength
   │  ├─ F1.1 Net Asset Position - Equity / Total Assets
   │  └─ F1.2 Net Asset Trend
   ├─ F2 Liquidity Position
   │  ├─ F2.2 Current Ratio
   │  └─ F2.3 Quick Ratio
   └─ F3 Debt & Financing Exposure
      └─ F3.1 Debt Burden - Interest-Bearing Debt / Total Assets

## 2.2 Domain and indicator display

At the top, show the selected domain belief distribution (Low / High / Unknown). Below it, use expandable indicator sections. The page should default to a readable summary and allow drill-down rather than displaying all technical detail simultaneously.

Example variable card:

F2.2 Current Ratio
Value: 1.05
Low 5%   High 90%   Unknown 5%
Reliability: 95%
Risk reference: Low >= 1.5 | High <= 1.1
[View Evidence]   [How assessed?]

## 2.3 Variable states

## 2.4 Risk Detail interactions

- Clicking View Evidence opens Evidence Explorer pre-filtered to that variable.

- Clicking How assessed? shows definition, formula, thresholds/risk direction and model version in a concise panel.

- Indicator/domain sections may expand/collapse; both states must be controlled and preserve navigation.

- Single-child indicators (G3 and F3) should not imply an additional independent calculation; their child result passes through as defined by ER Specification v1.

- No LLM may change a variable value, belief, reliability or aggregation result in the UI layer.

# 3. Step 4 - Evidence Explorer

Purpose: provide the audit trail from a risk variable back to the facts and original evidence. This is the principal differentiator of the product and must make it possible for a reviewer to inspect why a displayed value exists without trusting an AI-generated narrative.

## 3.1 Core evidence chain

Risk Result -> Variable -> Derived Calculation -> Structured Fact -> Evidence -> Original Source

## 3.2 Evidence Explorer default view

When opened from a variable, the page is automatically filtered to that variable. When opened directly from the navigation bar, show a simple selector/filter for Domain, Indicator and Variable.

F2.2 CURRENT RATIO
Derived value: 1.05
Formula: Current Assets / Current Liabilities

FACT 1
Current Assets: £11,557,318
Period: 31 Dec 2025
Source: Annual Accounts
Extraction: structured/deterministic where available
[View source]

FACT 2
Current Liabilities: £10,977,042
Period: 31 Dec 2025
Source: Annual Accounts
[View source]

VALIDATION
✓ Same company
✓ Same reporting period
✓ Currency consistent
✓ Calculation reproducible

EVIDENCE RELIABILITY
95%
[Why this reliability?]

## 3.3 Source detail

View source should reveal provenance appropriate to the source type: Companies House endpoint/record, filing ID, document title, reporting period, retrieval timestamp, and where available an iXBRL concept/tag or PDF page/section. The system should link to the original public source when a stable link is available.

## 3.4 Reliability explanation

Why this reliability? may show the S/E/V/C components and final r because this is a drill-down page, not the Overview. It should explain the components in plain language as well as values. The UI must state that these are MVP evidence-quality parameters and must not imply empirical calibration where none exists.

## 3.5 Conflict and missing evidence

- Conflicting evidence must be displayed rather than silently choosing a preferred value.

- If a hard fail-safe sets reliability to zero, show the reason and resulting 100% Unknown at the leaf variable.

- Missing evidence should show the availability/status code plus a plain-language explanation.

- A source being authoritative as a registry source does not mean the system independently proves every submitted company fact is true.

- Evidence text generated by an LLM is never presented as the original source.

# 4. Step 5 - Methodology

Purpose: let technical reviewers understand what the model does without crowding the operational pages. This page is explanatory and read-only in MVP v1.

The Methodology page should clearly distinguish externally anchored thresholds from MVP heuristics and should display model versions (risk model, reliability model and ER aggregation version) used for the current assessment.

# 5. Global UI Rules

## 5.1 Persistent navigation

MVP navigation: Overview | Risk Detail | Evidence | Methodology, plus New Search.

The active page should be visually identifiable. Navigation must preserve the currently selected company. New Search deliberately exits the current company context.

## 5.2 Controlled response states

## 5.3 Error boundary

No public page may expose raw Python tracebacks, API secrets, database credentials, stack traces, or internal exception objects. Technical details may be logged server-side with a processing-run/error identifier.

## 5.4 Loading and long-running analysis

Use a spinner/progress message during analysis. The first MVP does not require detailed stage animation, but backend processing_run fields should support future stage-level progress. Repeated Analyse clicks should not create uncontrolled duplicate runs.

## 5.5 Accessibility and clarity

- Do not communicate Low/High/Unknown by colour alone; always include text and percentages.

- Buttons and links require meaningful labels, not ambiguous icons alone.

- Belief bars and other visuals need accompanying text values.

- Use readable contrast and responsive layouts suitable for desktop and ordinary mobile/tablet viewing.

- Avoid excessive technical jargon on Overview; detailed terminology belongs in drill-down and Methodology.

## 5.6 Data freshness

Show Assessment date in the company context. Detailed source/reporting dates remain in Evidence. A future Refresh feature can add cache age and data-current indicators without changing the navigation structure.

# 6. Complete MVP Interaction Map

# 7. MVP UI Scope - Frozen

Included:

- Step 1: Search -> Select -> Analyse

- Step 2: Overview Dashboard

- Step 3: Risk Detail

- Step 4: Evidence Explorer

- Step 5: Methodology

- Persistent navigation and controlled response/error/loading states

Deferred:

- Dedicated History page and trend visualisation

- Company comparison

- User accounts and saved watchlists

- Custom risk-model editing

- Report export

- Advanced visual analytics

- Administrative/configuration UI

# 8. Cross-Specification Rules

The UI is a presentation and navigation layer. It must not redefine the Risk Model Specification v1, Evidence Reliability Scheme v1, or ER Aggregation Specification v1. Calculations must be produced by deterministic backend services and rendered by the UI. AI-generated explanations, if later used, may explain validated outputs but may not alter facts, reliability, risk beliefs, weights, thresholds or ER results.

## 8.1 Belief display precision

Low / High / Unknown remain the primary risk representation, with Unknown
visible. Normally display each value to two decimal places; when percentages
are used, the mixed reference displays as 26.65% / 68.92% / 4.43%.
Earlier illustrative wireframes with whole percentages do not override this
formatting rule. No scalar Overall risk score is introduced.

Formatting is presentation-only. Read full-precision authoritative results;
never feed rounded display values back into calculations, validation or
storage. Calculation/storage precision and the ER absolute test tolerance
are defined in `docs/design-docs/er-aggregation-v1.md`, section 12.1.

# 9. Acceptance Criteria for Complete MVP UI

- A new user can independently search for a UK company and reach an assessment.

- The Overview presents Overall, Governance and Financial Low/High/Unknown beliefs clearly.

- The user can drill from Overall/Domain to Indicator/Variable and then to supporting evidence.

- Every material derived value can expose its underlying facts and provenance.

- Missing/conflicting/non-comparable evidence is visible and is not silently fabricated or corrected.

- Methodology and model-version information are accessible without cluttering operational pages.

- Every visible interactive element has a defined response.

- No raw exception, dead click, broken navigation or secret is exposed to the public UI.

- Partial evidence and processing failure are visibly distinct states.

- The UI does not describe belief degrees as probabilities of company failure.

- The design can later add History, comparison and richer visualisation without changing the core evidence chain.

# 10. Final UI Design Principle

Company -> Risk -> Why -> Fact -> Evidence -> Original Source

This traceable path is the central interaction model of the MVP. The interface should remain simple at each level and reveal complexity only when the user deliberately drills down.



| State | UI behaviour |

| --- | --- |

| AVAILABLE | Show value, belief distribution, reliability and evidence link. |

| NOT_DISCLOSED | No fabricated value; show Unknown and explain that required evidence was not disclosed. |

| NOT_APPLICABLE | Show N/A and exclude only according to the frozen model rule; never silently reinterpret. |

| NON_COMPARABLE | Show Unknown for the affected time-dependent variable and explain period comparability. |

| RETRIEVAL_FAILED | Show controlled evidence retrieval failure; do not fabricate. |

| EXTRACTION_FAILED | Show extraction failure and allow evidence inspection if source was retrieved. |

| VALIDATION_FAILED | Show validation issue and resulting uncertainty/fail-safe treatment. |

| CONFLICT_UNRESOLVED | Show conflicting evidence and Unknown according to reliability rules. |





| Section | Content |

| --- | --- |

| Risk Model | Governance and Financial domains; indicators; 11 variables; risk direction; thresholds; importance weights. |

| Evidence Reliability | Source quality, extraction quality, validation and conflict handling; reliability-to-Unknown preprocessing. |

| ER Aggregation | Variables -> Indicators -> Domains -> Overall; Low / High / Unknown; hierarchical aggregation and single-child pass-through. |

| Data Sources | Companies House API, iXBRL and filed accounts/PDF; source priority and fallback policy. |

| Limitations | Heuristic thresholds/weights where applicable, correlated variables, incomplete disclosure, source limitations, and MVP scope. |





| State | Required behaviour |

| --- | --- |

| READY | Page/control is ready for interaction. |

| LOADING | Action is in progress; prevent duplicate accidental submissions where appropriate. |

| SUCCESS | Requested operation completed normally. |

| PARTIAL | Assessment is valid but evidence is incomplete; Unknown communicates uncertainty. |

| EMPTY | No matching content exists; explain what the user can do next. |

| INVALID_INPUT | Explain the input problem and how to correct it. |

| ERROR | Friendly system failure with recovery action where possible. |

| NOT_IMPLEMENTED | Explicit Coming Soon / Under Development response; never a dead click. |





| Location | Action | Response |

| --- | --- | --- |

| Home/Search | Search | Validate input -> company results or controlled empty/error response. |

| Search Results | Analyse | Resolve company number -> cached/live processing -> Overview. |

| Overview | View details | Risk Detail, preserving company context. |

| Overview | Evidence | Evidence Explorer, pre-filtered to selected driver. |

| Risk Detail | View Evidence | Evidence Explorer, pre-filtered to selected variable. |

| Risk Detail | How assessed? | Definition/formula/threshold/model explanation. |

| Evidence | View source | Show source provenance and original-source link where available. |

| Evidence | Why reliability? | Show reliability components and plain-language rationale. |

| Global nav | Methodology | Read-only methodology and limitations. |

| Any page | New Search | Return to Search and clear current company selection after intentional navigation. |

| Any visible unfinished control | Click | Controlled Under Development / Coming Soon response. |

| Any processing failure | Failure | Friendly error; no fabricated assessment; recovery action if safe. |
