# M3 implementation notes

Implementation against frozen design baseline `fa392930c7d71c0944ed799c7b2b567f5494ac7b`.
The frozen design remains authoritative except for the explicitly approved narrow
final semantic-normalization and dynamic-derivation amendment below. This note does not approve a commit.

## Components and boundaries

`ingestion/accounts/client.py` follows M2's existing Document API metadata links,
with bounded HTTPS requests and an explicit redirect-host allowlist. Credentials
are sent only to the official Document API host; signed download URLs are transient.
`acquisition.py` publishes metadata and selected document bytes through M1's
`EvidencePersistence` coordinator before extraction. SQL repositories have no
object-storage dependency. `accounts_repository.py` persists source observations,
canonical lineage and complete component links. Existing M2 snapshots remain readable.

`ixbrl.py` preserves exact monetary values, qualified concepts, context, units,
entity, dimensions, current/comparative periods, sign, scale and precision metadata.
Only supported inline monetary semantics are admitted; XML/XHTML without these
semantics falls through to another advertised representation. No extension-only
routing, external XML entities or generic XML value guessing is used.

`pdf.py` uses PyMuPDF word positions and reporting-year columns. Scanned/hybrid
pages use its Tesseract OCR pathway when explicitly configured. Company and group
statement headings retain different scope. Exact approved labels, unique amounts
within disjoint year bands, and an unambiguous printed current-assets subtotal
can produce direct observations. A subtotal is read, never invented by summing
arbitrary rows. Unsupported layouts remain partial/failed.

`mapping.py` contains the versioned exact registry: FRC 2024 core monetary concepts
and qualified PDF labels. Unknown taxonomy versions/dimensions remain unresolved.
`derivation.py` retains the historical exhaustive-debt gate. `interpretation.py`
admits contextual mappings and dynamic expressions against independently verified
statement proofs. `asset_side.py` supports subtotal and component presentations. Generic creditors, charges and
"total assets less current liabilities" never become debt or total assets.

`service.py` processes newest M2 accounts links until three candidate period ends,
input exhaustion, or a configured document bound (default five, maximum ten).
It does not determine comparability. Missing values remain typed NULLs; PDF
disclosure coverage is not proven, so unavailable concepts are EXTRACTION_FAILED,
not presumed NOT_DISCLOSED or zero. Explicit inline nil can be NOT_DISCLOSED.

## Schema and reuse

Migration 003 adds accounts-document lineage, source financial occurrences,
direct/derived component edges, durable processing claims and run/document outcomes.
Migration 004 adds immutable run-to-processing and run-to-observation membership.
The latter prevents later parser results from changing a previous run's financial
input set. Both are additive; migrations 001/002 are byte-for-byte unchanged.
Migration 003 was applied during the first live smoke, so the subsequent extension
is a separate migration rather than rewriting an applied migration.

Canonical monetary values remain exact Decimal/text through M1's existing fact
repository. Raw/OCR/LLM artifacts stay in immutable object storage, not SQL blobs.
Creation time is recorded but is not a cache-key input. Keys include verified
raw SHA, document identity, stage, parser/OCR/model configuration and versions.
Canonical keys also include source-result SHA, mapping and derivation versions.
Missing-observation identities include extraction identity. Source and canonical
conflicts are append-only; M4 owns resolution.

Complete cache hits verify stored bytes and do not invoke the operation again.
RUNNING/FAILED claims are not blindly replayed: uncertain work requires explicit
reconciliation and a deliberate version/retry configuration. Reuse is currently
within an established document identity; identical bytes under different document
identities are processed separately to preserve occurrence lineage.

## Dependencies and operation

New exact runtime pins: `pymupdf==1.28.2` for native PDF/OCR and `openai==3.20.0`
for the optional official SDK fallback. Existing dependencies are unchanged.
OCR requires separately provisioned English trained data. The smoke used the
official `tessdata_fast` `eng.traineddata` SHA256
`7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`,
stored only under ignored `data/tessdata/`. OCR fingerprints include that checksum,
PyMuPDF version, English language and 200 DPI.

