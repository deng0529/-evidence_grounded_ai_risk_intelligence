# Hierarchical ER aggregation test — V45, 5 October 2026

V44 compact six-variable stage accepted by user. User explicitly authorized
next phase: Governance ER of its three variables, Financial ER of its three
variables, then Overall ER of the two domains. Final integrated UI is deferred.

Method: reuse the existing analytical ER engine in aggregation.py, checked
against an independently implemented recursive ER with separate importance
and incompleteness masses. Primary theory: Yang and Xu (2002), Nonlinear
Information Aggregation via Evidential Reasoning in Multiattribute Decision
Analysis Under Uncertainty, IEEE TSMC A 32(3),376-393,
DOI 10.1109/TSMCA.2002.802809. Section II B, equations (6)-(9), PDF pages 3-4,
printed pp.378-379. Author-hosted source:
https://personalpages.manchester.ac.uk/staff/jian-bo.yang/JB%20Yang%20Journal_Papers/ER-Aggregation-IEEE.pdf

Inputs are the accepted V42/V44 reference beliefs, NOT historical discounted
M5 results. No source revalidation, reliability discount, OpenAI, extraction,
R2 read or ER importance redistribution to known siblings occurs. Unknown
is residual assessment incompleteness, not a third explicit grade. Removing
importance-only unassigned mass is part of the ER normalization.

Preserve registry model 1.2: each domain has three equally important variables
(1/3 each); Overall uses Governance=0.40 and Financial=0.60. These project
weights are not prescribed by the paper. Hierarchical aggregation is not a
flat six-variable average. Domain conflict with full Low Governance/full High
Financial yields Overall High=9/13,Low=4/13,Unknown=0, not High=0.60.

Formula (N=2):
s_i = Low_i + High_i
A_n = product_i(w_i*belief_n_i + 1-w_i*s_i)
B = product_i(1-w_i*s_i); C = product_i(1-w_i)
D = A_Low + A_High - B - C
Low = (A_Low-B)/D; High = (A_High-B)/D; Unknown = 1-Low-High.
All engine and intermediate calculations use full-precision Decimal; rounded
UI percentages/values are never reused as aggregation inputs.

UI: new ER aggregation test workflow; empty selector, select company to run.
Top: Overall company risk pie with High/Low/Unknown percentages, legend,
tooltips and exact two-decimal percentage metrics (including zero slices).
Below: two-row Governance/Financial table using decimal belief shares.
Plain-language hierarchy/importance/Unknown explanation follows, with expanders:
1 Overall inputs/domain beliefs and weights;
2 each domain's three input memberships and equal weights;
3 original six-variable saved-value/reference explanations;
4 underlying five financial amounts/document identifiers or governance API dates.
Technical expander includes formula and primary method source. Overall covers
only Governance and Financial, not every type of company risk. It is a belief
assessment, not a probability of default. Current and Quick ratios share inputs;
dependence and weight calibration remain future validation work.

Persistence: migration 020 saved_reference_er, FK to accepted reference result.
Each cached payload stores exact child beliefs, local weights, domain outputs,
overall output, stable logical child IDs and method/model versions. Fingerprint
covers complete payload. Repeated unchanged runs reuse one row. Historical
M4/M5/M6 assessments and immutable source runs remain unchanged.

Verification: 887 offline tests passed. Six analytical-versus-recursive checks
cover Low/High/Unknown unanimity, partial missingness, mixed incomplete support
and conflict. Two-level missing/conflict/all-Unknown regressions, accepted-leaf
preservation, SQL cache/lineage, no old M5 runner, empty UI selector, pie schema,
domain tables and full drill-down verified. Entire regression suite and
 git diff --check passed. Installer byte-copy and ZIP integrity verified.
Live five-company Turso acceptance is not performed here (credentials unavailable).
No freeze/commit/push or next integrated-UI phase has been performed.

Stop Streamlit; unzip v45pkg into project folder. Run separately:
& ".\.venv\Scripts\python.exe" ".\v45pkg\apply_fix.py" "."
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
Choose ER aggregation test, then select one saved company. No extraction or
cleanup is needed. V44 six-variable test remains available unchanged.
