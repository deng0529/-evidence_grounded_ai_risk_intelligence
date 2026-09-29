# M3 — Accounts Document & Financial Fact Ingestion

Status: implementation contract with the approved final M3 semantic-normalization
and evidence-grounded dynamic-derivation amendment (2026-09-29). Implementation
and bounded real-data verification are authorized by the associated task; commit
and push still require separate approval.
It refines the [M3 milestone](../implementation/M3-accounts-extraction.md),
preserving the [data dictionary](data-dictionary-v1.md),
[risk model](risk-model-v1.md), [reliability scheme](evidence-reliability-v1.md)
and [ER specification](er-aggregation-v1.md).

## 1. Purpose and boundary

```text
M2 accounts filing metadata → document_metadata → Companies House Document API
→ immutable raw accounts evidence in R2 → representation routing
→ deterministic extraction → optional OCR → optional grounded LLM fallback
→ Source Financial Facts → controlled canonical mapping / derivation
→ Canonical Financial Observations → Turso
```

Routing is conditional, not a requirement to run every extractor. M3 ends at
canonical observations, provenance and processing metadata. It calculates no
Current Ratio, Quick Ratio, Net Asset Trend, Debt Burden, F1/F2/F3 risk,
S/E/V/C/r, Reliability-to-Unknown, ER aggregation or final company risk. It
produces no final risk report or Streamlit UI. Deterministic extraction admission
checks do not constitute M4 validation or reliability assessment.

## 2. Entry point, identity and acquisition

Use existing M2 accounts filing observations, their stable filing transaction
identity and `FILINGS_LINKS_DOCUMENT_METADATA`. Follow reused M2 resource snapshots
to the originating facts; do not require a copy in the latest run. M2 currently
stores document-metadata **links**, not the Document API response or accounts
bytes. M3 retrieves and preserves that metadata response as evidence before
interpreting its representation list. An absent link is explicit missing input.
M3 must not search for companies or independently rediscover accounts filings.

`company_number` remains canonical TEXT (including leading zeroes); reuse the
existing company ID. A filing, document, fact, component and processing run must
belong to the same company. Preserve this lineage in both directions:

```text
M2 filing event/fact → Document Metadata evidence → selected representation
→ raw document evidence → Source Financial Fact → Canonical Financial Observation
```

Keep filing ID, metadata source/evidence IDs, stable remote document identifier,
selected media type, original URL/identifier, retrieval UTC, SHA-256 and local
document/raw IDs. Different metadata responses and representations have separate
retrieval sources: M1 permits only one raw payload per source. Record why a
representation was selected or rejected. Only download representations used for
extraction or specifically needed evidence checks, never all formats for completeness.

Acquisition must have explicit finite request, retry, byte, document and processing
bounds recorded in run configuration. Do not assume that an extension, media type
or successful HTTP response proves usable financial semantics. Unsupported content
is preserved and reported; it cannot silently become an empty successful extraction.
Authenticate only against approved provider endpoints, validate document links and
redirects, and never forward credentials to an arbitrary linked host. Logs and
persisted HTTP metadata exclude credentials and secret-bearing URLs.

## 3. Representation routing

Use the first adequate route for the required observations:

1. Verified machine-readable financial representation preserving
   concept/context/unit/value relationships, normally iXBRL.
2. Other structured representation only with an explicitly understood,
   versioned semantic adapter; untagged XHTML is not automatically financial data.
3. Native-text PDF with deterministic layout-aware extraction.
4. Scanned/image PDF: OCR derived artifact, then deterministic extraction.
5. Optional evidence-grounded LLM fallback for unresolved extraction.

Verification includes content structure, resolvable contexts/units and source
identity. A routing failure may move to the next supported representation without
discarding the failure. Preserve native/scanned/hybrid classification per page;
OCR only pages that require it. The presence of some text, such as a header, does
not establish that a PDF table is deterministically extractable.

## 4. Three observation levels

