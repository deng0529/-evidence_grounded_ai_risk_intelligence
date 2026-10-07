# Company Risk MVP — accepted V49 release, 7 October 2026

The user accepted V49 and explicitly authorized GitHub publication on
7 October 2026. This supersedes earlier no-push / pending UI acceptance notes.
Public deployment remains pending the user's GitHub review.

## Branches and entry points

- main: accepted integrated MVP after merging feature/unified-risk-mvp.
- feature/unified-risk-mvp: cumulative six-variable, ER and standalone UI work.
- foundation-v33-20261003: preserved historical data-foundation freeze.

Both current branches contain public and maintenance entry points sharing
core services; they are not independent copies of risk calculations.

| File | Responsibility |
| --- | --- |
| streamlit_app.py | Public standalone UI and cloud deployment entry |
| maintenance_app.py | Local foundation / belief / ER testing |
| prepare_dashboard.py | Prepare one published snapshot per saved company |
| src/risk_intelligence/ui/ | UI modules, welcome and architecture diagram |
| src/risk_intelligence/services/ | Application orchestration and display services |
| src/risk_intelligence/risk_variables/config/risk_model.yaml | References, domains and weights |
| src/risk_intelligence/services/config/dashboard.yaml | UI title and variable descriptions |
| src/risk_intelligence/services/config/models.yaml | AI models and extraction configuration |
| .streamlit/config.toml | Theme |
| .streamlit/secrets.example.toml | Credential placeholders only |
| requirements.txt and pyproject.toml | Installable project and pinned dependencies |
| tests/ | Offline automated tests |
| CURRENT_HANDOFF.md | Current authoritative handoff |

Original evidence remains in R2; facts and published results remain in Turso.
Cloud data and secrets are not committed into GitHub. The standalone UI reads
saved snapshots without ingestion, ER calculations, migrations or writes.

## Verification and acceptance

899 automated tests pass. git diff --check passes. V49 UI acceptance was
reported by the user, not repeated with live Turso/R2 credentials here.
No dependency changes beyond the previously accepted V49 UI are required.

## Streamlit Community Cloud preparation

1. Review main on GitHub, especially README and the three root entry points.
2. Confirm local V48/V49 preparation previously printed DASHBOARD_RESULTS_READY
   for the five companies. No new preparation is needed for this release.
3. Sign into https://share.streamlit.io yourself and connect the GitHub account
   that can access deng0529/-evidence_grounded_ai_risk_intelligence.
4. Choose Create app and an existing app. Repository:
   deng0529/-evidence_grounded_ai_risk_intelligence; branch: main;
   entry: streamlit_app.py. Do not select maintenance_app.py.
5. In Advanced settings select Python 3.12. In Secrets enter top-level TOML:

```toml
RISK_DATABASE_BACKEND = "turso"
RISK_EVIDENCE_STORAGE_BACKEND = "local"
TURSO_DATABASE_URL = "libsql://YOUR-DATABASE.turso.io"
TURSO_AUTH_TOKEN = "YOUR-READ-ONLY-TOKEN"
```

Use the real database URL and a read-only Turso token in the hosting Secrets
panel only. Read-only here concerns the deployed viewing token, not the
maintenance token needed to prepare results. R2, OpenAI and Companies House
keys are not required for public viewing. Do not send passwords or keys in chat.
6. Optionally choose an available app subdomain. Deploy only after review.
7. Wait for dependency installation, review logs if startup fails, and test
   Overview, Domain analysis, Variables & standards and How it works.
8. In App settings -> Sharing select public visibility, then verify the link
   in a signed-out/incognito browser and check all five companies.

Official sources checked on 7 October 2026:
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app

---

# Welcome and architecture visual polish — V49, 7 October 2026

User requested a fuller initial screen, a clear attractive architecture diagram,
and modest color/typography refinement. No GitHub push or deployment authorized.

Empty Overview now has a responsive gradient welcome panel, selection prompt,
saved-company count and three exploration cards. Failure states retain explicit
messages rather than displaying the welcome panel as if results were loaded.
Main title/headings use navy/blue; secondary text uses muted slate. Risk colors
retain red, green and gray. No distracting scrolling text or script required.