`examples/ingest_accounts.py` requires explicit `--live`, company, assessment date,
new run ID and report path, with Turso/R2 settings supplied through environment.
It does not implicitly load or edit `.env`. Optional `--tessdata` enables OCR;
`--download-host s3.eu-west-2.amazonaws.com` authorizes the observed provider
download host. A PARTIAL/FAILED run deliberately exits 2, while retaining its
report and evidence. It verifies checksums and foreign keys after ingestion.

LLM fallback requires `OPENAI_API_KEY`, `OPENAI_EXTRACTION_MODEL`, explicit
`--enable-llm` and `--llm-config-version`. No model is hard-coded. Missing settings
leave deterministic processing available. Requests use bounded evidence, strict
structured output, no retries and `store=False`; prompt/schema/model/config/input
fingerprints and returned model are retained. After deterministic PDF extraction,
coverage is checked per required concept and period. Missing supported inputs
trigger configured fallback when relevant evidence exists, even when other
deterministic facts succeeded. Up to four relevant pages/40000 characters are sent,
prioritizing the company statement and tables with supported scope/year headers.
The selected input is retained with model output.
Located candidates must pass independent excerpt, row-label, value-column,
period, currency/scale and company-scope verification against persisted OCR/native
layout. Wrapped labels can be verified through a bounded row span. Four-column
group/company tables require explicit entity headers; a group value cannot be
borrowed for company scope. Qualified parenthesized balance-sheet creditors retain
their raw token and an explicit deduction-presentation normalization to a positive
liability amount. Ambiguous layouts fail closed.

Candidate decisions are retained in a versioned admission artifact with AVAILABLE,
VALIDATION_FAILED or EXTRACTION_FAILED. Provider failure, missing configuration,
empty/malformed output and rejected candidates do not discard valid deterministic
facts. Supported financing/asset components remain source-only; model output never
authorizes completeness or a new canonical derivation. The frozen contract
explicitly requires design approval for any TOTAL_ASSETS component derivation.

## Limitations and interpretation

Supported XML is inline XBRL, not an arbitrary standalone XBRL/taxonomy engine.
The default taxonomy registry is FRC 2024 only. PDF tables require supported
headings, explicit dates/currency and two reporting-year columns. Located fallback
also checks bounded wrapped labels and explicit four-column group/company tables.
Ambiguous labels, unverified notes completeness and other layouts remain unresolved.
OCR recognition is not M4 validation. All source amounts need later validation.

The SQL-only readiness utility reports all 11 variables, source coverage, events,
financial inputs, explicit missingness and document outcomes. Input presence is
not a claim of comparability or full historical coverage. It performs no ratios,
trend, governance scoring, reliability, beliefs, ER, final assessment or UI work.

## Verification on 2026-09-29

Focused M3: 40 passed. Full regression: 334 passed, no failures, skips or warnings.
`pip check` and `git diff --check` passed. Git may print its existing LF/CRLF
conversion notices; no whitespace errors were reported. Changed-file scanning
found no local credential values. `.env` remains ignored, untracked and unchanged.
HEAD remains the frozen baseline; no staging, commit or push was performed.

Real PIP & NUT LTD (08624397), assessment date 2026-09-29, reused M2 Turso inputs.
The initial run `m3-pipnut-first-20260929T135849` considered three accounts filings:
all advertised PDF only. Three metadata responses, three PDFs and three OCR
artifacts were published and verified. Parser v1 failed on statement-scope/layout
handling; this failed history remains intact. Versioned corrections were tested,
then existing PDFs/OCR were reused, not downloaded or OCR-processed again.

Final parser run `m3-pipnut-v3-20260929T141914` reached three candidate periods from
two documents. It produced 24 source occurrences: 12 company and 12 consolidated
occurrences, with the latter excluded from company canonical mapping. It linked
24 canonical observations: 12 AVAILABLE/DIRECT and 12 NULL/EXTRACTION_FAILED.
The four newly created artifacts were two parse and two canonical outputs.
The two filed PDFs plus those four outputs passed checksum verification; stored
metadata was separately verified. Foreign-key checks found no violations.

