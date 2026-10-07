# Independent reliability, expert explanations and evidence — v43

User-approved changes on 5 October 2026:
1. Retain the correct V42 direct High/Low/Unknown memberships unchanged.
2. Calculate source Reliability separately using the existing versioned source
   audit (M4 S/E/V/C policy and M5 minimum-required-input aggregation). Reuse
   its persisted snapshot results. This audits source evidence, not the converted
   membership values. Reliability never discounts V42 memberships. Source audit
   exclusions may yield Reliability=0 while numeric Unknown remains 0; show the
   precise exclusions and inspected factors. A lineage failure shows Unavailable
   without changing reference values. It is not fabricated as zero or one.
3. Explain high-risk financial ratios using actual operands, reference anchors
   and liquidity/equity-buffer interpretation. Do not claim a one-period ratio
   proves which operand changed historically. Low-risk cases remain compact;
   all-variable evidence is available in an expander.
4. Optional OpenAI button generates English expert commentary only for variables
   with High>Low and recorded evidence. English financial/governance expert
   prompt lives in reference_narrative.py. It receives supplied numeric facts,
   reference rationale and evidence locators, never credentials or object paths.
   Output cites supplied evidence IDs only. Exact numeric facts and locators are
   rendered by deterministic code; qualitative AI prose may not contain digits.
   Invalid citations, numeric claims, incomplete output and provider failures
   retain the deterministic explanation. This is bounded AI interpretation,
   not an independent verification of facts or a guarantee of prose accuracy.
5. SQL component lineage resolves each ratio operand and every derived-total
   source component. Display canonical values, original source operands,
   currency/unit, source URL and the exact recorded page/label/section. PDF page
   means the saved one-based physical page. XHTML/iXBRL has no fixed PDF page:
   display concept/context instead; API evidence uses endpoint/JSON path. Missing
   locators are explicit, never invented. Evidence is not re-extracted.
6. Prepare evidence download reads only selected-company supporting bytes from
   existing Local/R2 storage, verifies SHA-256, then exposes a download button.
   Source links are also available. No public R2 bucket or credential-bearing
   link is created; no new Companies House extraction or ER fusion is performed.

Persistence: migration 019 records the explicit link from the V42 numerical
calculation to its independent source audit, and caches expert prose by result,
evidence, model and prompt version. Primary numeric result fingerprints and
immutable standard rows remain unchanged. Unchanged reruns reuse records.
Historical M4/M5 assessments retain their original discount methodology.

Verification: 866 offline tests passed; no real five-company Turso acceptance or
live OpenAI/R2 call was possible here. Tests cover independent reliability,
zero-r preservation for five synthetic saved companies, exact ratio operands in
UI, default empty selector, source API/iXBRL locators, PDF derived-total operands
and page numbers, selected-evidence downloads/checksum rejection, AI citation
and numeric-claim rejection, mocked provider requests and persistent reuse,
plus the full existing regression suite. Installer byte-copy and ZIP integrity
verified. No GitHub push until user acceptance.

Stop Streamlit; unzip v43pkg into the project folder. Run separately:
& ".\.venv\Scripts\python.exe" ".\v43pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Select Six-variable belief test, then select a saved company. Reliability loads
alongside unchanged numeric memberships. High-risk explanations are below.
Click Generate AI explanations for high-risk variables to request/reuse AI prose.
Click Prepare evidence download, then Download source evidence for the original.
No cleanup, full ingestion, re-extraction or .env changes are needed.