How it works now shows a nine-stage SVG architecture diagram as an image:
Companies House -> R2 -> extraction -> Turso facts -> reference beliefs -> ER
-> Turso results -> Streamlit UI -> Community Cloud target. Governance API
facts have a direct dashed link into Turso. This is a genuine linked diagram,
not an HTML block of text. Rendering via st.image avoids HTML SVG sanitization.
The diagram was rendered to PNG and visually inspected for clipping/readability.

No YAML/model, source, snapshot or database changes. V48 snapshot fingerprints
remain valid. Users who completed V48 preparation only need install/restart.
Otherwise run prepare_dashboard.py once as documented in V48.

Verification: 899 tests passed; git diff --check clean. Architecture image and
semantic node/link regression added. Existing missing data, connection-failure,
no-selection, saved-result and no-write tests retained. Installer byte-verified.
No live Turso access, Git commit/push or public hosting performed.

Next: user reviews appearance and five company results. GitHub release and
Streamlit Community Cloud deployment remain gated on user acceptance.

---

# Standalone Company Risk MVP — V48, 7 October 2026

User authorized implementation, explicitly no GitHub push until review.
Local branch: feature/unified-risk-mvp. No commit/push/deployment performed.

Public streamlit_app.py is independent of maintenance_app.py. Title:
Evidence-Grounded Company Risk MVP. English introduction; no development-tool
credit on the UI. Larger text, widget labels and tabs; explicit-angle pie uses
smaller radius and top padding. Paper link removed. Four tabs: Overview,
Domain analysis, Variables & standards, How it works. Architecture tab works
without company selection and even when database access is unavailable.

Migration 021 adds dashboard_snapshot, one current payload per company.
prepare_dashboard.py migrates and prepares all existing companies atomically
from existing structured evidence via accepted reference/ER services. It does
not ingest, call OpenAI, clean evidence or create duplicate company snapshots.
Source runs are immutable. Published payload contains chart angles/labels,
domain and variable results, standards, explanations and source input tables.
Viewer reads saved JSON only, with no risk calculations or database writes.
Missing/stale/corrupt results produce helpful messages; no replacement values.
Read-only viewer checks snapshot hash, YAML fingerprint and source-run lineage.

YAML: risk_model.yaml controls variables, anchors, units and ER weights;
models.yaml controls AI models; new dashboard.yaml controls title, descriptions,
variable names/formulas/standard explanation and reference standard version.
services/dashboard_config.py exposes combined loading. New calculation types
still require Python implementation and source mappings. Reference changes
require a new standard version and maintenance refresh, not historical edits.

Verification: full suite 898 passed; final layout-only change followed by
repeat dashboard tests. git diff --check clean. Rendered chart inspected:
39.99/60.01 sectors and labels are complete with top padding. UI regression
covers empty selection, full saved results, missing result, stale config,
connection failure and read-only access without computation. Preparation CLI
verified with synthetic SQLite records. Installer verified by byte comparison.
No live Turso credentials here; five-company publication is performed by user
with the preparation command. No claim of live results validation.

Windows update/test (project directory, commands separately):
1. Stop Streamlit and extract v48pkg into the project directory.
2. & ".\.venv\Scripts\python.exe" ".\v48pkg\apply_fix.py" "."
3. & ".\.venv\Scripts\python.exe" ".\prepare_dashboard.py"
   Wait for DASHBOARD_RESULTS_READY listing retained companies.
4. & ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"

Local maintenance only:
& ".\.venv\Scripts\python.exe" -m streamlit run ".\maintenance_app.py"

Cloud release after acceptance: reviewed feature branch -> main, tag
risk-mvp-v1.0, deploy streamlit_app.py on Streamlit Community Cloud using
Python 3.12 and requirements.txt. Put actual credentials only in Cloud Secrets;
public viewing needs a Turso read-only token, not AI/R2/Companies House keys.
Migration and snapshot preparation use maintenance credentials locally before
publishing. .streamlit/secrets.example.toml has placeholders only. Public
entry exposes no maintenance workflows regardless of RISK_UI_PUBLIC setting.