| Level | Meaning and required lineage |
| --- | --- |
| Source Financial Fact | What one identified source location says, without forced canonical classification. Preserve unresolved source concepts. |
| Canonical Direct Financial Observation | A source fact admitted through a versioned deterministic mapping or evidence/context-verified semantic proposal, with documented unit/sign normalization. |
| Canonical Derived Financial Observation | An exact deterministic calculation from grounded source operands under a verified accounting relationship and independent completeness evidence. |

For each source fact preserve, where supplied: taxonomy namespace/version and
concept; original label and raw lexical value; normalized exact Decimal value;
currency/unit; scale; decimals/precision; sign/transform rule; entity and all context
dimensions (including company/group); context ID; reporting period and instant/
duration type; current/comparative role; document/source/evidence IDs and locator;
extraction method; relevant parser/OCR/LLM versions and processing run.
Absent metadata remains typed NULL; never invent precision or period boundaries.

Store current/comparative role relative to its document, not as an enduring
property of a year. A normalized value is not a claim that the filed statement is
true. `AVAILABLE` means structurally supported extraction, not M4 approval.

Canonical observations retain source fact IDs, concept, value/status, currency,
unit, period, entity scope, evidence IDs, direct/derived origin, mapping version,
derivation version where used and run lineage. Direct/derived origin is not a
replacement for M0 `FactType.NUMERIC`; derived observations use extraction method
`DERIVED` while their components retain their original methods.

The current `FinancialFact`/SQL fact contract is the compatibility foundation,
not a claim that all these new lineage fields already exist. Later implementation
must add typed relational records/links as needed without rewriting migrations
001/002 or stuffing full records into JSON. Unmapped source facts must have their
own source identity, not a fabricated canonical concept. This design specifies
logical requirements, not new DDL. No schema is changed by this documentation task.

## 5. Controlled mapping and six concepts

The output vocabulary has exactly six canonical financial concepts. Supporting
source facts are retained only for mapping, complete derivations or provenance;
M3 is not a general financial-statement extraction system.

| Concept | Admission rule | Downstream use only; not calculated in M3 |
| --- | --- | --- |
| CURRENT_ASSETS | Direct controlled mapping; no arbitrary component construction. | F2.2 and F2.3 numerator inputs |
| CURRENT_LIABILITIES | Direct current/due-within-one-year liabilities. Generic creditors alone is insufficient. | F2.2 and F2.3 denominator |
| INVENTORY | Explicit disclosed stocks/inventory value, including explicit zero. Absence never means zero. | F2.3: (CURRENT_ASSETS − INVENTORY) / CURRENT_LIABILITIES |
| NET_ASSETS | Direct net assets/equity mapping. Net liabilities becomes negative net assets only with explicit taxonomy/sign semantics and a retained normalization rule. | F1.1: NET_ASSETS / TOTAL_ASSETS; F1.2: NET_ASSETS across periods |
| TOTAL_ASSETS | Direct total assets, otherwise a verified complete asset-side derivation. “Total assets less current liabilities” is only a possible cross-check. | F1.1 and F3.1 denominator |
| INTEREST_BEARING_DEBT | Explicit total borrowings/debt with supported interest-bearing scope, or the complete component rule below. Generic creditors is insufficient. | F3.1: INTEREST_BEARING_DEBT / TOTAL_ASSETS |

F2.2 later calculates CURRENT_ASSETS / CURRENT_LIABILITIES. None of these
downstream formulas authorizes M3 ratio calculation.

Mapping registry entries must identify exact taxonomy-qualified concepts or
explicit normalized labels with required table/context qualifiers, target concept,
allowed unit/period/entity scope and normalization rule. Label normalization may
standardize whitespace/case; it must not remove semantic qualifiers. Never use
loose substring guesses such as `"asset" in label`. Unknown taxonomy concepts,
ambiguous labels or unsupported scopes remain unresolved. Deterministic registry
extensions require reviewed versions and evidence-based fixtures. The hybrid
semantic route below supports contextual terminology without inventing equivalence.

### Semantic Concept Normalization — final amendment

Source financial terminology is preserved and normalized to the controlled
canonical vocabulary using deterministic mappings where reliable and
evidence-grounded LLM semantic interpretation where terminology or context
varies. LLM mappings remain subject to evidence/context verification.

