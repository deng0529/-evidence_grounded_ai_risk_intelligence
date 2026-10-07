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
