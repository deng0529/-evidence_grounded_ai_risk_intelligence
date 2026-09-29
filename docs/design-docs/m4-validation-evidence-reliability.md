# M4 — Validation & Evidence Reliability Engine
## FINAL DESIGN FREEZE AND EXECUTION SPECIFICATION

This specification is authoritative for M4.

Do not redesign the methodology.
Do not invent alternative reliability formulas.
Do not change the frozen risk model.
Do not implement M5/M6/M7.
Do not commit or push until explicitly instructed.

Your role is execution:
1. record this frozen design in the repository;
2. update architecture/cross-reference documentation;
3. report any implementation conflict or ambiguity;
4. do not make methodological decisions independently.

==================================================
1. M4 PURPOSE
==================================================

M2 answers:
"What structured Companies House evidence do we have?"

M3 answers:
"What financial facts can be extracted, normalized and derived from accounts?"

M4 answers:
"Is this evidence analytically admissible, how well is it validated, and how
reliable is it?"

M4 performs:

- admissibility checking;
- validation;
- conflict classification/resolution;
- evidence reliability assessment;
- persistence of validated analytical inputs.

M4 does NOT:

- calculate the 11 risk variables;
- apply risk thresholds;
- calculate Low/High/Unknown risk beliefs;
- perform Reliability-to-Unknown conversion;
- perform ER aggregation;
- generate final company risk scores.

Those belong to M5/M6.

Core flow:

M2 / M3 structured evidence
        ↓
Admissibility Gate
        ↓
Validation Rule Registry
        ↓
Validation Results
        ↓
Conflict Classification / Resolution
        ↓
S / E / V / C
        ↓
Evidence Reliability r
        ↓
ValidatedFact / ValidatedEvidenceSet
        ↓
Turso
        ↓
M5

==================================================
2. CORE PRINCIPLE: AVAILABILITY != RELIABILITY
==================================================

Availability and reliability are separate dimensions.

Example:

value = NULL
availability_status = NOT_DISCLOSED

means the required data is unavailable.

It does NOT mean that a numeric value exists with low reliability.

Example:

value = 11,381,830
availability_status = AVAILABLE
reliability = 0.90

means a value exists but carries residual uncertainty.

Never represent missing data by:
- zero;
- fabricated numeric values;
- low-reliability invented values;
- literal "UNKNOWN" inside numeric/date fields.

Continue using typed availability semantics already frozen in the project:

AVAILABLE
NOT_DISCLOSED
NOT_APPLICABLE
RETRIEVAL_FAILED
EXTRACTION_FAILED
VALIDATION_FAILED
CONFLICT_UNRESOLVED
NON_COMPARABLE

==================================================
3. ADMISSIBILITY GATE
==================================================

Before reliability scoring, determine whether evidence is analytically
admissible.

Some failures must NOT be represented merely by reducing reliability.

Hard-failure examples include:

- missing core required data;
- unsupported LLM-generated numeric values;
- serious unresolved conflict;
- clearly non-comparable periods;
- incompatible Company/Group scope;
- incompatible currency/unit where normalization cannot resolve it;
- failed derivation completeness where a complete total is required;
- evidence identity failure.

A hard-failed analytical input contributes no supported numeric evidence.

Where the frozen reliability representation requires a value:

r = 0

but the typed failure/availability status must also be preserved.

Do not hide the reason behind r=0.

==================================================
4. VALIDATION ARCHITECTURE
==================================================

Validation must be rule-based, extensible, versioned and testable.

Do NOT implement validation as a growing collection of concept-specific
if/elif branches inside the core engine.

Use a Validation Rule Registry.

Conceptually:

Validation Engine
    |
    +-- Core Rules
    |     +-- Identity
    |     +-- Evidence Grounding
    |     +-- Period
    |     +-- Scope
    |     +-- Currency
    |     +-- Unit
    |     +-- Completeness
    |     +-- Conflict
    |
    +-- Financial Rules
    |     +-- Semantic Consistency
    |     +-- Accounting Identity
    |     +-- Derivation Integrity
    |     +-- Double Counting
    |     +-- Comparative Agreement
    |     +-- Restatement
    |
    +-- Governance Rules
          +-- Pagination Coverage
          +-- Window Coverage
          +-- Event Chronology
          +-- Duplicate Event
          +-- Officer Anchor Coverage
          +-- PSC Coverage