Next: user tests all five companies, including chart/labels, larger typography,
all tabs and Unknown explanations. Only after approval commit/push and host.

---

# Unified risk explorer — V47, 6 October 2026

Authorized scope: integrate saved foundation, six-variable reference beliefs,
and hierarchical ER in a professional English UI. Cloud deployment is the
next acceptance step, not performed by this patch. No commit/push performed.

Default Risk dashboard: select company (empty placeholder until selection),
then Overview, Domain analysis, Variables & standards tabs. Overview uses
explicit-angle pie of overall ER and Governance/Financial table. Domain tab
shows each three-variable ER and explanation. Variables tab shows six values,
formulas, reference benchmarks, exact linear-transform explanations, Unknown
reasons and saved underlying inputs. No reliability or LLM-generated risk text.

Public viewing uses application_database read-only and persist=False reference
transformation. The same existing approved V42 memberships and V45 ER engine
are used; source values, anchors, weights and mathematical method are unchanged.
No migrations, source ingestion, provider calls or result writes from dashboard.
Existing local maintenance workflows remain in sidebar. RISK_UI_PUBLIC=true
hides all maintenance workflows in public hosting.

Verification: 895 tests passed before final sidebar-only adjustment; dashboard
checks repeated afterward. Tests compare entire database dumps before/after
selection and repeated viewing; no changes. Six leaves, both domains, chart,
no-selection placeholder, tabs and public maintenance isolation are checked.
No live five-company/Turso/R2 access; user acceptance and hosting pending.

Deploy with Python 3.12, entry streamlit_app.py, requirements.txt installing
this repository, and server-side Streamlit Secrets. Read deployment guide.

---

# ER chart and explanation UI — V46, 5 October 2026

The user reported all-green 100% pies while overall metrics showed High/Low
39.99/60.01 and 43.69/56.31. The exact local cause is not established: the old
chart also renders correctly in isolated Vega conversion here. No claim is
made that live company results were revalidated.

The revised chart uses explicit start/end/midpoint angles from the same
full-precision overall ER distribution used for percentage labels. It no
longer relies on implicit stacked theta calculations. ER mathematics, weights,
method identity, source records and saved results remain unchanged.

Removed the repeated three percentage metrics. Kept the domain table and only
three expanded explanation panels: Overall, Governance and Financial.
Removed leaf transformations, source input tables and the technical formula
expander from this ER test UI. The six-variable workflow remains available.

Verification: 893 tests passed; git diff --check passed. Six SVG rendering
cases checked, including both screenshot percentage pairs, mixed Unknown,
and all-Low/all-High/all-Unknown. Added angle/label regressions. vl-convert was
used only for local verification, not added as an application dependency.
No live Turso/R2/LLM access; Windows user acceptance is pending. No Git push.

---

# Hierarchical ER aggregation test — V45, 5 October 2026

V44 compact six-variable stage accepted by user. User explicitly authorized
next phase: Governance ER of its three variables, Financial ER of its three
variables, then Overall ER of the two domains. Final integrated UI is deferred.

Method: reuse the existing analytical ER engine in aggregation.py, checked
against an independently implemented recursive ER with separate importance
and incompleteness masses. Primary theory: Yang and Xu (2002), Nonlinear
Information Aggregation via Evidential Reasoning in Multiattribute Decision
Analysis Under Uncertainty, IEEE TSMC A 32(3),376-393,
DOI 10.1109/TSMCA.2002.802809. Section II B, equations (6)-(9), PDF pages 3-4,
printed pp.378-379. Author-hosted source:
https://personalpages.manchester.ac.uk/staff/jian-bo.yang/JB%20Yang%20Journal_Papers/ER-Aggregation-IEEE.pdf

Inputs are the accepted V42/V44 reference beliefs, NOT historical discounted
M5 results. No source revalidation, reliability discount, OpenAI, extraction,
R2 read or ER importance redistribution to known siblings occurs. Unknown
is residual assessment incompleteness, not a third explicit grade. Removing
importance-only unassigned mass is part of the ER normalization.

