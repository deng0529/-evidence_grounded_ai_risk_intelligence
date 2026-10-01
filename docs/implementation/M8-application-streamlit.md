# M8 — End-to-End Streamlit Application

M8 integrates the accepted M4–M7 services. M9 owns deployment/final validation;
older milestone numbering in the archived UI/deployment plans does not expand
this step. No thresholds, reliability, beliefs, weights or historical semantics
are changed.

## Run locally

From the repository root with Python 3.12:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
# For a new local database only, explicitly apply the existing migrations:
.venv\Scripts\python.exe -m risk_intelligence.persistence.migrations
.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

The single entry point is `streamlit_app.py`. Streamlit 1.64.0 is pinned in
`pyproject.toml`; native widgets are used, with no additional chart/UI dependency.

Configuration uses the existing environment variables from `.env.example`.
The app does **not** automatically read `.env`, display settings or apply migrations.
Supply required variables through the process environment. For a local persisted
Golden or another existing SQLite database, set the optional server-side path:

```powershell
$env:RISK_DATABASE_BACKEND = "sqlite"
$env:RISK_EVIDENCE_STORAGE_BACKEND = "local"
$env:RISK_ENVIRONMENT = "development"
$env:RISK_UI_DATABASE_PATH = "data/golden/pipnut-m8-20261001/assessment.sqlite3"
.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Generated Golden files are local acceptance assets, not bundled sample data.
Without a path override, SQLite uses `RISK_LOCAL_DATA_DIRECTORY/metadata.sqlite3`.
Turso uses the existing configured adapter; no silent local fallback is permitted.
Local viewing opens SQLite read-only. Missing/unmigrated databases produce an
actionable error, not an automatically created empty replacement.

## User flow

1. **Load existing assessment:** select company, explicit financial reporting
   year, and assessment/date/version; click Load.
2. **Overview:** exact persisted Overall Low/High/Unknown, followed by Governance
   and Financial beliefs and their persisted Overall importance weights.
3. **Variables:** all six v1.2 leaves, raw values, units, beliefs, reliability,
   availability and persisted exclusion reasons.
4. **Traceability:** select a variable and its M4 input. Inspect the stored
   calculation, validated record, validation/conflict state, source observations,
   canonical components, coverage snapshots and individual evidence locators.
5. **Methodology:** concise stage boundaries and Unknown/importance semantics.

Company name is the current persisted company projection; the assessment's
company number/date and financial reporting year retain their original semantics.
Historical v1/v1.1 assessments are selectable for identification but explicitly
unsupported by M7/M8; their prior audit replay remains available.

**New assessment** is a separate explicit write action. Enter company number,
assessment date and reporting year. Choose live ingestion or supply exact existing
M2/M3 run IDs for reuse. The application invokes `run_company_assessment`, then
`AggregationService`, then loads the result through `ExplanationService`.
Rerendering never invokes the pipeline. Existing results are never overwritten.

Live ingestion requires existing Companies House and storage configuration.
Optional OCR uses `RISK_OCR_TESSDATA` pointing to a directory with
`eng.traineddata`; the existing M3 fingerprint contract is preserved. LLM
extraction is disabled unless explicitly checked and requires the configured
`OPENAI_API_KEY` and `OPENAI_EXTRACTION_MODEL`. `RISK_LLM_CONFIG_VERSION` may supply
an explicit cache configuration version. No model ID is hardcoded. Missing OCR/LLM
configuration does not fabricate financial results; existing extraction and
missingness policies apply. Runs are bounded to 1–10 accounts documents.

## Architecture and exactness

- `services/application.py`: deterministic view envelope, selection metadata,
  safe error messages and production-service orchestration.
- `services/application_runtime.py`: explicit connection/ingestion adapters.
- `ui/streamlit_app.py`: native Streamlit presentation and interaction only.
- `ExplanationService`: the sole source of resolved M4–M7 traceability.

M8 retains the complete M7 tree. All numeric table cells use exact decimal
strings, so no dataframe float conversion changes displayed values. Overall is
the stored M6 ER result; no arithmetic average or second scoring engine exists.
The new assessment repository listing method reads existing contexts only.
No new migration or duplicated result table is needed.

Unknown is always a displayed column, never removed or redistributed. Missing
raw values display “Unavailable” alongside their actual persisted status/cause.
Optional absent metadata stays null/absent. Required broken lineage stops loading
with a safe error. Provider exception text, tracebacks and credentials are never
shown. Failed runs may retain immutable ingestion/partial processing records;
the displayed run ID supports diagnosis without inventing successful results.

Coverage snapshots are distinct from field-level evidence locators. A citation
is not automatically independent validation support; the retained M4 rule roles
and reasons are available. Source URLs/references are displayed as recorded text;
no invented URL, raw-artifact download or R2 request occurs during viewing.

## Acceptance and M9 boundary

Offline M8 tests cover exact M6/M5/M4 wiring, Unknown, reporting year, provenance,
read-only viewing, deliberate production runs, unsupported models, safe errors,
and Streamlit load/drill-down/new-run interactions using AppTest. External network
access is prohibited; Windows asyncio loopback socketpairs are permitted.

Real Pip & Nut validation uses a copy at
`data/golden/pipnut-m8-20261001/assessment.sqlite3`. Recorded M2/M3 runs feed a new
production M5/M6 assessment; M7 and M8 resolve/display it. F1.1 traces GBP
1,083,960 NET_ASSETS (r=0.8075) and GBP 12,232,894 TOTAL_ASSETS (r=0.923) through
COMPANY scope and real PDF locators. Its persisted leaf reliability is 0.8075.
The rendered Overall equals persisted M6 exactly. Original Golden checksum and
copy integrity/FK checks pass. Generated DB/view JSON remain ignored.

M9 still owns hosting, deployment configuration and final live acceptance. M8
has no authentication, job queue, name-search client, automatic migrations,
raw-document serving or speculative narrative. Runs are synchronous. A persisted
assessment status may still say PARTIAL under the frozen M5 lifecycle contract;
M8 shows it truthfully alongside the existing M6 results rather than rewriting it.