Future rules must be addable through implementation + tests + registry
registration without redesigning the validation engine.

==================================================
5. VALIDATION RULE CONTRACT
==================================================

A validation rule must expose a stable/versioned identity.

Conceptual contract:

rule_id
rule_version
applies_to
required_inputs

execute(...)

result:
    PASS
    FAIL
    INCONCLUSIVE
    NOT_APPLICABLE

severity / role:
    INFORMATIONAL
    SUPPORT
    HARD_FAIL

validation_strength_candidate:
    NONE
    MEANINGFUL
    STRONG

independence_group

evidence_ids

reason

structured_details

The exact Python representation may follow repository conventions, but these
semantics must be preserved.

==================================================
6. VALIDATION DIMENSIONS
==================================================

M4 must support at least:

A. Identity validation
- canonical company identity uses company_number;
- evidence must belong to the intended company/entity.

B. Temporal validation
- reporting period;
- reporting date;
- filing date;
- assessment date;
- required analytical horizon;
- period compatibility.

C. Scope validation
- COMPANY;
- GROUP;
- UNKNOWN where genuinely unresolved.

Never silently mix Company and Group evidence.

D. Currency/unit validation
Examples:
GBP
GBP thousands
other explicit scale/unit

Normalize only where supported.

E. Semantic validation
Evaluate the evidence supporting M3 canonical normalization.

M4 does NOT redo M3 semantic normalization.

It evaluates whether the accepted mapping has sufficient contextual support.

F. Structural/accounting validation
Evaluate supported accounting relationships, derivations, subtotals and
cross-checks.

G. Completeness validation
Determine whether the evidence population is sufficiently complete for the
intended analytical use.

H. Conflict validation
Detect, classify and resolve explainable conflicts where deterministic evidence
supports resolution.

==================================================
7. SOURCE QUALITY — S
==================================================

S evaluates source authority/quality.

It does NOT evaluate extraction difficulty.

Frozen MVP v1 values:

Companies House API      0.98
Companies House iXBRL    0.97
Filed PDF                0.95
Company website          0.85

Example:

A scanned Companies House filed PDF still has:

S = 0.95

OCR difficulty belongs to E, not S.

These are versioned MVP engineering heuristics, not empirically proven
probabilities.

==================================================
8. EXTRACTION / INTERPRETATION QUALITY — E
==================================================

Definition:

E measures the reliability of the transformation from source evidence into the
structured/canonical fact used by the analytical system.

Frozen MVP v1 transformation classes:

STRUCTURED_DETERMINISTIC            0.99
TAGGED_IXBRL_DETERMINISTIC          0.98
NATIVE_PDF_DETERMINISTIC            0.95
OCR_DETERMINISTIC                   0.85
GROUNDED_LLM_SEMANTIC               0.85
COMPLEX_LLM_INTERPRETATION          0.75
UNSUPPORTED_LLM_NUMERIC             0 / HARD FAIL

Do NOT create a combinatorial table such as:

OCR × GPT × Python × mapping × derivation ...

Do NOT mechanically multiply transformation-stage reliability values.

Store the complete transformation chain as metadata.

Classify the critical transformation responsible for material interpretation
uncertainty.

Example:

SCANNED_PDF
→ OCR
→ SOURCE_FACT
→ LLM_SEMANTIC_NORMALIZATION
→ DETERMINISTIC_ADMISSION

may be represented as:

critical_transformation = GROUNDED_LLM_SEMANTIC
E = 0.85

The full chain remains stored for explainability.

==================================================
9. DIRECT / DERIVED AND LLM INVOLVEMENT
==================================================

DIRECT versus DERIVED is provenance, not an automatic reliability score.