| Period end | Current assets GBP | Inventory GBP | Net assets GBP |
| --- | ---: | ---: | ---: |
| 2025-12-31 | 11381830 | 3273856 | 1083960 |
| 2024-12-31 | 6984410 | 1854769 | 217942 |
| 2023-12-31 | 6342805 | 1212466 | 386055 |

These are OCR-derived source observations awaiting M4 validation, not validated
financial conclusions. The 2024 observations occur in both filings with equal
values; separate evidence is retained. No differing-value company conflict was
observed among these admitted figures. Company statements are on page 14 of
`d-285f3e670c3a47bbbf0491b1406ad99a` and page 13 of
`d-10cea2fd7267459cb2e6ea88fb8271b7`. Current liabilities were not established by
supported exact row-label/layout rules. No direct total-assets amount or approved
complete derivation was established. Debt disclosure completeness was not
established. All three remain NULL/EXTRACTION_FAILED in every candidate period;
this does not claim the filings omit them. Both documents and the run are PARTIAL.

Immediate reuse run `m3-pipnut-v3-reuse-20260929T142122` was likewise PARTIAL. Both
document outcomes show raw and parse reuse. Its lineage links two OCR, two parse
and two canonical COMPLETE jobs. No download, OCR or OpenAI operation repeated;
no financial/source/artifact duplicates were added. Before/after database totals:

| Table | Before | After |
| --- | ---: | ---: |
| raw_evidence | 22 | 22 |
| financial_source_fact | 32 | 32 |
| financial_observation_lineage | 16 | 16 |
| accounts_processing | 14 | 14 |
| fact (M1/M2/M3 combined) | 502 | 502 |

Totals retain earlier parser history and are not current-run output counts.
New orchestration runs/membership/outcomes are expected audit records. OCR was
required and used in the original acquisition. OpenAI was not invoked; no model
was selected for the smoke. Deterministic partial results were retained honestly.

Full local human-readable reports (ignored, not fixtures):
`data/m3/pipnut-v3-readiness.md` and `data/m3/pipnut-v3-reuse-readiness.md`.
They cover all 11 variables, underlying M2 facts/events, financial observations,
missingness, source locators and document outcomes. PSC Statements remains the
pre-existing M2 retrieval failure; no M2 ingestion was repeated.

Proposed future commit message, only after human approval:
`M3: add accounts document and financial fact ingestion`.

## Targeted fallback correction

Human review identified missing fallback after partial deterministic success. The
PDF route previously returned as soon as any deterministic result existed, and
the original smoke did not enable/configure the optional model. The correction
retains the same repositories, coordinator, cache, schema and dependencies.

`service.py` now checks required concept/period coverage before returning. When
supported inputs are missing and relevant evidence exists, explicitly configured
fallback is attempted. `fallback.py` bounds selection and independently checks
located candidates. `models.py` records per-candidate decisions; `llm.py` supplies
the structured locator/scope/value schema and retains the exact bounded input.
The admission artifact is fingerprinted separately from the provider response:
admission-only changes can reuse model output. Failed/unresolved complete responses
are cached too. Optional-provider failure never invalidates deterministic facts.

Offline correction verification: **57 focused M3 tests; 351 full regression tests
passed**, with no failures/skips/warnings. Cases cover complete deterministic input
without a model call; partial-success fallback; numeric/date/scope/currency support;
rejected/unresolved candidates; provider/configuration failure; repeat-call avoidance;
explicit pound-symbol unit normalization; repeated group/company year headings;
source-only components; and rejection of assets-less-liabilities as total assets.
Maturity-qualified component labels require the nearest explicit creditor-section
heading. A rejected component is recorded as VALIDATION_FAILED in the candidate
audit; it is not a rejected canonical-total candidate. Without an approved total
derivation or complete debt population, the canonical total remains
NULL/EXTRACTION_FAILED. No rejected model value is written into a canonical value.

The correction's model choice is an explicitly authorized test-process setting,
not an application default. Production selection remains `OPENAI_EXTRACTION_MODEL`;
`.env` is not edited. No new dependency or migration was introduced by this correction.