Preserve registry model 1.2: each domain has three equally important variables
(1/3 each); Overall uses Governance=0.40 and Financial=0.60. These project
weights are not prescribed by the paper. Hierarchical aggregation is not a
flat six-variable average. Domain conflict with full Low Governance/full High
Financial yields Overall High=9/13,Low=4/13,Unknown=0, not High=0.60.

Formula (N=2):
s_i = Low_i + High_i
A_n = product_i(w_i*belief_n_i + 1-w_i*s_i)
B = product_i(1-w_i*s_i); C = product_i(1-w_i)
D = A_Low + A_High - B - C
Low = (A_Low-B)/D; High = (A_High-B)/D; Unknown = 1-Low-High.
All engine and intermediate calculations use full-precision Decimal; rounded
UI percentages/values are never reused as aggregation inputs.

UI: new ER aggregation test workflow; empty selector, select company to run.
Top: Overall company risk pie with High/Low/Unknown percentages, legend,
tooltips and exact two-decimal percentage metrics (including zero slices).
Below: two-row Governance/Financial table using decimal belief shares.
Plain-language hierarchy/importance/Unknown explanation follows, with expanders:
1 Overall inputs/domain beliefs and weights;
2 each domain's three input memberships and equal weights;
3 original six-variable saved-value/reference explanations;
4 underlying five financial amounts/document identifiers or governance API dates.
Technical expander includes formula and primary method source. Overall covers
only Governance and Financial, not every type of company risk. It is a belief
assessment, not a probability of default. Current and Quick ratios share inputs;
dependence and weight calibration remain future validation work.

Persistence: migration 020 saved_reference_er, FK to accepted reference result.
Each cached payload stores exact child beliefs, local weights, domain outputs,
overall output, stable logical child IDs and method/model versions. Fingerprint
covers complete payload. Repeated unchanged runs reuse one row. Historical
M4/M5/M6 assessments and immutable source runs remain unchanged.

Verification: 887 offline tests passed. Six analytical-versus-recursive checks
cover Low/High/Unknown unanimity, partial missingness, mixed incomplete support
and conflict. Two-level missing/conflict/all-Unknown regressions, accepted-leaf
preservation, SQL cache/lineage, no old M5 runner, empty UI selector, pie schema,
domain tables and full drill-down verified. Entire regression suite and
 git diff --check passed. Installer byte-copy and ZIP integrity verified.
Live five-company Turso acceptance is not performed here (credentials unavailable).
No freeze/commit/push or next integrated-UI phase has been performed.

Stop Streamlit; unzip v45pkg into project folder. Run separately:
& ".\.venv\Scripts\python.exe" ".\v45pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Choose ER aggregation test, then select one saved company. No extraction or
cleanup is needed. V44 six-variable test remains available unchanged.

## Prior stage history
# Compact six-variable MVP interface — V44, 5 October 2026

User-approved simplification:
- One combined six-row table: Variable, Value, Domain, Value basis / formula,
  Unit, High risk, Low risk, Unknown, Unknown reason. Value is the second column.
  All current six indicators are calculated from saved dates or amounts, and
  each formula is identified explicitly. Do not label a derived ratio direct.
- Keep all numeric display values at two decimals, exact internal calculation.
- Remove Reliability and its explanations from this test UI. Do not invoke
  the independent source-audit calculation merely to render this compact view.
  Earlier reliability/evidence/AI modules and records remain available for later
  explicitly approved work; this UI does not call them.
- Remove risk drivers, supporting evidence, AI buttons and diagnostic downloads
  from this compact UI. Empty company selector remains; selection runs once.
- The unchanged six-row reference table includes domain, both anchors, unit,
  and brief reasons for the MVP benchmarks plus inclusive boundary behaviour.
  Reference anchors are user-approved initial heuristic benchmarks, not values
  mathematically determined by ER or empirically calibrated industry standards.