Do NOT implement:

DIRECT = high reliability
DERIVED = low reliability

A strongly validated deterministic derivation may be highly reliable.

Likewise, LLM involvement does NOT automatically make a fact unreliable.

LLM uncertainty must be represented through the appropriate transformation
class and evidence validation.

M4 must preserve:

normalization_method
derivation_method
LLM artifact/model/prompt/schema linkage where applicable
source fact lineage
evidence lineage

==================================================
10. VALIDATION STRENGTH — V
==================================================

Frozen MVP v1 values:

NONE         0.00
MEANINGFUL   0.30
STRONG       0.60

V represents independent or partially independent validation support.

It is NOT a subjective confidence score.

V must be derived from Validation Rule outcomes.

Do NOT ask an LLM to directly assign V.

--------------------------------------------------
NONE
--------------------------------------------------

No substantive independent validation.

V = 0.

--------------------------------------------------
MEANINGFUL
--------------------------------------------------

At least one substantive and meaningfully independent supporting relationship.

Possible examples:

- the same financial amount appears in another relevant disclosure;
- a later filing comparative supports an earlier observation;
- a meaningful accounting/subtotal relationship independently supports the
  extracted fact.

V = 0.30.

--------------------------------------------------
STRONG
--------------------------------------------------

A strong independent accounting identity or multiple genuinely independent
supporting relationships materially validate the fact.

V = 0.60.

Do NOT implement:

number_of_passed_rules >= 2 → STRONG

Validation independence matters.

Use independence_group or equivalent metadata to avoid double-counting highly
correlated checks.

Admission evidence and validation bonus evidence must also be distinguished.

Evidence required merely to admit a fact must not automatically be counted
again as independent validation.

==================================================
11. CONFLICT PENALTY — C
==================================================

Frozen MVP v1 values:

NONE / RESOLVED         0.00
PARTIAL_UNRESOLVED      0.30
SERIOUS_UNRESOLVED      1.00

Conflict penalty applies to unresolved uncertainty.

A detected difference does NOT automatically imply a conflict penalty.

First classify the difference.

Supported conflict-resolution classifications must include at least:

NONE
RESTATEMENT
SUPERSEDED
EXTRACTION_ERROR
ROUNDING_EXPLAINED
SCOPE_DIFFERENCE
PERIOD_DIFFERENCE
UNIT_DIFFERENCE
UNRESOLVED

Resolved differences normally use:

C = 0

while preserving the complete audit trail.

==================================================
12. RESTATEMENTS
==================================================

Restatements must be explicitly represented.

Example:

2024 filing:
value = A

2025 filing comparative for 2024:
value = B

If the later filing explicitly supports a restatement:

- preserve A as originally reported;
- preserve B as restated;
- preserve lineage;
- mark the relationship;
- use the appropriate current analytical observation according to the
  deterministic restatement policy;
- do not delete A;
- do not treat the resolved restatement as serious unresolved conflict.

Normally:

C = 0

after supported resolution.

==================================================
13. SUPERSEDED / AMENDED FILINGS
==================================================

A superseded filing is historical evidence, not automatically false evidence.

Preserve it.

Where filing B deterministically supersedes filing A:

A:
historical/superseded evidence

B:
current analytical candidate

Preserve provenance for both.

Do not average conflicting filing values.

==================================================
14. EXTRACTION ERRORS
==================================================

If one extraction candidate is demonstrably wrong using source evidence and is
rejected/superseded by the validated candidate, do not necessarily penalize the
accepted fact forever.

Record:

rejected candidate
reason
evidence
resolution

If uncertainty is fully resolved:

C = 0

If material uncertainty remains:

C = 0.30 or 1.00 according to severity.

==================================================
15. ROUNDING AND SCALE
==================================================

Accounting cross-checks must respect reported precision.

Do NOT introduce a universal arbitrary percentage tolerance.

Tolerance should be derived deterministically from evidence such as:

currency
unit
scale
reported precision
decimals

Example:

