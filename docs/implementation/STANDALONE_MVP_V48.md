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