Use deterministic mappings first, then optional bounded semantic proposals,
otherwise unresolved. Preserve source IDs, original label/value/locator, statement
type, section/hierarchy, scope, date, currency/unit, proposed concept, method,
rationale, supporting evidence, model/prompt/schema linkage, admission status and
rejection reason. A model proposal never overwrites a source fact. Verify source
identity/value, context, scope, period, units and compatibility with known mappings.
Generic Creditors alone is insufficient; a current-maturity row under an explicit
Company creditors context may qualify. Ambiguity remains unresolved.

### Evidence-Grounded Dynamic Derivation — final amendment

Financial canonical derivations are evidence-grounded and may be dynamically
proposed from filing structure. LLMs may interpret financial structure and
propose derivation plans, but every operand must be grounded in evidence,
final arithmetic is deterministic, and completeness/admission remains
controlled.

Priority: supported direct value, safe deterministic structure, grounded LLM plan,
then unresolved. No universal component list defines TOTAL_ASSETS or debt. Asset
presentations may use fixed/non-current and current subtotals, or a complete
non-overlapping component population. The earlier four-component rule is
superseded as a universal requirement. Missing components are never zero.

Plans retain target, scope/date/unit, ordered source operands and their original
labels/locators, structured operations, rationale, separate completeness evidence,
optional cross-checks, proposal method/version and model-artifact linkage. Record
admission/rejection and the Python-calculated result. Python checks every operand,
scope/date/unit, duplicate/subtotal overlap, supported operations, accounting
relationship and completeness before publication. ADD/SUBTRACT/MULTIPLY/DIVIDE
may be represented as bounded data; operation availability is not authorization
of an accounting relationship. Reject zero division and unsupported/inexact
calculations. No arbitrary expressions, symbolic engine or generated Python.

For current implementation, certified asset-side and exhaustive debt populations
authorize sums; subtraction is also used for supported cross-checks. A model can
select a grounded plan but cannot invent its independent completeness proof.
Unrecognized structures remain unresolved rather than weakening this boundary.
An exposed contradictory cross-check rejects derivation. A direct supported total
takes priority; independent source conflicts remain retained for M4.

PIP & NUT is an acceptance case, not a branch in application code: Company fixed
assets subtotal plus current assets may derive TOTAL_ASSETS. Assets less current
liabilities must not map directly to TOTAL_ASSETS; use it as a cross-check where
available. Arithmetic agreement alone does not establish completeness, especially
for an incomplete list of financing items.

### Complete debt aggregation

The approved derived rule is an exact sum of a source-supported exhaustive,
non-overlapping set of interest-bearing debt components. Potential components
include bank loans, borrowings, finance lease liabilities, hire purchase and
other explicitly interest-bearing financing. A category name alone does not
establish that every balance belongs in this total.

Admission requires evidence defining the complete debt population, all relevant
current/non-current components, one entity scope, one reporting instant, common
currency/unit and no overlap between subtotals and their children. An explicitly
labelled exhaustive borrowing schedule may establish completeness; a collection
of isolated loans does not. Missing components, ambiguous interest-bearing scope,
mixed contexts or incomplete schedules produce NULL with the appropriate status,
never a partial sum labelled total debt. No currency conversion is introduced.

Retain every component source-fact ID, completeness evidence, ordered component
set, formula, rule version, period and evidence links. Prefer supported direct
totals; retain rejected or superseded plans and discrepant evidence for M4
rather than overwriting direct observations. Charges presence does not establish an amount;
absence of charges never establishes debt = 0. Derived does not automatically
mean unreliable: reliability is M4's responsibility.

## 6. Deterministic machine-readable extraction

Resolve taxonomy/source concept, contextRef, unitRef, entity, instant or duration
dates, dimensions, sign, scale, supported transformations and decimals/precision
explicitly. Preserve original attributes and normalization decisions. Parse exact
numbers from lexical text into Decimal, apply supported scale/sign once and do
not round to display precision. Unsupported transforms, invalid units, missing
contexts or ambiguous signs produce extraction failure/candidates, not guessed
numbers. Negative values require supported source semantics, not blanket rejection
or blanket sign inversion. Explicit nil is not zero.

