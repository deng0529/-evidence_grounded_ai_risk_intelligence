# Six-variable belief test — v34, 4 October 2026

This temporary test UI adds a saved-company selector and one explicit Calculate
six variable beliefs button. It reads the latest accepted Foundation pair from
Turso, retains the source snapshot's assessment date and actual evidence year,
validates existing structured SQL evidence through M4 and calculates M5 leaves.
There is no Companies House call, raw R2 download, OpenAI call or M6 ER fusion.
The saved Foundation sources and values are preserved. Repeated clicks replay
one saved leaf result per source pair, workflow version and model configuration.

## Reference levels: existing model 1.2

| Variable | Value | Low-risk reference | High-risk reference |
| --- | --- | --- | --- |
| G1.1 Accounts Filing Lateness | Days late | 0 | 90 |
| G1.2 Confirmation Statement Lateness | Days late | 0 | 30 |
| G2.2 Median Tenure of Active Directors | Median years | 5 | 1 |
| F1.1 Net Asset Position | Net assets / total assets | 0.10 | 0 |
| F2.2 Current Ratio | Current assets / current liabilities | 1.50 | 1.10 |
| F2.3 Quick Ratio | (Current assets - inventory) / current liabilities | 1.00 | 0.70 |

High membership h=clip((x-low_reference)/(high_reference-low_reference),0,1).
Low membership l=1-h. Evidence reliability r is the minimum among mandatory
usable validated inputs. Final High=r*h; Low=r*l; Unknown=1-r. An unavailable
or inadmissible value yields High=0, Low=0, Unknown=1. There is no medium-risk
category. Reliability factors and reference levels are versioned MVP modelling
assumptions, not empirically calibrated company-failure probabilities.

M4 reliability: r_base=S*E; r_v=r_base+(1-r_base)*V;
r_input=min(0.99,r_v*(1-C)); hard failure overrides r_input to zero.
S: source quality; E: critical transformation quality; V: eligible independent
validation; C: unresolved conflict. Actual factors, conflicts, validation failures,
calculation traces, exact beliefs and source missingness reasons are shown.

Saved Foundation values and validated values are separate columns. A present
source amount is never silently promoted to fully reliable analytical evidence.
The value-only reference comparison is shown separately; it does not bypass
M4 or replace final beliefs. Missing source-scope/semantic provenance may produce
Unknown even when the Foundation diagnostic value is present; the UI explains
that exact validation failure. No scope or evidence association is fabricated.

## Test boundary
Synthetic offline checks cover six directions and midpoint interpolation,
reliability applied once, missing companies, unchanged source values for five
synthetic companies, validation exclusions, no ingestion/ER, idempotent replay
and the real Streamlit button/rerender path. Live user Turso testing is pending;
this environment does not have the user's credentials. The accepted v33 freeze
remains the baseline; v34 is an unpushed test candidate, not a new freeze.

## User run
Place v34pkg in the existing project root; stop old Streamlit with Ctrl+C.
Run separately in PowerShell:
& ".\.venv\Scripts\python.exe" ".\v34pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Choose Six-variable belief test, select Saved company, then Calculate six variable
beliefs. Ordinary rerenders do not write, calculate, ingest or fuse. No cleanup
command is needed. Existing environment/configuration and cloud evidence remain.

## Next steps
Review all six variable rows and their High/Low/Unknown explanations in the live
UI. Preserve any unresolved M4 metadata limitations for evidence-based follow-up;
never force all numeric rows to AVAILABLE. Domain and Overall ER fusion, final UI
integration and deployment remain deferred.