- Common transform formula followed by six per-variable explanations. Show
  whether the actual full-precision value is on/beyond the Low or High side, or
  between the two anchors. Explain the actual resulting decimal memberships.
  Director tenure 4 gives High=0.25 / Low=0.75; tenure 9 gives full Low.
  Equity Ratio 0.20 gives full Low; 0.09 gives High=0.10 / Low=0.90.
- Unknown means no usable saved value. State the actual missing dependency;
  distinguish NOT_DISCLOSED (not identified in supplied data), extraction failure,
  retrieval failure, conflict, incomplete filing history and a zero denominator.
  Extraction failure must not be represented as confirmed company non-disclosure.

Only presentation and test-UI orchestration changed. V42 numeric memberships,
source pair selection, SQL fingerprints, approved immutable standards and
full-precision arithmetic remain unchanged. No re-extraction, OpenAI/R2 calls,
new source audit, ER fusion, raw evidence change or data cleanup is performed.

Verification: 876 offline tests passed; UI covers combined six-row table,
empty selector, no optional audit/buttons/expanders, two-decimal beliefs and
unchanged results. Eight boundary/interpolation examples and two typed-missing
explanation cases added. Full suite and git diff --check passed. Installer byte
copy and ZIP integrity verified. Live Turso five-company acceptance remains
with the user. No GitHub push and no next-stage ER work yet.

Stop Streamlit; unzip v44pkg into the project folder, then run separately:
& ".\.venv\Scripts\python.exe" ".\v44pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, then choose a saved company.
No new data ingestion or .env changes are needed.

## Prior stage history
# Independent reliability, expert explanations and evidence — v43

User-approved changes on 5 October 2026:
1. Retain the correct V42 direct High/Low/Unknown memberships unchanged.
2. Calculate source Reliability separately using the existing versioned source
   audit (M4 S/E/V/C policy and M5 minimum-required-input aggregation). Reuse
   its persisted snapshot results. This audits source evidence, not the converted
   membership values. Reliability never discounts V42 memberships. Source audit
   exclusions may yield Reliability=0 while numeric Unknown remains 0; show the
   precise exclusions and inspected factors. A lineage failure shows Unavailable
   without changing reference values. It is not fabricated as zero or one.
3. Explain high-risk financial ratios using actual operands, reference anchors
   and liquidity/equity-buffer interpretation. Do not claim a one-period ratio
   proves which operand changed historically. Low-risk cases remain compact;
   all-variable evidence is available in an expander.
4. Optional OpenAI button generates English expert commentary only for variables
   with High>Low and recorded evidence. English financial/governance expert
   prompt lives in reference_narrative.py. It receives supplied numeric facts,
   reference rationale and evidence locators, never credentials or object paths.
   Output cites supplied evidence IDs only. Exact numeric facts and locators are
   rendered by deterministic code; qualitative AI prose may not contain digits.
   Invalid citations, numeric claims, incomplete output and provider failures
   retain the deterministic explanation. This is bounded AI interpretation,
   not an independent verification of facts or a guarantee of prose accuracy.
5. SQL component lineage resolves each ratio operand and every derived-total
   source component. Display canonical values, original source operands,
   currency/unit, source URL and the exact recorded page/label/section. PDF page
   means the saved one-based physical page. XHTML/iXBRL has no fixed PDF page:
   display concept/context instead; API evidence uses endpoint/JSON path. Missing
   locators are explicit, never invented. Evidence is not re-extracted.
6. Prepare evidence download reads only selected-company supporting bytes from
   existing Local/R2 storage, verifies SHA-256, then exposes a download button.
   Source links are also available. No public R2 bucket or credential-bearing
   link is created; no new Companies House extraction or ER fusion is performed.

Persistence: migration 019 records the explicit link from the V42 numerical
calculation to its independent source audit, and caches expert prose by result,
evidence, model and prompt version. Primary numeric result fingerprints and
immutable standard rows remain unchanged. Unchanged reruns reuse records.
Historical M4/M5 assessments retain their original discount methodology.