Keep company and group contexts distinct; never silently substitute group values
for the selected company. Retain current and comparative observations independently.
An instant financial amount need not invent a start date; a duration requires both
bounds. The six balance-sheet concepts normally use instant contexts. Unsupported
duration-to-instant mapping is prohibited.

Equivalent observations may be logically deduplicated only within matching entity,
period, unit/currency and semantic context, retaining every evidence occurrence.
Different values for the same canonical concept/period are separate potential
conflicts; differing scopes are retained with their qualifiers. M3 neither chooses
an authoritative value nor assigns M4 conflict penalties.

## 7. PDF, OCR and LLM extraction

Native extraction must recover **row label × column/reporting period × value**
with table headers, currency/scale and entity context. Do not select the nearest
number to a label. Ambiguous columns, signs, scope or headers remain unresolved.
A PDF locator requires document ID, one-based page and source label/context;
section/table and evidence text should be retained where available. Bounding
boxes may help but are not an MVP acceptance requirement.

OCR output is a versioned derived artifact linked to the filed PDF SHA, page
mapping and OCR engine/version/config. The PDF remains authoritative. Preserve
OCR artifact content and checksum in immutable object storage with structured
lineage in Turso; never relabel OCR text as newly filed evidence. Uncertain numeric
recognition remains a candidate/failure, not a corrected guess.

LLM fallback is optional, explicitly enabled, bounded by configured input size,
calls, output and timeout limits, and used only after deterministic processing
cannot resolve required extraction. Document content is untrusted data, not tool
instructions. Supply identified native/OCR evidence and require structured output
containing concept candidate, raw value token, period/unit/sign context, evidence
span and source locator, or an explicit unresolved result.

Before admission, deterministic checks must establish that the cited evidence
exists in the supplied artifact, the numeric token normalizes exactly to the
candidate, and row/column, period, entity, scale and unit semantics support that
association. Finding the same number elsewhere is insufficient. An LLM may propose
a semantic mapping or structured derivation, but cannot modify the registry,
bypass context/completeness admission or resolve a source conflict. Unsupported candidates
remain separate from usable values; failed admission records a reason and
`VALIDATION_FAILED`, without calculating M4 validation strength/reliability.
An unresolved or malformed extraction is `EXTRACTION_FAILED`. Missing API key or
disabled fallback must not break deterministic processing; record why fallback
was unavailable if a document remains unresolved.

## 8. Model configuration and derived artifacts

Model selection is configuration-driven. `OPENAI_EXTRACTION_MODEL` belongs to M3;
`OPENAI_REPORT_MODEL` and `OPENAI_QA_MODEL` are reserved conceptual later-stage
settings, not M3 features. No business-logic model default, including the prior
smoke-test model `gpt-4.1-nano`, is frozen as the production extraction model.
Enabling fallback requires an explicit model/config version. Model upgrades are
reviewed version changes, never automatic switches to a newer model.

Persist model identifier (requested and returned where provided), prompt version,
extraction schema version, relevant model/config version, input evidence fingerprint,
created_at UTC and output/result status for each LLM artifact. Include all settings
that affect extraction; exclude API keys from fingerprints, artifacts and logs.
LLM output is a versioned derived artifact, never an original source or an
authoritative financial fact. Versioned output and admission decisions must be
inspectable even when no candidate is accepted.

## 9. Period-centric observation history and bounded retrieval

Distinguish filing date, document date where supplied, reporting start and reporting
end. Never infer a reporting period solely from filing date. Order candidate M2
accounts newest-first for acquisition, then determine actual periods from evidence.
The analytical acquisition target is the latest three **potentially relevant**
periods where available, not three PDFs, filings or automatically comparable years.

