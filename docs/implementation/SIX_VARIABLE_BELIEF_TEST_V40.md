# Equity Ratio display terminology — v40

F1.1 is named Equity Ratio in the result table, reference table, explanations
and diagnostic output. Formula NET_ASSETS / TOTAL_ASSETS and unit ratio remain
unchanged. Historical SQL reference row labels remain immutable; the UI applies
the current professional display name. No recalculation or reliability override.

Country Style diagnostic received: G2.2 MISSING_EXACT_APPOINTMENT; F1.1 TOTAL_ASSETS
failed semantic derivation completeness. These are concrete validation exclusions,
not linear interpolation faults. Actual lineage/source records are still needed
to repair them without invented evidence. v40 is a terminology correction only.

12 focused tests passed including the displayed result/reference label and
idempotent standard persistence. Unzip v40pkg into the project folder; run:
& ".\.venv\Scripts\python.exe" ".\v40pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
