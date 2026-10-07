# Evidence-Grounded Company Risk MVP

An evidence-grounded company risk assessment MVP using Companies House evidence,
AI-assisted financial extraction and hierarchical Evidential Reasoning (ER).
The current model has three Governance variables and three Financial variables.

## Application entry points

- `streamlit_app.py`: standalone public risk explorer. Overview, Domain analysis,
  Variables & standards and How it works. No sidebar maintenance navigation.
- `maintenance_app.py`: local data foundation, belief and ER test workflows.
- `prepare_dashboard.py`: prepare published display snapshots from existing
  structured company evidence; no new extraction or OpenAI calls.

All entry points share the same services and calculation code.

## Run locally

Use Python 3.12 and install the project with `python -m pip install -e .`.
Configure the existing local `.env` with the database credentials. Secrets are
never committed. Prepare published results once with:

```powershell
& ".\.venv\Scripts\python.exe" ".\prepare_dashboard.py"
```

Start the public explorer:

```powershell
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
```

Local maintenance runs separately with `python -m streamlit run maintenance_app.py`.

## Data and assessment flow

Companies House API and account documents → Cloudflare R2 original evidence →
structured extraction → Turso facts and source references → six reference beliefs →
Governance / Financial ER → Overall ER → Turso published snapshot → Streamlit UI.

Numeric risk transformations and ER are deterministic. AI supports extraction;
it does not assign or overwrite risk results. Missing usable data stays explicit.
Dashboard viewing reads published results without ingestion, calculations,
migrations or database writes. Maintenance preparation upserts one current
snapshot per company. Configuration/source changes require a deliberate refresh.

## YAML configuration

- `src/risk_intelligence/risk_variables/config/risk_model.yaml`: active variables,
  reference levels, units, domains, model versions and ER weights.
- `src/risk_intelligence/services/config/dashboard.yaml`: title, description,
  variable names, formulas, reference explanations and standard version.
- `src/risk_intelligence/services/config/models.yaml`: extraction/explanation
  models, configuration version and verified download hosts.

`services/dashboard_config.py` provides the combined configuration entry point.
New calculation types still require tested Python implementations and input
mappings. YAML alone does not implement a new extraction or calculation method.
Changing references requires a new standard version to preserve historical
standards; published snapshots must be refreshed after configuration changes.

## Hosting

Streamlit Community Cloud is the deployment target. Use `streamlit_app.py`,
Python 3.12, `requirements.txt`, and server-side Secrets based on
`.streamlit/secrets.example.toml`. The public explorer only needs Turso access;
R2, OpenAI and Companies House credentials are not required for viewing.
See `docs/implementation/STANDALONE_MVP_V48.md` for the release workflow.

## Scope and limitations

Current pilot: five retained companies; Governance and Financial only. Reference
benchmarks and weights are approved MVP settings, not empirically calibrated
failure probabilities. Reliability discounting is deferred. Current/Quick Ratios
share inputs; their dependence remains a future validation consideration.

`CURRENT_HANDOFF.md` is the current project handoff. V49 UI was accepted on 7 October 2026 and GitHub publication was authorized.
Public deployment follows the GitHub review. Unit tests use synthetic data; live acceptance
requires the configured database and the five-company review.

Accepted release and hosting instructions: [V49 release](docs/implementation/RELEASE_V49_20261007.md).