Start with newest relevant accounts and retain current/comparative observations.
Visit older M2-linked accounts only as necessary for up to three distinct candidate
periods, stopping on sufficient coverage, exhausted useful M2 inputs or explicit
retrieval bounds. Record examined/skipped filings, periods found and stopping reason.
Do not discard extra periods already extracted. Period coverage is not proof that
all concepts are disclosed or that observations are comparable.

M2's existing filing window may limit available historical inputs. M3 reports that
coverage limitation rather than bypassing M2 discovery or treating inaccessible
history as non-disclosure. Any broader M2 acquisition is a separate authorized
operation. M4 decides comparability; M3 retains actual dates and normally uses
`REVIEW_REQUIRED` rather than asserting cross-period comparability.

Illustrative synthetic observations, not claims about the smoke company:

| Source | Period | NET_ASSETS |
| --- | --- | ---: |
| 2026 accounts, current | 2026 | 800000 |
| 2026 accounts, comparative | 2025 | 720000 |
| 2025 accounts, current | 2025 | 715000 |

Both 2025 values remain separately supported observations. Newer filings do not
automatically supersede earlier facts. M4 handles reconciliation. Historical
observations remain stored when they fall outside the latest analytical horizon.

## 10. Availability and processing status

Never store literal `UNKNOWN` in typed numeric/date/text values. Use typed NULL
and the existing vocabulary, preserving the M0 exception for non-comparable source
values. ER Unknown exists only at the later belief layer.

| Availability | M3 handling |
| --- | --- |
| AVAILABLE | Supported typed value; not yet M4 validated. |
| NOT_DISCLOSED | Successfully inspected applicable source does not disclose the concept; NULL. |
| NOT_APPLICABLE | Evidence establishes non-applicability; NULL, never invented zero. |
| RETRIEVAL_FAILED | Required source retrieval failed; NULL and failed-source/run provenance. |
| EXTRACTION_FAILED | Retrieved evidence cannot be adequately interpreted; NULL, candidate separately where available. |
| VALIDATION_FAILED | Candidate fails deterministic admission checks; NULL, candidate retained separately. |
| CONFLICT_UNRESOLVED | Vocabulary retained for unresolved selection/validation results; M3 keeps competing observations rather than erasing values. |
| NON_COMPARABLE | Existing source-value contract retains typed values; M3 does not make M4 comparability decisions. |

No disclosed inventory means NULL/NOT_DISCLOSED only after adequate inspection.
Unprocessed, unreadable or inaccessible pages mean an appropriate processing or
retrieval failure, not absence. Explicit inventory zero remains Decimal zero.
Failure to establish total debt cannot become zero or a known partial total.
Do not fabricate a financial period when acquisition fails before one is known.

Acquisition, document processing and company-run status are separate dimensions.
Reuse existing `RetrievalStatus` SUCCESS/FAILED and `ProcessingStatus`
PENDING/RUNNING/COMPLETE/PARTIAL/FAILED with reasons and coverage rather than
creating unnecessary enums. A document is COMPLETE when its applicable pipeline
finished adequately, even with INVENTORY or debt NOT_DISCLOSED. Unsupported or
failed required processing prevents COMPLETE. A company run can be PARTIAL while
retaining valid facts from other documents. Record bounds/coverage separately:
COMPLETE does not assert that three periods or all six concepts exist. Failed
optional fallback does not invalidate already supported deterministic facts.

## 11. Immutable publication and relational separation

The M1 order is mandatory:

```text
external response/document bytes → immutable R2 object
→ readback/checksum verification → parsing/extraction → structured Turso facts
```

Use `EvidencePersistence.save` for raw publication, outside an existing managed
SQL transaction. It owns identity checks, object publication, readback/checksum
verification and atomic source/document/raw SQL metadata publication. After it
returns, parsing may use the same verified in-memory bytes; a second R2 download
is unnecessary. Raw metadata can survive a later extraction failure. SQL failure
may leave an orphan object for safe retry; it does not authorize deletion or a
claim of successful structured publication.

Repositories own relational persistence only. `EvidenceStorage` owns bytes.
The coordinator owns cross-store ordering/integrity. SQL repositories must not
depend directly on `EvidenceStorage`; direct raw repository writes must not bypass
the application publication boundary. Derived-artifact publication must preserve
the same object-before-metadata invariant while identifying artifacts as derived.

