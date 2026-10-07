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