### Corrected PIP & NUT verification

Requested/returned model: `gpt-5.6-luna`, supplied only to the smoke process.
Four OpenAI requests occurred in total: two initial requests and two with corrected
evidence selection. Initial pound-symbol unit rejections and the earlier evidence
selection remain in immutable history. Admission-only corrections reused the stored
model responses; every unchanged repeat made zero new API calls. Downloads and OCR
were explicitly blocked throughout this correction.

Final bounded inputs were pages **14, 32, 17, 18** (9710 characters) of the latest
filing and **13, 29, 16, 17** (8854 characters) of the prior filing. Targets were
CURRENT_LIABILITIES, TOTAL_ASSETS and INTEREST_BEARING_DEBT. The deterministic
CURRENT_ASSETS, INVENTORY and NET_ASSETS observations were retained unchanged.

Admission v3 replay: `m3-fallback-v3-first-20260929T152250`.
Unchanged repeat: `m3-fallback-v3-reuse-20260929T152340`.
Both finished PARTIAL; neither required a new model call. Of 26 returned candidates,
19 passed (four direct current-liability occurrences and 15 source-only components),
six failed evidence/label admission and one had no supported numeric value. Source
components do not become canonical totals. Rejected unlabeled-subtotal candidates
were retained in the audit; the investment dash did not become zero.

Verified current liabilities: GBP 10583194 at 2025-12-31, GBP 6553584 at 2024-12-31
(both filings retain separate evidence), and GBP 5400694 at 2023-12-31. These are
DIRECT canonical observations with method LLM_OCR_TEXT after deterministic admission.
The latest filing's supported source-only financing components include:

| Component | 2025 GBP | 2024 GBP |
| --- | ---: | ---: |
| Invoice discounting facility | 3879902 | 1753608 |
| Other loans, within-one-year table | 517058 | 433587 |
| Other loans, after-one-year table | 548309 | 918080 |

No completeness assertion was made from that list. TOTAL_ASSETS and
INTEREST_BEARING_DEBT remain NULL/EXTRACTION_FAILED in every candidate period.
At that verification point TOTAL_ASSETS derivation needed explicit design approval
(subsequently granted in the addendum below). Debt aggregation remains
blocked by unestablished completeness. F1.2/F2.2/F2.3 now have inputs present,
subject to M4 review; F1.1 and F3.1 remain missing required totals. No ratios or
risk/ER calculations were performed.

Final unchanged-repeat before/after counts: raw_evidence **38/38**,
financial_source_fact **66/66**, financial_observation_lineage **24/24**,
accounts_processing **30/30**, all-M1/M2/M3 fact **538/538**. These include retained
version history. Foreign-key violations: zero. Both document outcomes confirm
raw and deterministic parse reuse.

Ignored local artifacts: `data/m3/pipnut-fallback-final-reuse-readiness.md`,
`data/m3/pipnut-fallback-final-audit.json`, and
`data/m3/pipnut-fallback-candidate-verification.md` (every candidate and decision).
The original PDF and OCR/model artifacts remain in R2; no raw source text was
printed during verification. `.env` remained byte-for-byte unchanged. Nothing was
staged, committed or pushed.

## Historical narrow completion addendum (superseded by final amendment)

The user explicitly approved `complete-four-component-asset-side-v1`:

`TOTAL_ASSETS = INTANGIBLE_FIXED_ASSETS + TANGIBLE_FIXED_ASSETS + INVESTMENTS + CURRENT_ASSETS`.

`asset_side.py` recognizes only the supported Company balance-sheet structure in
verified persisted PDF layout. Each required component must have an explicit
amount in the same reporting-year column. The three fixed components must exhaust
the section and reconcile to its printed subtotal; the current-assets section
must contain no unknown labelled asset categories. A separately supported printed
current-assets total supplies the fourth component. Missing/dash amounts, unknown
rows, ambiguous columns, scope/date/unit differences or subtotal mismatches block
derivation. No Group substitution or missing-as-zero convention is introduced.