Verification: 866 offline tests passed; no real five-company Turso acceptance or
live OpenAI/R2 call was possible here. Tests cover independent reliability,
zero-r preservation for five synthetic saved companies, exact ratio operands in
UI, default empty selector, source API/iXBRL locators, PDF derived-total operands
and page numbers, selected-evidence downloads/checksum rejection, AI citation
and numeric-claim rejection, mocked provider requests and persistent reuse,
plus the full existing regression suite. Installer byte-copy and ZIP integrity
verified. No GitHub push until user acceptance.

Stop Streamlit; unzip v43pkg into the project folder. Run separately:
& ".\.venv\Scripts\python.exe" ".\v43pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, then select a saved company. Reliability loads
alongside unchanged numeric memberships. High-risk explanations are below.
Click Generate AI explanations for high-risk variables to request/reuse AI prose.
Click Prepare evidence download, then Download source evidence for the original.
No cleanup, full ingestion, re-extraction or .env changes are needed.

## Prior stage history
# Direct saved-value reference beliefs — v42, 5 October 2026

User explicitly approved direct conversion of accepted Foundation values without
another evidence validation pass or a reliability discount. The test UI now reads
the latest saved M2/M3 pair and applies the six existing anchors once. It calls
no M4/M5 runner, provider, LLM or ER aggregation. Existing full assessment paths
and historical validation/reliability results retain their original methodology.

Numeric value: High=clip((x-low)/(high-low),0,1); Low=1-High; Unknown=0.
Missing value: High=0; Low=0; Unknown=1. No missing inventory is replaced by zero.
Negative values and both reference directions are supported; non-finite numbers
fail explicitly. Equity Ratio remains NET_ASSETS/TOTAL_ASSETS.

Reliability is displayed as Not applied, not fabricated as 1.00. Numerical
memberships do not certify source accuracy. There is no post-transform evidence
revalidation. Two-decimal display does not alter exact Decimal calculation.

Migration 018 stores these reference results separately from evidence-adjusted
M5 results. Fingerprint covers method, standards, source pair, exact input values
and anchors. Repeated unchanged selection reuses one record. Existing evidence
and historical results are unchanged. Standards retain their immutable approved
rows; method saved-value-linear-no-discount-v42 records the new calculation.

Offline verification: 856 tests passed including ten numeric examples, six
missing values, SQL replay without M4 or source mutation, UI default placeholder,
and schema upgrades on sqlite/libsql. Five live Turso companies are not verified
here; user acceptance is the next step. No GitHub push until acceptance.

Stop Streamlit; unzip v42pkg into the project directory. Run each line separately:
& ".\.venv\Scripts\python.exe" ".\v42pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, then select a company. No calculation button.
No cleanup, extraction or .env changes are required.

## Prior stage history
# CURRENT_HANDOFF — v41 upgrade repair, 5 October 2026

# Active tenure and subtotal semantic validation repair — v41

The Country Style diagnostic establishes two actual exclusions:
G2.2 MISSING_EXACT_APPOINTMENT; F1.1 derived TOTAL_ASSETS rejected by semantic
completeness although NET_ASSETS is supported. Linear interpolation is correct;
excluded analytical inputs cause zero reliability and Unknown.

Fix 1: G2.2 filters definite resignations on/before the assessment date BEFORE
requiring exact appointment dates. Missing historical start dates of retired
directors cannot exclude the current active population. Potentially active
directors still require exact dates; appointed_before is never a substitute.
History-dependent governance variables retain their full-population requirements.

Fix 2: semantic consistency v2 validates the already reviewed reported-subtotal
identities using exact approved M3 regeneration, ordered operands/evidence and
amounts. An explicit subtotal identity is not an exhaustive sum of detail rows.
General row-sum derivations still require their original completeness proof.
Grounding, scope, units, period and identity checks remain mandatory.

Financial validation IDs use financial-subtotal-validation-v3; workflow is
saved-foundation-leaf-test-v41. This avoids writing new validation into old
immutable IDs or replaying the old failed leaf results. M5 selects only this
source-run's financial validation handoff. Source facts and prior records stay
unchanged. No Companies House, R2 processing, OpenAI or ER is invoked.

