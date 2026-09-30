# M5 — Risk Variable and Leaf Belief Design

Status: approved operational policies frozen; additive obligation-validation-v1
implements the approved M4-to-M5 extension. Existing M4 rulesets remain unchanged.

Baseline: `55551d52098586502de92acd9ec2bcf088077a5d` (M4 Final).
Design date: 2026-09-30.
Calculation policy identifier: `m5-calculation-v1`.

## 1. Authority and scope

This is the authoritative M5 operational design, incorporating the human-approved
Checkpoint 1 policy decisions. [Risk Model v1](risk-model-v1.md) remains authoritative
for the 11 variables, thresholds, directions and importance weights. The
[M4 specification](m4-validation-evidence-reliability.md) governs upstream validation
and reliability. The [data dictionary](data-dictionary-v1.md),
[ER specification](er-aggregation-v1.md) and
[M5 milestone](../implementation/M5-risk-variable-leaf-belief-engine.md) continue
to govern compatible domain contracts and stage boundaries.

The operational decisions fill previously unspecified policies. In particular,
the model's unquantified F1.2 "special handling near zero" is operationalized as
an exact zero-denominator guard; no positive epsilon is introduced. This does not
change the formula, reference levels or risk direction. No direct conflict with
an explicit frozen numerical rule was identified.

M5 consumes persisted M4 validated inputs and their reliability. It does not
recalculate S/E/V/C/r, normalize concepts, resolve source conflicts, extract
evidence, call external services or read R2. M6 owns parent/category/company ER.
Removed variables G1.3, F1.3, F2.1 and F3.2 remain excluded.

## 2. Frozen variable definitions

NA = NET_ASSETS; TA = TOTAL_ASSETS; CA = CURRENT_ASSETS;
CL = CURRENT_LIABILITIES; I = INVENTORY; D = INTEREST_BEARING_DEBT.
References below are exact Decimal values; percentages are represented as ratios.

| ID | Raw calculation | Low reference | High reference | Direction | Local weight |
| --- | --- | --- | --- | --- | --- |
| G1.1 | Accounts obligation lateness in days | 0 | 90 | Higher risk | 0.60 |
| G1.2 | Confirmation obligation lateness in days | 0 | 30 | Higher risk | 0.40 |
| G2.1 | Distinct departing directors / distinct directors immediately before the 24-month window | 0 | 0.50 | Higher risk | 0.40 |
| G2.2 | Median active-director tenure in years | 5 | 1 | Lower risk | 0.25 |
| G2.3 | Maximum computable rolling 90-day distinct-departure ratio | 0 | 0.50 | Higher risk | 0.35 |
| G3.1 | Substantive PSC/control changes in 36 months | 0 | 2 | Higher risk | 1.00 |
| F1.1 | NA / TA | 0.10 | 0 | Lower risk | 0.65 |
| F1.2 | (NA_current - NA_previous) / abs(NA_previous) | 0 | -0.20 | Lower risk | 0.35 |
| F2.2 | CA / CL | 1.50 | 1.10 | Lower risk | 0.60 |
| F2.3 | (CA - I) / CL | 1.00 | 0.70 | Lower risk | 0.40 |
| F3.1 | D / TA | 0.20 | 0.60 | Higher risk | 1.00 |

Governance/Financial weights remain 0.40/0.60. G1/G2/G3 weights remain
0.30/0.45/0.25; F1/F2/F3 remain 0.35/0.40/0.25. Store weights as model metadata;
do not apply them to leaf beliefs. Effective weights remain those in Risk Model v1.

## 3. Beliefs, reliability and availability

For higher-is-riskier variables, provisional High is
`clamp((value - low_reference) / (high_reference - low_reference), 0, 1)`.
For lower-is-riskier variables it is
`clamp((low_reference - value) / (low_reference - high_reference), 0, 1)`.
Provisional Low is one minus provisional High. G3.1 therefore maps 0 to Low,
1 to equal Low/High, and 2 or more to High before reliability discounting.

For usable calculations:

```text
r_variable = min(r_i for every mandatory consumed M4 validated input)
Low     = r_variable * provisional_Low
High    = r_variable * provisional_High
Unknown = 1 - r_variable
```

One input uses its existing r. Deduplicate repeated references to the same
validated input in the trace. Optional corroborating evidence is excluded from
the minimum. No averaging, multiplication, additional extraction penalty or
reapplication of M4 reliability is permitted. A derived validated fact is consumed
with its persisted r, without recursively discounting its construction operands.
Low reliability increases Unknown, not substantive High risk.

