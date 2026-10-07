# Active tenure and subtotal semantic validation repair — v41

The Country Style diagnostic establishes two actual exclusions:
G2.2 MISSING_EXACT_APPOINTMENT; F1.1 derived TOTAL_ASSETS rejected by semantic
completeness although NET_ASSETS is supported. Linear interpolation is correct;
excluded analytical inputs cause zero reliability and Unknown.

Fix 1: G2.2 filters definite resignations on/before the assessment date BEFORE
requiring exact appointment dates. Missing historical start dates of retired
directors cannot exclude the current active population. Potentially active
directors still require exact dates; appointed_before is never a substitute.
History-dependent governance variables retain their full-population requirements.

Fix 2: semantic consistency v2 validates the already reviewed reported-subtotal
identities using exact approved M3 regeneration, ordered operands/evidence and
amounts. An explicit subtotal identity is not an exhaustive sum of detail rows.
General row-sum derivations still require their original completeness proof.
Grounding, scope, units, period and identity checks remain mandatory.

Financial validation IDs use financial-subtotal-validation-v3; workflow is
saved-foundation-leaf-test-v41. This avoids writing new validation into old
immutable IDs or replaying the old failed leaf results. M5 selects only this
source-run's financial validation handoff. Source facts and prior records stay
unchanged. No Companies House, R2 processing, OpenAI or ER is invoked.

839 offline tests passed: signed subtotal arithmetic AND semantic gate, wrong
amount rejection, missing generic completeness exclusions, active vs retired
directors with missing dates, historical-row upgrade, six threshold directions,
and five synthetic saved-company source preservation. Live five-company Turso
acceptance has NOT been verified: credentials and remaining four diagnostics
are unavailable here. Numeric presence alone never establishes admissibility.

The professional F1.1 display name is Equity Ratio. Standards and reliability
policy unchanged. Selector begins empty; select a company to calculate/replay.

Stop Streamlit, unzip v41pkg into the project directory and run separately:
& ".\.venv\Scripts\python.exe" ".\v41pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
No cleanup/fresh ingestion needed. This is a tested repair, not a new freeze.