839 offline tests passed: signed subtotal arithmetic AND semantic gate, wrong
amount rejection, missing generic completeness exclusions, active vs retired
directors with missing dates, historical-row upgrade, six threshold directions,
and five synthetic saved-company source preservation. Live five-company Turso
acceptance has NOT been verified: credentials and remaining four diagnostics
are unavailable here. Numeric presence alone never establishes admissibility.

The professional F1.1 display name is Equity Ratio. Standards and reliability
policy unchanged. Selector begins empty; select a company to calculate/replay.

Stop Streamlit, unzip v41pkg into the project directory and run separately:
& ".\.venv\Scripts\python.exe" ".\v41pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
No cleanup/fresh ingestion needed. This is a tested repair, not a new freeze.

## Prior stage record
# CURRENT_HANDOFF — v40 upgrade repair, 5 October 2026

# Equity Ratio display terminology — v40

F1.1 is named Equity Ratio in the result table, reference table, explanations
and diagnostic output. Formula NET_ASSETS / TOTAL_ASSETS and unit ratio remain
unchanged. Historical SQL reference row labels remain immutable; the UI applies
the current professional display name. No recalculation or reliability override.

Country Style diagnostic received: G2.2 MISSING_EXACT_APPOINTMENT; F1.1 TOTAL_ASSETS
failed semantic derivation completeness. These are concrete validation exclusions,
not linear interpolation faults. Actual lineage/source records are still needed
to repair them without invented evidence. v40 is a terminology correction only.

12 focused tests passed including the displayed result/reference label and
idempotent standard persistence. Unzip v40pkg into the project folder; run:
& ".\.venv\Scripts\python.exe" ".\v40pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"

## Prior stage record
# CURRENT_HANDOFF — v39 upgrade repair, 5 October 2026

# Company selection and exact belief diagnostics — v39

Select a saved company to view its beliefs is the default placeholder. No
calculation runs until a company is selected. No threshold/reliability changes.
Download calculation diagnostic exports exact saved/admitted values, references,
reliability and actual validation exclusions. No credentials are exported.

The two screenshots have numeric Foundation values but zero final reliability.
Actual exclusions are needed to diagnose these cases. Do not bypass validation
or claim the live Unknown values are repaired. Live Turso access unavailable.

Stop Streamlit, unzip v39pkg into the project directory; run separately:
& ".\.venv\Scripts\python.exe" ".\v39pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, select the company, download its diagnostic.
No ingestion, OpenAI, cleanup or ER. 12 targeted tests passed, including no
selection means no result write. Live belief correction remains pending exact
failure reasons from the user's existing data.

## Prior stage record
# CURRENT_HANDOFF — v38 upgrade repair, 5 October 2026

# Saved-assessment upgrade repair — v38, 5 October 2026

V37 changed financial validation rules but reused legacy validated_fact IDs.
Immutable persistence consequently rejects changed validation results against
existing IDs. Empty-database tests failed to cover this upgrade scenario.

V38 uses a separate financial-subtotal-validation-v2 identity namespace and
passes the exact newly selected validated financial IDs to M5. This prevents
both immutable ID collisions and ambiguous mixing of old/new validation records.
Old records, raw source facts and R2 evidence remain unchanged. Workflow version
saved-foundation-leaf-test-v38 ensures failed/old leaf results are not replayed.
No Companies House, PDF processing, OpenAI or ER invocation is added.

The simplified UI, automatic company selection, two-decimal shares and approved
six-variable-reference-v1 standard remain unchanged. No cleanup command needed.

Stop Streamlit; unzip v38pkg into the existing project directory; run separately:
& ".\.venv\Scripts\python.exe" ".\v38pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, then select a saved company.

Verification: 838 offline tests passed, including an upgrade from prior persisted
financial validation IDs, preservation of historical records, exact current
handoff selection, and repeat-result reuse. Installer/archive verified.
Live user Turso confirmation is pending; no credentials are available here.

## Prior stage record
# CURRENT_HANDOFF — v36 UI candidate, 4 October 2026

