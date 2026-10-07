# Simplified six-variable belief UI — v37, 4 October 2026

Presentation update requested by the user; reference version remains
six-variable-reference-v1, calculation/workflow versions unchanged.
Both Governance and Financial tables now contain only Variable, Saved Foundation
value, Unit, High risk, Low risk, Unknown, Reliability, in that order.
Beliefs are 0-1 shares, not percentages. Numeric displays have two decimal places.
Internal precision and persisted values are unchanged. Standards omit Code.
The UI ends with the common method and six short actual reliability explanations;
individual trace expanders and detailed internal input tables are removed.
V37 additionally auto-loads/calculates when a saved company is selected, with
no Calculate button. Net Asset is a display label for NET_ASSETS/TOTAL_ASSETS.
A confirmed M4 mismatch is repaired: reviewed M3 balance-sheet-subtotals-v1
identities must reproduce their signed arithmetic, including subtraction,
instead of summing every operand. Explicit subtotal identities do not require
an exhaustive row-population proof. They are admitted only when the existing
reviewed M3 function regenerates the exact formula, ordered source IDs,
evidence IDs and amount; all other identity/scope/unit/period checks remain.
Missing general row-sum completeness proofs still fail validation.
This reproduces a plausible Net Asset Unknown cause, not a confirmation of the
user screenshot cause. Live Turso values cannot be verified without credentials.
Five-company synthetic saved-data preservation tests and all six reference
midpoint/direction checks pass. The source facts are never overwritten.

Reliability explanations use the existing stored S/E/V/C and mandatory input r.
Missing or inadmissible values explain zero reliability with calculation exclusion
codes. Usable values explain the minimum mandatory-input policy. Failed evidence
is not promoted to valid, and zero reliability is not high company risk.

This is a cumulative patch for v33/v34/v35. Migration 017 from v35 is included.
Standard rows are stored on Calculate in the user's configured Turso database.
No new schema, thresholds or reliability policy is introduced by v37. Saved
leaf results are reused; no fresh ingestion, OpenAI or ER call is made.

Stop Streamlit, unzip v37pkg into the existing project directory and run separately:
& ".\.venv\Scripts\python.exe" ".\v37pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Choose Six-variable belief test, choose a saved company, results load automatically. No cleanup command is needed.

Verification: 837 offline tests passed, covering real Streamlit table columns,
result order, shares/two-place formatting, removed detailed panels, standards
persistence, replay and saved source preservation. Prior v35 full suite: 836
passed. Installer/archive verified. Live user Turso testing remains pending.