GBP versus GBP thousands may legitimately create apparent small differences
after presentation rounding.

Record the tolerance basis used.

==================================================
16. CONFLICT RESOLUTION ORDER
==================================================

When competing observations appear to represent the same canonical analytical
fact, resolve in a deterministic order:

1. entity identity compatible?
2. entity scope compatible?
3. reporting period compatible?
4. canonical concept compatible?
5. currency/unit compatible?
6. explicit restatement?
7. explicit amended/superseded filing?
8. demonstrable extraction error?
9. explained rounding/scale difference?
10. accounting cross-check resolves difference?
11. otherwise UNRESOLVED.

Do not resolve conflicts because an LLM merely says one value looks more
plausible.

==================================================
17. LLM ROLE IN M4
==================================================

M4 is deterministic-first.

LLMs may optionally assist with bounded semantic interpretation where existing
structured evidence is insufficient to explain:

- accounting context;
- unusual terminology;
- possible restatement language;
- conflict explanation.

LLM output is a proposal, never final authority.

Any accepted interpretation must remain evidence-grounded and pass deterministic
admission.

LLMs must NOT:

- assign final S/E/V/C values;
- invent numeric facts;
- resolve unsupported conflicts;
- override scope/period/unit incompatibility;
- bypass completeness requirements;
- calculate risk;
- calculate ER.

Normal M4 processing should not require new LLM calls where M2/M3 persisted
evidence and interpretation artifacts are sufficient.

==================================================
18. RELIABILITY FORMULA
==================================================

Frozen M4 formula:

r_base = S * E

r_v = r_base + (1 - r_base) * V

r = r_v * (1 - C)

Final reliability is capped at:

0.99

Do not prematurely round intermediate values.

Hard failures result in no supported numeric analytical evidence and, where
represented numerically:

r = 0

while preserving the typed failure reason.

==================================================
19. RELIABILITY POLICY VERSIONING
==================================================

All S/E/V/C parameter tables must belong to a versioned reliability policy.

Example conceptual identifier:

m4-reliability-v1

Future empirical calibration must create a new policy version rather than
silently rewriting historical assessments.

Every persisted M4 result must record the reliability policy version.

==================================================
20. VALIDATION RULESET VERSIONING
==================================================

Validation rules and rulesets must be versioned.

Example conceptual identifiers:

financial-validation-v1
governance-validation-v1

Every M4 output must record the applicable validation ruleset/version.

Historical assessment reproducibility is mandatory.

==================================================
21. VALIDATED FACT
==================================================

M4 must support a persisted analytical object equivalent to:

ValidatedFact

with at least the semantics:

company_number
canonical_concept
value
reporting_period/date
scope
currency/unit
availability_status

source/evidence identifiers

provenance_type:
DIRECT / DERIVED

normalization_method
derivation_method

transformation_chain
critical_transformation

validation_results
cross_checks

conflict_state
conflict_resolution
conflict_details

S
E
V
C

reliability_r

validation_status

validation_ruleset_version
reliability_policy_version

assessment_date
processing/version metadata

The exact schema may follow existing repository conventions.

==================================================
22. VALIDATED EVIDENCE SET
==================================================

M4 must also support evidence-set validation.

This is required especially for governance variables that depend on event
populations rather than one scalar fact.

Conceptual example:

ValidatedEvidenceSet

company_number
evidence_set_type
analytical_window

source_resource

pagination_complete
window_complete
anchor_coverage
chronology_valid
duplicate_resolution

availability_status

validation_results
conflict_state

S
E
V
C
reliability_r

validation_ruleset_version
reliability_policy_version

assessment_date
processing/version metadata

Example:

OFFICER_EVENTS_24M

may be a validated evidence set used later by M5 to calculate director turnover.

M4 validates the evidence population.

M4 does NOT calculate director turnover.

==================================================
23. GOVERNANCE VALIDATION
==================================================

M4 applies to M2 governance evidence as well as M3 financial facts.

Governance validation must consider where applicable:

- resource pagination completeness;
- analytical-window coverage;
- historical anchor coverage;
- duplicate events;
- appointment/resignation chronology;
- officer event consistency;
- PSC coverage;
- assessment-date boundaries.

A partial resource must not invalidate unrelated company evidence.

Validation/reliability should operate at the narrowest meaningful analytical
input/evidence-set level.

==================================================
24. FINANCIAL VALIDATION
==================================================

M4 must understand M3 provenance including:

- source facts;
- canonical normalization;
- DIRECT versus DERIVED;
- semantic normalization;
- dynamic derivation;
- completeness decisions;
- cross-checks;
- Company/Group scope;
- reporting period;
- currency/unit;
- source filing/document;
- LLM artifacts where applicable.

M4 evaluates these records.

It does NOT redo M3 extraction.

==================================================
25. PIP & NUT GOLDEN FINANCIAL FIXTURE
==================================================

Use existing persisted PIP & NUT evidence as the primary real financial
validation fixture.

Important 2025 example:

Company Fixed Assets:
851,064 GBP

Company Current Assets:
11,381,830 GBP

Derived TOTAL_ASSETS:

851,064
+
11,381,830
=
12,232,894 GBP

Independent cross-check:

12,232,894
-
10,583,194 Current Liabilities
=
1,649,700

which matches reported:

"Total assets less current liabilities"
=
1,649,700

This is an example of strong structural/accounting validation.

Do NOT hard-code company-specific numbers into production rules.

2024 TOTAL_ASSETS is also supported.

2023 TOTAL_ASSETS remains unresolved.

INTEREST_BEARING_DEBT remains unresolved because completeness has not been
established.

Do NOT create a debt total merely to make the fixture complete.

==================================================
26. GOVERNANCE REAL FIXTURE
==================================================

Use the existing M2 PIP & NUT Companies House ingestion as the primary real
governance fixture.

The existing M2 resource state includes:

- profile;
- officers;
- PSC;
- PSC statements retrieval state;
- filing history;
- analytical-window coverage;
- historical anchors where required.

The known PSC Statements 404 must not be silently rewritten into complete/empty
unless supported by an explicitly approved policy.

M4 should preserve the distinction between:

resource retrieval state

and

analytical evidence-set completeness.

==================================================
27. M4 / M5 BOUNDARY
==================================================

M4 validates analytical inputs.

M5 calculates risk variables.

Example:

M4:

CURRENT_ASSETS
value = X
reliability = r1

CURRENT_LIABILITIES
value = Y
reliability = r2

M5 later calculates:

CURRENT_RATIO = X / Y

M4 must NOT calculate the ratio.

Likewise, M4 does not combine r1 and r2 into variable-level reliability.

Variable-level multi-input reliability belongs to M5.

==================================================
28. RELIABILITY-TO-UNKNOWN REMAINS IN M5
==================================================

M4 outputs:

value
reliability r

M5 later transforms the variable value into provisional risk belief:

beta_hat_L
beta_hat_H

then applies:

beta_L = r * beta_hat_L
beta_H = r * beta_hat_H
beta_U = 1 - r

M4 must NOT create Low/High/Unknown risk beliefs.

==================================================
29. M4 EXPLAINABILITY
==================================================

Every reliability result must explain WHY it received its score.

Persist human-readable/structured reasons equivalent to:

S reason:
source authority classification

E reason:
critical extraction/interpretation transformation

V reason:
validation evidence and independent cross-checks

C reason:
conflict state/resolution

Example UI-ready explanation:

Source quality: 0.95
Reason: Companies House filed PDF

Interpretation quality: 0.85
Reason: OCR-based grounded extraction/interpretation

Validation strength: 0.60
Reason: strong independent accounting cross-check

Conflict penalty: 0.00
Reason: no unresolved conflict

Final reliability: calculated deterministically from frozen formula.

Do not treat reliability as an unexplained scalar.

==================================================
30. STORAGE AND NORMAL PROCESSING
==================================================

Turso remains the operational analytical source.

R2 remains the immutable evidential source.