An unavailable calculation has NULL raw value and beliefs (0, 0, 1). Never call
`min` on an empty input collection. Preserve upstream AvailabilityStatus and
typed calculation reasons separately: source missingness is not an arithmetic
failure, and arithmetic failure must not masquerade as M4 VALIDATION_FAILED.
Use an M5 calculation-status/reason record alongside the existing result contract
where the existing availability vocabulary cannot faithfully express the cause;
do not silently add meanings to historical enum values.

Required failure, incomplete population, unresolved selection, incompatible
inputs and non-comparable trend periods produce unavailable results. Optional
evidence absence alone does not. No broad NOT_APPLICABLE rule is introduced.
Missing inventory is not zero; partial debt is not total debt. Preserve all 11
leaves without redistributing importance weights.

Calculations use a fixed local Decimal context (precision 50, ROUND_HALF_EVEN),
independent of ambient context. Preserve resulting Decimal values without display
quantization. Beliefs must be bounded and sum to one within absolute tolerance
1e-8. UI rounding never feeds stored calculations.

## 4. Financial input selection and arithmetic

Assessment context explicitly identifies company and analytical scope. Never
prefer COMPANY over GROUP implicitly. Select the latest compatible available
period ending on or before assessment_date for which all mandatory inputs are
usable. Preserve selected IDs and any rejected more-recent candidates/reasons
in the trace; do not silently present an older observation as current-period data.

Same-period inputs must agree on company, analytical scope, period, currency,
unit and upstream validation usability. Do not convert currency or reinterpret
scale. Do not choose arbitrarily between competing validated observations:
use existing explicit resolution lineage, otherwise return unresolved selection.
An equal value alone is not evidence that two conflicting records are equivalent.

F1.2 uses the latest two distinct comparable NET_ASSETS periods, with matching
company/scope/currency/unit. Retain actual boundaries and upstream comparability
status. M5 does not manufacture a new comparability decision or annualize the
change. F1.1/F2.2/F2.3/F3.1 each use a single compatible period.

| Condition | Calculation outcome |
| --- | --- |
| F1.1 or F3.1: TA <= 0 | Unavailable; NON_POSITIVE_TOTAL_ASSETS |
| F1.2: previous NA == 0 | Unavailable; ZERO_PREVIOUS_NET_ASSETS |
| F1.2: nonzero previous NA, however small | Apply exact approved formula; no epsilon |
| F2.2 or F2.3: CL <= 0 | Unavailable; NON_POSITIVE_CURRENT_LIABILITIES |
| F2.3: required inventory absent | Unavailable; MISSING_REQUIRED_INPUT |
| F3.1: debt is partial/incomplete | Unavailable; INCOMPLETE_REQUIRED_INPUT |

These are M5 calculation reason identifiers, not new M4 failure classifications.

## 5. Director calculations

Calendar-month subtraction preserves day-of-month where possible and otherwise
clamps to the last day of the destination month. Date-granularity windows include
assessment_date by using assessment_date + one day as the exclusive end.
The 24-month horizon starts at assessment_date minus 24 calendar months.

Only explicit director roles qualify: `director` and `corporate-director`.
Do not infer a director role from a name or an appointment alone. Other explicit
non-director roles are excluded; missing or unrecognized roles affecting the
population make the calculation unavailable. Corporate directors are distinct
director identities, not assumed natural people.

Resolve person/director identity through structured officer-appointments links.
An appointment-event identifier alone is not a person identifier. Never merge
by name. Missing identity or ambiguous linkage affecting distinct counts produces
Unknown. Repeated observations of one explicitly linked appointment are deduplicated;
unreconciled repeated appointments must not be guessed into a tenure start.

A director is active on date d when appointment <= d and resignation is absent
with valid active-state semantics, or resignation > d. Immediately before d,
appointment must be < d and resignation must be absent or >= d. Explicitly
insufficient appointment bounds produce Unknown when membership cannot be proved.

G2.1 counts distinct eligible identities departing in the 24-month horizon,
divided by distinct eligible identities active immediately before its start.
Incomplete population or zero denominator produces Unknown. Do not cap the raw
ratio at one; only reference-level membership is clamped.

G2.2 uses distinct eligible directors active at assessment_date, with exact
appointment dates for their current tenure. Tenure is elapsed whole date days /
Decimal("365.2425"). Sort tenures; an odd population uses the middle value,
an even population the arithmetic mean of the two middle values. Empty population,
incomplete coverage or ambiguous current tenure produces Unknown.
`appointed_before` is never an exact appointment date.

