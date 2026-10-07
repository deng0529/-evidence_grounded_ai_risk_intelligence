# Six-variable risk reference standards and belief UI — v35

Approved 4 October 2026. Standard name: Risk Reference Standards.
Standard version: six-variable-reference-v1. Model: 1.2.

| Variable | Low risk reference | High risk reference | Unit |
| --- | --- | --- | --- |
| G1.1 Accounts Filing Lateness | 0 | 90 | days |
| G1.2 Confirmation Statement Lateness | 0 | 30 | days |
| G2.2 Median Tenure of Active Directors | 5 | 1 | years |
| F1.1 Net Asset Position | 0.10 | 0 | ratio |
| F2.2 Current Ratio | 1.50 | 1.10 | ratio |
| F2.3 Quick Ratio | 1.00 | 0.70 | ratio |

Migration 017 creates risk_reference_standard (one row per standard version and
variable) and leaf_test_reference_standard (assessment processing-run link).
The Calculate button applies pending migrations on the configured database,
stores the six approved standards, checks same-version drift, and stores the
reference version with the leaf test run. Repeated clicks reuse the standards
and results. Original source records and R2 evidence remain unchanged.
This environment has no user Turso credentials: live persistence occurs when
the user clicks Calculate on their configured installation, not at packaging.

UI order: Governance three-variable percentage table; Financial three-variable
percentage table; stored reference standards table; shared calculation method;
six individual calculations, actual reliability factors, evidence exclusions.
Percentages are belief shares * 100, displayed to two decimal places. Exact
Decimal shares remain stored. Unknown is unresolved belief, not medium risk.

h=clip((x-low)/(high-low),0,1); l=1-h.
r=min(reliability of mandatory usable inputs).
High=r*h; Low=r*l; Unknown=1-r.
Missing/inadmissible value: High=0, Low=0, Unknown=1.
These user-approved initial references and reliability factors are modelling
assumptions, not calibrated company failure probabilities or universal standards.
Reliability-to-Unknown is the project discount policy, not the complete 2013 ER rule.

The missing derivation completeness proof loader now preserves proof=None and
lets the existing FinancialCompletenessRule return its typed hard-fail outcome.
Missing required proof still excludes the corresponding value; it is never
fabricated. Broken lineage and missing referenced source records still fail.
This repairs one reproducible generic-lineage-error trigger. The user's exact
live failure has not been confirmed without diagnostic output.

Install: unzip v35pkg into the existing project directory; stop old Streamlit.
Run each command separately in PowerShell from that project directory:
& ".\.venv\Scripts\python.exe" ".\v35pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, choose Saved company and click Calculate six
variable beliefs. Do not rerun ingestion or old-record cleanup.

Validation: 836 offline tests pass including SQLite/libSQL migration upgrades,
standard idempotency/drift, real Streamlit button/order/percentage columns,
missing derivation proof validation, and unchanged source data. Live five-company
acceptance remains pending. No GitHub push or ER aggregation in this phase.
