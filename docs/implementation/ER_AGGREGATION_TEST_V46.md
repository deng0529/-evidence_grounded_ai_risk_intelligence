# ER chart and explanation UI — V46, 5 October 2026

The user reported all-green 100% pies while overall metrics showed High/Low
39.99/60.01 and 43.69/56.31. The exact local cause is not established: the old
chart also renders correctly in isolated Vega conversion here. No claim is
made that live company results were revalidated.

The revised chart uses explicit start/end/midpoint angles from the same
full-precision overall ER distribution used for percentage labels. It no
longer relies on implicit stacked theta calculations. ER mathematics, weights,
method identity, source records and saved results remain unchanged.

Removed the repeated three percentage metrics. Kept the domain table and only
three expanded explanation panels: Overall, Governance and Financial.
Removed leaf transformations, source input tables and the technical formula
expander from this ER test UI. The six-variable workflow remains available.

Verification: 893 tests passed; git diff --check passed. Six SVG rendering
cases checked, including both screenshot percentage pairs, mixed Unknown,
and all-Low/all-High/all-Unknown. Added angle/label regressions. vl-convert was
used only for local verification, not added as an application dependency.
No live Turso/R2/LLM access; Windows user acceptance is pending. No Git push.