Normal M4 validation reads structured M2/M3 records from Turso.

M4 must NOT routinely reread raw R2 evidence.

R2 may be revisited only for workflows such as:

- evidence investigation;
- reprocessing;
- parser/extractor change;
- conflict investigation requiring raw evidence.

M4/M5/M6 analytical engines must not become directly dependent on R2 for normal
execution.

==================================================
31. IDEMPOTENCY / REUSE
==================================================

The same:

evidence inputs
+ validation ruleset version
+ reliability policy version
+ assessment context

must deterministically reproduce the same M4 result.

Repeated execution should reuse valid results where possible.

Do not create meaningless duplicate validation/reliability records.

Historical results must remain reproducible.

==================================================
32. FUTURE EXTENSIBILITY
==================================================

Validation rules are extensible, versioned policies rather than hard-coded
branches in the validation engine.

New validation knowledge should follow:

new observed pattern
→ evidence review
→ tested validation rule
→ registry registration
→ new/versioned ruleset where required

LLMs may help identify possible new validation relationships.

LLMs must NOT autonomously modify the production validation rule registry.

Future empirical calibration may replace heuristic reliability parameters with
benchmarked values.

That is outside M4 v1.

==================================================
33. HEURISTIC STATUS
==================================================

The following values are MVP engineering heuristics:

S values
E values
V values
C values

They must not be described as scientifically validated probabilities.

Documentation and future UI methodology should describe them as:

versioned heuristic reliability parameters subject to empirical calibration.

==================================================
34. M4 DEFINITION OF DONE
==================================================

M4 implementation will eventually be complete only when:

1. M2 governance evidence can be validated.
2. M3 financial facts can be validated.
3. ValidatedFact is supported.
4. ValidatedEvidenceSet is supported.
5. Availability and reliability remain separate.
6. Hard-failure semantics are preserved.
7. S/E/V/C are explainable.
8. Validation Rule Registry is extensible.
9. Validation rules are versioned.
10. Reliability policy is versioned.
11. Restatements are represented without deleting original evidence.
12. Superseded filings retain provenance.
13. Resolved extraction errors do not automatically create permanent conflict
    penalties.
14. Genuine unresolved conflicts produce appropriate penalty/hard failure.
15. Rounding/scale validation uses evidence-derived tolerance.
16. LLM assistance cannot bypass deterministic admission.
17. Normal M4 execution uses Turso rather than rereading R2.
18. Results are persisted and reproducible.
19. Repeat execution is idempotent/reusable.
20. PIP & NUT financial real-data fixture passes expected behavior.
21. Existing M2 governance real-data fixture passes expected behavior.
22. 2023 PIP & NUT TOTAL_ASSETS remains unresolved unless new supported evidence
    legitimately resolves it.
23. PIP & NUT INTEREST_BEARING_DEBT remains unresolved unless completeness is
    legitimately established.
24. No risk variables are calculated.
25. No Low/High/Unknown risk beliefs are generated.
26. No ER aggregation is implemented.
27. Full regression remains green.

==================================================
35. CURRENT TASK — DOCUMENTATION ONLY
==================================================

For this execution step, DO NOT implement M4 production code yet.

Create the authoritative design document:

docs/design-docs/m4-validation-evidence-reliability.md

using this specification.

Update only the necessary documentation cross-references, including as
appropriate:

ARCHITECTURE.md
AGENTS.md
docs indexes / milestone roadmap references

Preserve existing repository terminology and conventions.

Do not reinterpret or simplify away substantive requirements in this
specification.

Do not change M0–M3 implementation.

Do not create M4 migrations.
Do not add dependencies.
Do not make OpenAI API calls.
Do not access/reprocess R2 evidence.
Do not alter Turso data.
Do not begin M5/M6/M7.

After documentation changes:

1. run documentation/repository consistency checks available in the repo;
2. run git diff --check;
3. inspect git diff;
4. do NOT commit;
5. do NOT push.

Return:

1. files created/changed;
2. concise summary of how the specification was recorded;
3. any ambiguity or conflict discovered against existing frozen documentation;
4. confirmation that no production code/migration/dependency/data changes were
   made;
5. git diff --check result;
6. git status;
7. confirmation that HEAD remains:
   37f2d8c32ae6ec10bf2164716b47c004e4027fb1


## Authoritative pre-freeze clarifications

These four user-approved clarifications are part of the authoritative M4
implementation contract. They resolve the recorded policy questions without
changing the frozen formula, parameter values, risk model or milestone boundaries.
This amendment is documentation only; it authorizes no implementation or migration.

### 1. Admission evidence versus validation evidence

Evidence used to construct a fact must not validate that fact merely by restating
the same derivation. Construction and independent corroboration are distinct.

An independently disclosed value or accounting relationship that was not required
to construct the target fact may provide M4 validation support, even if M3 already
used that relationship as an admission cross-check. Prior use in M3 admission
neither automatically awards nor automatically disqualifies M4 validation support.
M4 must check the actual evidence relationship and independence.

For the PIP & NUT 2025 Company TOTAL_ASSETS golden fixture:

- Fixed Assets + Current Assets constructs TOTAL_ASSETS. That derivation must not
  validate itself.
- The separately reported "Total assets less current liabilities" value, combined
  with independently grounded CURRENT_LIABILITIES, supplies the independent
  accounting cross-check:

  `TOTAL_ASSETS - CURRENT_LIABILITIES = reported Total assets less current liabilities`.

- This qualifies as **STRONG validation (V = 0.60)** for the M4 golden fixture,
  provided scope, period, unit and evidence checks pass.

Do not generalize "M3 admission passed" into automatic M4 validation strength.
Retain the derivation and corroborating evidence separately, apply independence
metadata, and do not count correlated restatements of the same relationship twice.

### 2. Conservative classification policy

Where deterministic evidence/rules cannot establish a classification or resolution,
return **INCONCLUSIVE/UNRESOLVED** rather than guessing. This applies to the recorded
classification, validation-support and conflict-resolution questions; it does not
authorize invented S/E/V/C values or bypass the existing hard-failure semantics.

Rounding tolerance must be derived from source precision, unit and scale. Do not
introduce a universal percentage tolerance. If the available evidence/rule cannot
establish the required tolerance, the check remains inconclusive rather than using
an assumed rounding convention.

Restatement/supersession selection requires explicit evidence supporting the
relationship. Otherwise preserve competing observations and classify the conflict
as unresolved. Do not choose a value merely because it is newer or appears more
plausible, and do not average competing values.

New patterns must be handled by future versioned validation rules rather than
unsupported inference. Existing frozen classifications and values remain in force
where their evidence requirements are satisfied.

### 3. M3 → M4 structured Turso handoff

**Normal M4 execution must not read R2.** Before M4 implementation, inspect the
existing M3 Turso interpretation ledger and structured records to determine whether
they expose all metadata required for M4 validation, including, where applicable:

- normalization method and rationale;
- source fact IDs;
- evidence IDs and locators;
- derivation components;
- derivation expression/plan;
- cross-check relationships;
- completeness result;
- scope;
- period;
- currency/unit;
- interpretation/admission status;
- LLM artifact reference, fingerprint and version metadata.

Reuse existing structured records where sufficient. An artifact reference is not
by itself proof that all required validation metadata is available as structured
Turso data; inspect the actual records and their links.

If required M4 metadata exists only inside an R2 artifact, do not make normal M4
execution read that artifact. **Stop and report the smallest required Turso
schema/handoff extension before implementing it.** Do not create that migration
in this documentation step. This is an explicit pre-implementation inspection and
reporting gate, not an assertion that the existing handoff is already complete or
authorization to extend the schema now.

### 4. Document authority

`docs/design-docs/m4-validation-evidence-reliability.md` is authoritative for M4
implementation, including these clarifications. Where older evidence-reliability
documentation conflicts with this M4 specification, this M4 specification governs
implementation. Preserve historical documents rather than silently rewriting them.