G2.3 candidate generation is explicitly event-induced, not an unbounded search:

1. Let H be the 24-month horizon start and E = assessment_date + one day.
2. For each distinct eligible departure date d in [H, E), generate candidate
   starts d and d - 89 days. These place d at the first or last included day.
3. Clamp each start into [H, E - 90 days], deduplicate and sort.
4. Evaluate each full [start, start + 90 days) window using distinct departures
   and distinct directors active immediately before start.
5. Exclude zero-denominator candidates as non-computable, retaining the reason.
   Return the maximum computable ratio; ties use earliest start for the trace.

No departures means no event-induced candidates and therefore Unknown under the
approved no-computable-candidate policy, not an invented zero ratio. Incomplete
event/population coverage also produces Unknown. Store all candidate boundaries,
membership IDs, denominator exclusions and selected maximum in the trace.

## 6. PSC/control changes

Use the preceding 36 calendar months through assessment_date. Reconstruct only
the exact validated PSC/statement/filing members. A structured PSC identity and
an explicit dated entry/exit of that identity may establish a population change;
notification date by itself is not automatically an effective control-change date.

Count an entry/exit only where structured event semantics explicitly establish
its effective date and identity. Cross-resource representations linked to that
same underlying event count once. A stable explicitly linked event ID is preferred;
identity, effective date and transition type can identify duplicates only when
the structured evidence establishes their equivalence. Do not merge distinct
changes merely because dates coincide. Contradictory duplicates are unresolved.

Statements, administrative filings, bare notifications and repeated snapshots do
not independently increment the count. Nature-of-control amendments require an
explicit before/after relationship establishing an effective change. No label
interpretation, name matching or reconstruction of undocumented history is allowed.

If unclassified records or ambiguous duplicates could alter the count, return
Unknown with the affected member IDs. Zero is available only when validated
coverage and classified evidence establish no substantive changes. Existing
structured data may consequently produce Unknown; do not weaken these rules to
force a populated metric.

## 7. Read-only governance member access

Add an adapter accepting a persisted ValidatedEvidenceSet ID. Load that exact
record, its ordered snapshot IDs, and existing immutable SQL snapshot-origin
lineage. Reuse the existing structured-fact reconstruction; do not copy observations
into M5 tables, select a newer run or rerun GovernanceValidationService.

Check lineage identity and resource consistency without recomputing evidence
validation or reliability. Return member facts together with the original M4
record/r and exact IDs. Missing/broken lineage is an explicit unavailable input.
No API/R2 access. Optional filing corroboration does not enter the reliability
minimum; filings used to establish a required event or membership do enter it.

## 8. Validated deadline/obligation extension

This belongs at the M4 validated analytical-input boundary, before M5 lateness.
It is not a raw-profile accessor. Proposed contract:

| Field | Meaning / invariant |
| --- | --- |
| validated_obligation_id | Immutable identity of this validated observation |
| company_id, company_number, processing_run_id | Existing company/run lineage |
| assessment_date | As-of date used to validate the obligation state |
| obligation_kind | ACCOUNTS or CONFIRMATION_STATEMENT |
| obligation_key | Explicit source-supported period/made-up-to identity, not due date alone |
| snapshot_observed_at | UTC checked_at of the supported profile snapshot; observation, not legal commencement |
| due_date | Explicit deadline for this exact obligation; nullable only when unusable |
| filing_state | FILED, OUTSTANDING or UNRESOLVED |
| filing_date, filing_fact_ids | Required for FILED; no future filing may satisfy an as-of assessment |
| deadline_fact_ids, evidence_ids, snapshot_ids | Exact structured source and evidence lineage |
| matched_filing_set_id | Existing validated filing population used for matching/absence |
| matching_policy_version | Explicit deterministic obligation-matching policy |
| availability, validation_report, conflict_state | Typed upstream usability and reasons |
| reliability_r, reliability_policy_version, validation_ruleset_version | M4-owned result; never fabricated by M5 |

Persist alongside the existing validated evidence-set handoff, with an immutable
obligation detail record and exact member links; do not overload numeric
validated_fact or rewrite existing M4 rows. Existing M4 reliability machinery
would supply reliability after the required validation, without changing its
formula, cap or existing rules. Migration 010 implements the additive persistence boundary after explicit approval.

Deterministic matching requires the same company, obligation kind and explicitly
supported obligation period/made-up-to key in deadline and filing evidence.
A unique underlying matching filing is required. Deduplicate only explicit
representations of that filing; unresolved matches remain UNRESOLVED.
OUTSTANDING requires a complete validated filing population through the assessment
date plus a supported obligation with no matching filing. Missing data is not
proof of an outstanding obligation. Current profile deadlines may not be assigned
to older filings. Statutory deadline reconstruction is outside this extension.