Foundation v33 remains frozen on GitHub main at
9279bed19042393f21bbda9e6ab1d85d5e85aaee, freeze branch foundation-v33-20261003.
Latest-only cleanup and five-company acceptance were user-confirmed. Never rerun
cleanup or ingestion for this phase. Companies: 05127466, SC137690, 08624397,
02554051, 02251694. Missing HP Foods inventory must not become zero.

User approved the existing six reference pairs on 4 October and requested their
versioned Turso persistence and UI results -> standards -> method ordering.
See docs/implementation/SIX_VARIABLE_BELIEF_TEST_V35.md for full contracts.
Migration 017 adds the immutable six-row risk_reference_standard and run-version
link. Standard six-variable-reference-v1, workflow saved-foundation-leaf-test-v35.
Same-version drift raises; identical clicks reuse stored rows/results. Source
values, saved snapshot dates and raw R2 evidence remain unchanged. No OpenAI,
Companies House or ER call is made. Code/UI English; communicate in Chinese.

The missing completeness-proof loader now reaches existing M4 typed exclusions,
instead of aborting every variable. It does not invent proof or admit unsupported
values. This fixes one reproduced error path; the user's actual generic lineage
error remains unconfirmed pending live test/diagnostic output. Other iXBRL source
scope or semantic provenance limitations remain visible as validation failures.

836 offline tests passed; installer preserves .env and archive verified.
No user Turso credentials are available here. Standards are written to user's
configured DB on Calculate. v35 is unpushed, awaiting live five-company UI test.
Next: review actual six values/percentages/exclusions in UI; if blocked capture
safe diagnostic stage and exact static integrity error. Preserve unknown reasons.
Stop at individual six-leaf beliefs; domain/Overall ER remains next phase.

## Latest user presentation changes (v36)
Six-variable test tables: Variable, Saved Foundation value, Unit, High risk,
Low risk, Unknown, Reliability. No Code or Validated value used. Belief shares
0-1 with two decimals; all numeric displays two decimals, full stored precision
retained. Reference standards omit Code; then common formula and concise actual
reliability explanations. Remove all later detailed panels. User explicitly
requested this simplified layout. No threshold/calculation/reliability change.
Workflow remains saved-foundation-leaf-test-v35 to reuse existing results.
11 targeted tests pass; v35 full suite 836 passed. Cumulative v36 installer tested.
Live acceptance pending; no GitHub push. See SIX_VARIABLE_BELIEF_TEST_V36.md.

## Latest user presentation changes (v37)
Six-variable test tables: Variable, Saved Foundation value, Unit, High risk,
Low risk, Unknown, Reliability. No Code or Validated value used. Belief shares
0-1 with two decimals; all numeric displays two decimals, full stored precision
retained. Reference standards omit Code; then common formula and concise actual
reliability explanations. Remove all later detailed panels. User explicitly
requested this simplified layout. Reference thresholds and reliability policy unchanged. M4 signed subtotal identity validation fixed; added regression for wrong amount and missing general proof.
Workflow is saved-foundation-leaf-test-v37 to revalidate saved evidence after the subtotal fix.
837 offline tests pass; v35 full suite 836 passed. Cumulative v37 installer tested.
Live acceptance pending; no GitHub push. See SIX_VARIABLE_BELIEF_TEST_V37.md.

## Latest user presentation changes (v37)
Six-variable test tables: Variable, Saved Foundation value, Unit, High risk,
Low risk, Unknown, Reliability. No Code or Validated value used. Belief shares
0-1 with two decimals; all numeric displays two decimals, full stored precision
retained. Reference standards omit Code; then common formula and concise actual
reliability explanations. Remove all later detailed panels. User explicitly
requested this simplified layout. Reference thresholds and reliability policy unchanged. M4 signed subtotal identity validation fixed; added regression for wrong amount and missing general proof.
Workflow is saved-foundation-leaf-test-v37 to revalidate saved evidence after the subtotal fix.
837 offline tests pass; v35 full suite 836 passed. Cumulative v37 installer tested.
Live acceptance pending; no GitHub push. See SIX_VARIABLE_BELIEF_TEST_V37.md.
