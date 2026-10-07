# Simplified six-variable belief UI — v36, 4 October 2026

Presentation update requested by the user; reference version remains
six-variable-reference-v1, calculation/workflow versions unchanged.
Both Governance and Financial tables now contain only Variable, Saved Foundation
value, Unit, High risk, Low risk, Unknown, Reliability, in that order.
Beliefs are 0-1 shares, not percentages. Numeric displays have two decimal places.
Internal precision and persisted values are unchanged. Standards omit Code.
The UI ends with the common method and six short actual reliability explanations;
individual trace expanders and detailed internal input tables are removed.

Reliability explanations use the existing stored S/E/V/C and mandatory input r.
Missing or inadmissible values explain zero reliability with calculation exclusion
codes. Usable values explain the minimum mandatory-input policy. Failed evidence
is not promoted to valid, and zero reliability is not high company risk.

This is a cumulative patch for v33/v34/v35. Migration 017 from v35 is included.
Standard rows are stored on Calculate in the user's configured Turso database.
No new schema, thresholds or reliability policy is introduced by v36. Saved
leaf results are reused; no fresh ingestion, OpenAI or ER call is made.

Stop Streamlit, unzip v36pkg into the existing project directory and run separately:
& ".\.venv\Scripts\python.exe" ".\v36pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Choose Six-variable belief test, choose a saved company, click Calculate six
variable beliefs. No cleanup command is needed.

Verification: 11 targeted tests passed, covering real Streamlit table columns,
result order, shares/two-place formatting, removed detailed panels, standards
persistence, replay and saved source preservation. Prior v35 full suite: 836
passed. Installer/archive verified. Live user Turso testing remains pending.