R2 is the immutable evidential source; Turso is the operational analytical source.
M4/M5/M6 normal analytical execution reads structured Turso records, not repeated
R2 parsing. Explicit evidence inspection or new validation work may read R2.
Exact Decimal values use M1 TEXT encoding without binary floats; dates remain ISO
dates, timestamps UTC, and provenance links preserve existing company/run checks.

## 12. Persist once and reuse valid work

Persist once, reuse when valid, recompute only when an input or relevant processing
version changes. New orchestration runs link to originating artifacts/facts instead
of copying them or rejuvenating retrieval time. Reuse never overwrites history.

| Level | Reuse identity | Required behavior |
| --- | --- | --- |
| 1: raw evidence | Stable document/representation identity linked to the same content and verified stored SHA | Reuse the existing raw object; no document redownload. Explicit refresh creates a new retrieval event if needed. |
| 2: source facts | Raw SHA plus all relevant parser/OCR/LLM processing versions/config and complete terminal result | No repeated parsing, OCR or LLM extraction. |
| 3: canonical observations | Exact source-fact input fingerprint plus mapping and derivation versions | Reuse canonical IDs; no duplicate observations. |

Resolve stable identity through persisted lineage; a URL alone does not prove
unchanged content after an explicit freshness check indicates change. Verify raw
objects through the M1 verified-read boundary when acquiring them for processing
or checking reuse integrity, not by trusting an ETag as SHA-256. Missing or corrupt
objects cause explicit integrity/retrieval failure, not successful reuse.

Fingerprint identity includes input fingerprint, algorithm/version and relevant
configuration. `created_at` and status accompany that identity as metadata; they
are **not** variable inputs to the hash. Use deterministic serialization and exact
values with stable component ordering. A creation timestamp in the hash would
defeat reuse. Preserve input/output links and original run IDs.

OCR identity: PDF SHA + page selection + OCR engine/version/config.
LLM identity: raw SHA + native/OCR input fingerprint + extraction schema version
+ prompt version + model/config. Canonical identity includes component source
fact IDs/content and mapping/derivation rules, not merely concept and period.
Mapping-only changes must not trigger OCR/LLM again; OCR/parser changes invalidate
only dependent artifacts. A complete cached unresolved result also prevents an
identical automatic LLM call; retry requires a deliberate changed input/version
or controlled retry operation.

Same complete fingerprint must not generate another LLM API call. Later
implementation must atomically claim processing identity to prevent concurrent
duplicate work, publish one terminal result and link other runs to it. An uncertain
remote outcome (timeout/crash after sending) must not be blindly replayed; record
it and require controlled recovery. This is not a claim of distributed exactly-once
delivery. Failed attempts retain history and may be retried under explicit refresh,
new retry run or version change; an ordinary user query is not a retry trigger.

## 13. Downstream assessment snapshot reuse (later stages only)

Completed M4–M6 assessments will be persisted in Turso as versioned snapshots.
Return the latest valid stored assessment for the same company when relevant
evidence/inputs, analytical versions and assessment-date context remain compatible
and freshness does not require refresh. ER must not rerun just because a user
queries the company. Date-dependent governance windows/deadlines are relevant
inputs; unchanged documents alone do not guarantee an unchanged assessment.

If freshness requires checking: company query → lightweight M2 freshness policy
check → no changed relevant evidence or analytical inputs → reuse assessment.
This reuses M2 per-resource contracts; it does not promise an unsupported provider
delta endpoint. If new accounts/evidence exists, process only new/changed evidence,
reuse unchanged M2/M3 artifacts, recompute dependent downstream stages and save a
new snapshot. Retain all older snapshots.

Preserve assessment_date, evidence/input fingerprint, M3 extraction/mapping and
derivation versions, M4 validation/reliability version, M5 risk-model version and
M6 ER version. This cross-stage cache requirement introduces no M4–M6 engine or
assessment-cache implementation in M3.