Supported components remain source observations even when the completeness gate
fails. A successful total is DERIVED, with ordered source-fact edges, exact formula,
rule version and an additional source reference retaining the complete asset-side
excerpt and page/row locator. SQL repositories only persist/check relational
lineage; object verification remains with the existing coordinator.

The new completeness PARSE artifact is independently versioned and canonical
fingerprints include the asset rule. Existing OCR and model-response fingerprints
are unchanged. Completed prior artifacts and migrations are not rewritten.

Debt retains `complete-interest-bearing-sum-v1`: an explicit exhaustive
interest-bearing schedule with admitted, non-overlapping Company components is
required. Keyword matches and several financing rows cannot establish accounting
completeness. The retained completeness audit records examined category/page
coverage and missing population evidence; keyword absence is never absence proof.

The latest Company balance sheet (page 14) and prior Company balance sheet
(page 13) do not contain the required intangible-assets row in supported OCR.
The latest consolidated balance sheet does contain an intangible-assets row.
The supplied acceptance value therefore cannot authorize a Company total under
the four-component rule. Source clarification is needed; the implementation does
not infer a zero or combine Group and Company figures to reach that value.

Completion runs `m3-completion-first-20260929T162423` and
`m3-completion-reuse-20260929T162517` both finished PARTIAL. TOTAL_ASSETS and
INTEREST_BEARING_DEBT remain NULL/EXTRACTION_FAILED for 2025, 2024 and 2023.
Seven additional supported asset-component occurrences were retained; all four
previously available canonical concepts retain their values. Financing rows are
source-supported candidates, not an admitted exhaustive interest-bearing population.
No category's absence was inferred from a missing OCR keyword. Interest-bearing
classification and exhaustive Company/period coverage remain unestablished under
the supported deterministic gate; net-debt headings do not resolve this.

Both runs reused persisted model responses, OCR and original documents. New
OpenAI calls, OCR runs and document downloads: **0 each**, enforced by rejecting
guards. The unchanged repeat added no raw artifacts, processing records, source
facts or canonical facts (counts respectively 44, 36, 73 and 546; canonical
lineage rows 24). Foreign-key violations: zero. `.env` was unchanged.

Verification: **68 focused M3 tests; 362 complete regression tests passed**, with
no failures, skips or warnings. `git diff --check` passed. The ignored local
`data/m3/pipnut-completion-reuse-readiness.md` and `pipnut-completion-audit.json`
retain current-run readiness, all component identifiers, periods, page locators,
completeness reasons and cache reuse. No ratios, risk scores or ER beliefs were
calculated. No commit or push was performed.

## Final approved semantic/dynamic amendment (2026-09-29)

The authoritative M3 contract now supersedes the universal four-component asset
assumption. Canonical vocabulary and the frozen risk model are unchanged. Source
terminology remains independently stored. Approved deterministic mappings take
priority, followed by context-grounded semantic proposals; ambiguity stays unresolved.

`models.py` defines immutable contextual evidence, grounded operands, completeness
proofs, structured normalization/derivation proposals and admission decisions.
`interpretation.py` checks copied source identity/label/value/locator, Company scope,
instant/date, currency/unit, known mappings, unique operands and the supported
accounting relationship. Python evaluates bounded Decimal expressions; no model
code or result is executed. The arithmetic evaluator supports four operations,
but current accounting gates authorize only certified population sums and their
supported subtraction cross-checks. Divide by zero/inexact division is rejected.

`asset_side.py` locates complete fixed/non-current plus current asset sections.
It can use a printed fixed subtotal or all independently resolved displayed fixed
components; no particular child category must exist. An unresolved child does not
become zero. A separately printed subtotal may still support the aggregate.
Unknown structures, overlap and contradictory totals fail closed. Reported assets
less current liabilities is retained as a source cross-check, never normalized to
TOTAL_ASSETS. An available contradictory cross-check rejects the proposed total.

Debt completeness is separate from arithmetic and financing classification. A
source-explicit exhaustive Company interest-bearing schedule can admit varying
component labels/populations; ordinary trade creditors, taxes, accruals, payables,
charges and mixed/subtotal populations are excluded. Isolated loan rows remain
source facts without a canonical total. Source headings and numeric coverage,
not LLM assertions, establish the supported completeness proof.

