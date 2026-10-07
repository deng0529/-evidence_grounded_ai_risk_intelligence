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