## 14. Human-readable Data Readiness Report

The real-company M3 Definition of Done requires a CLI/reporting utility producing
a human-readable report for **PIP & NUT LTD**, company number **08624397** (retain
the source-supplied legal-name punctuation). Combine existing M2 inputs with M3
observations for all 11 frozen variables; do not compute the variables, thresholds,
beliefs, reliability or ER. Readiness means input coverage, not validated suitability.

| Future variable | Show these raw inputs and coverage limitations |
| --- | --- |
| G1.1 Accounts Filing Lateness | Accounts due/filing dates and filing/period linkage; identify missing historical due dates. |
| G1.2 Confirmation Statement Lateness | Confirmation due/filing dates and relevant filing linkage. |
| G2.1 Director Turnover — 24 Months | Officer roles, appointment/resignation events and population/history coverage for the window. |
| G2.2 Median Tenure of Active Directors | Active-status source fields and appointment dates; appointed_before is not an exact date. |
| G2.3 Director Change Concentration — 90 Days | Dated director events and population anchors needed for rolling windows, without computing concentrations. |
| G3.1 PSC / Control Change Frequency — 36 Months | PSC/control events, statements, source codes and historical completeness; no substantive-change counts. |
| F1.1 Net Asset Position — Equity / Total Assets | NET_ASSETS and TOTAL_ASSETS, same period/entity/unit. |
| F1.2 Net Asset Trend | NET_ASSETS across candidate periods with actual boundaries and conflicts, pending M4 comparability. |
| F2.2 Current Ratio | CURRENT_ASSETS and CURRENT_LIABILITIES. |
| F2.3 Quick Ratio | CURRENT_ASSETS, INVENTORY and CURRENT_LIABILITIES. |
| F3.1 Debt Burden — Interest-Bearing Debt / Total Assets | INTEREST_BEARING_DEBT and TOTAL_ASSETS, including completeness evidence for derived debt. |

Display each available financial observation's concept, period, exact value,
currency/unit, availability, direct/derived origin, source filing/document,
page/context/locator and extraction method. Show competing observations separately.
For each known candidate period show all six concept outcomes, including explicit
NULL/status/reason rows; do not silently omit missing inventory or debt. When the
period is unknown, report the acquisition failure without inventing period rows.

For each of the 11 variables state whether raw inputs are present, missing or
require review, with reasons and evidence references. This presentation language
does not replace AvailabilityStatus or declare a final computable risk value.
Identify M2 snapshot IDs, run/processing versions, freshness/coverage, missing
documents and retrieval bounds. Known M2 PSC Statements HTTP 404 remains
RETRIEVAL_FAILED/incomplete, never evidence of zero control changes. No statutory
due-date inference, event-rate calculation or comparative-period selection is
performed merely to improve readiness. Actual reports contain observed results,
not the synthetic examples in this design, and remain outside committed fixtures.

## 15. Real smoke verification contract

Later explicitly authorized M3 smoke work uses company 08624397 because M2 has
already persisted its filing evidence and document-metadata links.

First run: existing M2 metadata → Document API → verified R2 accounts evidence
→ extraction/source facts → canonical observations in Turso → Data Readiness
Report. Record actual representation decisions, periods, successes/failures,
missingness, lineage checks and download/OCR/LLM counts. Optional LLM need not run
when deterministic extraction succeeds. Source limitations do not justify invented
values or a claim that all 11 future variables are ready.

Second run, unchanged inputs/versions: show reuse of raw evidence, extraction and
canonical IDs; no unnecessary document redownload, OCR, LLM call or duplicate
canonical observation. Compare fingerprints and operation counts, not just elapsed
time. A new processing run links to old artifacts. Report any controlled retry
separately from successful reuse. This documentation task executes neither run.

## 16. Definition of Done for later M3 implementation