Select the latest explicitly supported observable obligation valid for assessment,
ordered by supported profile observation timestamp, not due date. A current
next_accounts or confirmation_statement.next_* obligation is eligible even if
its period end/made-up-to date is future. Observation is not legal applicability
or commencement. Period/made-up-to date identifies the obligation; due date
determines due-ness; filing date records receipt; assessment date bounds the
evaluation. Do not assign one date another date's semantics. Competing obligations
without supported ordering remain unresolved. Never extrapolate historical deadlines.

For a usable selected obligation:

- FILED: max(0, filing_date - due_date) in days.
- OUTSTANDING: max(0, assessment_date - due_date) in days.
- UNRESOLVED or missing mandatory validated metadata: unavailable, Unknown=1.

### Additive implementation and supported source shapes

Human approval authorizes obligation-validation-v1 separately from existing M4
financial/governance versions, using unchanged m4-reliability-v1. Migration 010
stores an immutable validated_obligation record with typed JSON assessment and
relational snapshot, validated filing-set and fact lineage. No old row is rewritten.

The source contract uses accounts.next_accounts.period_end_on/due_on and
confirmation_statement.next_made_up_to/next_due. A filing's explicit
FILINGS_DESCRIPTION_VALUES_JSON made_up_date identifies its reporting obligation;
FILINGS_DATE is its receipt date. Unsupported/missing keys and competing filings
remain unresolved. A future current obligation with no matching filing, complete
filing coverage and a due date >= assessment_date is supported outstanding evidence,
so M5 returns zero lateness. Historical snapshots can support their own explicitly
identified obligations; a current deadline cannot supply a different period's due date.

## 9. M5 persistence and versioning design

Preserve VariableResult identity, assessment linkage, beliefs, exact values,
reference levels and version semantics. Add immutable variable calculation records
and ordered validated-input links, rather than lineage only to raw facts.

Retain company/assessment date through immutable assessment context, selected
periods/scope/windows, mandatory/optional input roles, exact ValidatedFact and/or
ValidatedEvidenceSet IDs, proposed validated obligation IDs where applicable,
input r values and upstream policy versions. Store a deterministic structured
trace of selection, operands, arithmetic, reference transformation, minimum-r
selection, reasons and final beliefs. No credential or evidence bytes belong here.

Use the existing reliability_id as the identity of an M5 variable-level reliability
record linking the mandatory M4 inputs and minimum policy, not as a fictional M4
standalone reliability row. It must not recalculate S/E/V/C. Store calculation
status separately for unavailable arithmetic as described in section 3; retain
existing available VariableResult semantics and preserve old domain regression.

Risk Model v1 remains the threshold/weight version. Record m5-calculation-v1 plus
the actual upstream validation/reliability versions (including m4-reliability-v1).
Assessment date, exact input IDs and calculation version determine reproducibility;
changing any relevant input/context/version creates a new result. Exact retries
are idempotent; conflicting retries and historical update/delete are rejected.
M5 persistence uses the next ordered migration after obligation migration 010. Never alter migrations 001–009 or historical M4 data.

## 10. Verification and execution checkpoints

After the obligation-focused and full regression pass, implement:

1. Typed core calculations, reasons, transformations and minimum-r policy.
2. Read-only validated governance membership and approved obligation handoff.
3. Governance variables, including deterministic identity/dedup/window policies.
4. Financial input selection and formulas.
5. Append-only results, validated-input lineage and M6 leaf handoff.
6. Full regression and final scope review.

Focused tests must cover every reference boundary/interpolation, all denominator
guards, missing inventory/partial debt, incomparable/competing observations,
scope/currency/unit isolation, exact-zero versus tiny nonzero trend denominators,
optional versus mandatory reliability, one-time discounting, all-Unknown states,
director identity/role/boundary/reappointment cases, empty G2.3 candidate sets,
PSC ambiguous duplicates and complete zero-event evidence, deadline matching and
as-of outstanding state. Verify Decimal context independence, lineage round trips,
immutable/idempotent persistence and no network/storage effects.

Run focused tests during implementation, then `python -m pytest -q` and
`git diff --check`; preserve all baseline M0–M4 regression behavior. Review the
final diff before any push. M5 completion requires tested obligation and calculation handoffs. No M6 aggregation, cloud deployment or company-specific golden
values are part of production M5 rules.