All four recorded clarifications are resolved at the design-policy level. The
structured-handoff inspection and any resulting minimal-extension report remain
required before implementation; they are not waived by this documentation freeze.

## Repository cross-references and implementation review

The original 35-section user-supplied M4 specification is preserved in full above,
followed by the authoritative user-approved clarifications. This appendix records
repository integration findings; it does not independently choose methodology.
Current work remains documentation only (section 35).

### Authority and boundaries

- [M4 milestone](../implementation/M4-validation-reliability.md) links to this
  contract; [roadmap](../implementation/roadmap-v1.md) records the M4/M5 handoff.
- [Evidence Reliability Scheme v1](evidence-reliability-v1.md) retains the formula
  background and historical examples. This later explicit M4 specification governs
  M4 transformation classification, validation independence, conflict handling and
  fact/evidence-set boundaries where older wording differs.
- [M3 contract](m3-accounts-financial-ingestion.md) governs the frozen producer.
  M4 evaluates its retained outputs; it must not redo extraction/normalization.
- [Data dictionary](data-dictionary-v1.md) and existing M0/M1 contracts are the
  compatibility baseline, not a claim that all required M4 records already exist.
- [Risk model](risk-model-v1.md) and [ER specification](er-aggregation-v1.md) are
  unchanged. Reliability-to-Unknown and variable-level multi-input reliability
  belong to M5; aggregation belongs to M6.

### Differences explicitly settled by the new authority

1. **E classification:** the older reliability table assigns OCR plus LLM 0.75
   from its route. Sections 8–9 instead classify the critical transformation:
   GROUNDED_LLM_SEMANTIC 0.85 versus COMPLEX_LLM_INTERPRETATION 0.75, with the
   complete chain retained. Route alone must not select the old value.
2. **V independence:** the older examples describe one/multiple passed checks.
   Section 10 requires substantive independent support, independence grouping and
   separation from admission evidence; counting passed rules is insufficient.
3. **Analytical level:** older reliability/data-dictionary prose describes a
   leaf-variable reliability measure and Unknown outcomes. Sections 21–28 make
   M4 outputs fact/evidence-set level; M5 owns multi-input variable reliability
   and Unknown conversion. These are stage boundaries, not a change to the risk
   model or the frozen reliability formula.

### Resolution of the previously recorded questions

The authoritative pre-freeze clarifications above resolve the admission/validation,
conservative classification, precision/selection, structured-handoff and authority
questions. The PIP & NUT independently disclosed cross-check can qualify as STRONG;
construction does not validate itself. Unsupported classifications/resolutions
remain INCONCLUSIVE/UNRESOLVED. The remaining handoff inspection is an execution
gate, not an unresolved policy choice.

### Existing implementation gaps to address only when M4 is authorized

- M0 ValidationResult has status/severity records, but not the complete rule
  identity/version, applicability, required-input, independence and strength-role
  semantics in section 5. ReliabilityResult records components and a model version,
  but does not implement this policy or the full ValidatedFact/ValidatedEvidenceSet
  contract. Future compatible extensions must preserve historical records and
  applied migrations; this task adds no schema or enum changes.
- M3 stores canonical values, source facts, ordered component lineage and an
  interpretation admission ledger in Turso. Full proposal/context/LLM metadata is
  also retained in R2 artifacts, rather than all being queryable structured Turso
  fields. Apply clarification 3: inspect the existing structured records first,
  reuse sufficient metadata, and stop/report the smallest extension if required
  metadata is R2-only. Do not assume every artifact field needs duplication, make
  normal M4 read R2, or change M3/schema during this documentation task.
- Existing M2 pagination/resource coverage is not automatically proof of every
  requested analytical window or historical anchor. Preserve the PSC Statements
  retrieval failure and evaluate completeness at the narrow evidence-set level;
  no 404-to-empty policy is introduced.

Repository checkpoint inspected: `37f2d8c32ae6ec10bf2164716b47c004e4027fb1`.
No M4 production implementation, migration, dependency or data operation is
performed by this design-recording step.