1. M2 accounts filing/document_metadata is the entry point; no independent rediscovery.
2. Used raw accounts representations are immutable R2 evidence.
3. Semantically appropriate deterministic machine-readable extraction has priority.
4. Native-text PDF deterministic extraction is supported.
5. Scanned/image PDF OCR routing is supported.
6. Optional grounded LLM fallback is bounded and safe when disabled.
7. Source Financial Facts are preserved independently of canonical mapping.
8. A controlled versioned registry maps to the six canonical concepts.
9. Controlled derived facts retain complete component/rule/evidence lineage.
10. Current and comparative periods are retained.
11. Equivalent duplicates retain lineage; conflicting observations are not overwritten.
12. Existing availability vocabulary distinguishes disclosure, retrieval, extraction and admission failures.
13. Provenance includes document/page/context and extraction method.
14. Raw/parser/OCR/LLM/mapping/derivation reuse is fingerprint/version based.
15. Identical valid evidence and processing versions do not repeat download/OCR/LLM work.
16. Typed structured financial observations are persisted in Turso.
17. No reliability, risk transformation or ER is performed.
18. The real-company smoke produces the human-readable 11-variable Data Readiness Report.
19. First and second PIP & NUT runs demonstrate processing and reuse.
20. Existing M0/M1/M2 contracts and regression tests remain compatible.

## 17. Required implementation tests

Normal tests are deterministic, offline and use synthetic fixtures. Cover:

- Machine-readable extraction; context/unit/entity/period resolution; current and comparative figures.
- Native PDF layout extraction and routing; scanned/hybrid PDF and OCR routing.
- Missing inventory stays NULL; explicit zero remains zero; supported negative net assets.
- TOTAL_ASSETS versus “Total assets less current liabilities”.
- Direct controlled mapping; unresolved source concepts and unsupported taxonomy transforms.
- Controlled derivations; complete interest-bearing debt aggregation; incomplete/overlapping components never become total debt.
- Equivalent duplicate lineage and same-period conflicting observations.
- Retrieval, extraction and candidate-admission failures; COMPLETE processing with NOT_DISCLOSED concepts.
- Raw, source-fact and canonical reuse; OCR version/config and mapping-version invalidation.
- Disabled LLM/missing key; successful grounded fallback; unsupported numeric candidate rejection.
- LLM fingerprint reuse preventing repeat calls, including concurrent claims and uncertain-outcome recovery.
- Bounded three-period retrieval and M2 coverage exhaustion; no period invented from filing dates.
- R2/checksum failure prevents successful publication; SQL failure preserves safe retry semantics.
- PIP & NUT report shape using synthetic fixtures for offline tests, all 11 input-readiness entries and explicit missing/conflicting values.

Live PIP & NUT verification is separately authorized and credential-isolated;
never run it implicitly in pytest. Run the complete existing regression suite and
`git diff --check` before later implementation acceptance.

## 18. Consistency review and remaining implementation choices

This contract preserves M1 coordinator ownership, SQL/object separation, immutable
R2-before-parsing/publication, M2 document-link provenance and reuse chains, textual
company identity, exact Decimal storage, UTC and all M0 availability/locator rules.
It adds no current schema, enum member, API call or dependency.

The older M3 “filing-to-document discovery” means following M2 links, not another
filing crawler. Its supporting concepts are permitted source/component inputs, not
additional mandatory canonical outputs. Its three-company acceptance is refined
to the explicitly requested primary PIP & NUT smoke; the implementation must not
hard-code that company's data or prevent other company numbers.

The reliability specification's “latest three comparable reporting periods” is
the downstream analytical aim: M3 gathers candidates and M4 judges comparability.
M3 cannot guarantee three comparable periods by assertion. Its “comparable-period
metadata” means preserving boundaries and review status, not computing comparability.
The existing ER mixed-case fixture gap is a later M6 issue, not a license for M3
to invent risk results.

No unresolved methodological conflict blocks this contract. Parser/OCR library
selection, supported exact taxonomy registry entries, explicit operational bounds
and configured extraction model are implementation configuration choices subject
to the admission/versioning rules above. Unsupported semantics fail explicitly;
new accounting admission relationships outside the approved bounded framework
require review. Within it, grounded structured proposals are explicitly permitted.
Additive implementation schema changes preserve existing contracts and applied
migration history.