`interpretation_workflow.py` first records deterministic decisions, then optionally
requests bounded context-supported unresolved proposals. A missing debt completeness
proof does not trigger another model call to force a total. `llm.py` exposes an
optional separate structured proposal request using the existing official SDK,
configuration and durable cache. Prompt/schema versions are distinct from existing
extraction versions, so old extraction responses remain reusable. Full model
metadata and input/output remain in verified R2 artifacts. Rejections retain
source facts and proposals.

Migration **005** adds an immutable, queryable relational admission ledger linked
to document/source/canonical identities and R2 interpretation/model artifacts.
Derived formulas and ordered component edges use the existing relational lineage.
SQL repositories remain independent of object storage. Applied migrations 001–004
are unchanged. No additional dependency was introduced by this amendment.

Current coverage is deliberately bounded: known taxonomy mappings, verified PDF
Company statements, qualified maturity rows under Creditors, explicitly contextual
subtotal terminology, recognized asset-side structures and source-explicit exhaustive
debt schedules. Unsupported taxonomy semantics/layouts and ambiguous accounting
relationships remain unresolved. This is not a general accounting ontology.

### Final amendment acceptance

Final runs: `m3-amendment-first-20260929T170314` and
`m3-amendment-reuse-20260929T170412`, both PARTIAL. Structure parser
`financial-statement-structure-v3`; admission/plan `financial-interpretation-v1`.

Company TOTAL_ASSETS at 2025-12-31 is **GBP 12,232,894**, DERIVED from printed
fixed assets **851,064** plus current assets **11,381,830**. Its source cross-check
passes: subtract current liabilities **10,583,194**, giving reported assets less
current liabilities **1,649,700**. Full operand, completeness and cross-check evidence
links are retained; this is deterministic, not an LLM-calculated value.

At 2024-12-31 two filing occurrences independently yield **GBP 7,689,606**:
the latest uses fixed assets **705,196** plus current assets **6,984,410**; the
prior uses tangible assets **705,096**, investments **100** and current assets
**6,984,410**. Both cross-check to **1,136,022** after current liabilities
**6,553,584**. This demonstrates different supported source structures.

2023 remains NULL/EXTRACTION_FAILED for TOTAL_ASSETS: the prior filing has an
unresolved investment amount and no admitted printed fixed subtotal. No zero or
inverse accounting-equation shortcut was inferred. Debt remains
NULL/EXTRACTION_FAILED for all three years because the retained financing rows
do not establish an exhaustive Company interest-bearing population.

Readiness: F1.1 inputs present for 2025/2024, incomplete for 2023; F1.2 has three
candidate periods; F2.2/F2.3 inputs are present in each period; F3.1 lacks debt in
every period and assets in 2023. M4 suitability/comparability remains undecided.
No ratios, risk scores or ER beliefs were calculated.

**92 focused M3 tests and 386 full regression tests passed**, no failures, skips
or warnings; `git diff --check` passed. Zero new OpenAI requests, OCR runs or
document downloads, enforced by rejecting guards. Existing extraction LLM
responses were reused. The optional new semantic-provider path was exercised
offline with mocked SDK responses, not a live API call.

Final repeat counts are unchanged: raw evidence 58, source facts 99, canonical
lineage 30, processing records 50, all-stage facts 562, interpretation decisions
38 (including retained version history). Foreign-key violations: zero. Detailed
ignored reports: `data/m3/pipnut-amendment-evidence.md`,
`data/m3/pipnut-amendment-reuse-readiness.md`, and
`data/m3/pipnut-amendment-audit.json`. `.env` remains unchanged and ignored;
nothing was staged, committed or pushed.

## Provider references

- [Companies House Document API](https://developer-specs.company-information.service.gov.uk/document-api/reference/document-location/fetch-a-document)
- [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [FRC 2024 taxonomy archive](https://www.frc.org.uk/documents/6566/FRC-2024-Taxonomy-v1.0.0_GJp67Do.zip)
