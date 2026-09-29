# M2 Companies House API evidence ingestion

This implements the approved M2 execution requirements (29 September 2026).
They supersede the earlier narrower governance-only milestone scope. M1 remains
the immutable evidence/relational persistence foundation; no methodology changed.

## Compatibility gate

- Company.company_number is canonical, unique SQL TEXT. Existing company IDs are reused.
- ProcessingRun and immutable Source/RawEvidence/Fact identities preserve snapshots.
- StructuredFact.subject_identifier distinguishes appointments, PSC resources and
  filing transactions; no (company, concept) uniqueness collapses populations.
- API JSON uses Source + RawEvidence + ApiLocator without a fabricated PDF Document.
- Migration 002 adds ingestion_run (frozen date/parser version), resource_snapshot
  (scope/completeness/freshness/reuse), api_response (safe HTTP metadata), and
  company_search_evidence (raw search responses before a company is selected).
- Migration 001 is unchanged. Historical M1 tests explicitly run migration 001;
  M2 tests exercise upgrading existing M1 and the complete schema with libSQL.

## Responsibility and publication

`client.py` owns fixed-host HTTPS Basic authentication, bounded retries and safe
errors. `parsing.py` owns explicit field/type parsing and stable subject identity.
`policy.py` owns per-resource freshness and calendar scope. `service.py` orchestrates
resource reuse/retrieval and publication. `ingestion_repository.py` performs SQL
only. `resolution.py` preserves company search pages and requires explicit
selection when multiple candidates exist; selected numbers still need profile validation.

Every successful resource page is preserved as exact received bytes through M1
EvidencePersistence before JSON interpretation or facts. The immutable raw object
is read back/verified before SQL publication. Source/raw metadata may survive a
later parse/fact failure, but resource_snapshot explicitly remains incomplete.
One page's facts/evidence links publish atomically. A subordinate failure does not
erase successful earlier resources/pages. R2/Turso failures stop the run rather
than masquerading as empty datasets. SQL repositories never access object storage.
Page publication reuses M1 scalar encoders and sends mapped rows through SQLite
json_each parameters to avoid thousands of cloud round trips. These parameters
are expanded into normal typed columns, never retained as opaque record blobs.
Exact retries compare the complete page's records and ordered links; conflicting
page facts are rejected and insertion failures roll back the whole page.

For a brand-new company, profile bytes are published/read back under the final
event key before parsing its name. Only then can the Company/ProcessingRun exist
and EvidencePersistence publish the normal relational lineage. A malformed new
profile may leave a retained orphan object; it creates no invented company/facts.
Search cannot have a company FK before selection, so its dedicated coordinator
verifies raw bytes before inserting standalone search evidence metadata. Search
pages are explicitly paged candidate results, not claimed exhaustive datasets.

## Temporal scope, populations and reuse

Assessment date is caller-supplied and frozen once; the horizon subtracts exactly
36 calendar months (leap days clamp). Filing date bounds are inclusive. Officers,
PSCs and statements retain their full returned populations, including older active
appointments and ceased records. All officer roles are kept. Filing pages stop
after crossing the horizon start; no category filter omits unknown event types.
The boundary page remains exact raw evidence, including older items. Only in-scope
filings become observations. Missing document links do not invalidate events.

Filing early termination relies on Companies House's newest-first ordering,
with observed monotonicity checks. Count changes, duplicate subjects, stalled
pagination, malformed pages and configured page limits produce incomplete results.
The API does not provide a transactional snapshot across pages: unchanged counts
cannot rule out every simultaneous upstream edit. No unsupported delta optimization
is used. Required historical officer/PSC anchors are retained outside the window.

FreshnessPolicy explicitly specifies maximum age independently for all five
resources (default 24 hours, configurable; zero forces refresh), page size and
page bound. Reuse requires the latest attempt to be complete, parser-compatible,
fresh and to cover the requested date range. A newer failure blocks reuse of an
older successful attempt. Only stale/incomplete/missing resources refresh. Moving
to a new assessment day can require new coverage. Reuse records point to the prior
snapshot and retain the original check time, so reuse never rejuvenates evidence.
Follow reused_snapshot_id to its originating run for the facts/pages; do not assume
facts were recopied into the new run. No historical evidence is deleted.

Run IDs must be distinct across orchestrations. Restart failed orchestration with
a new run ID: successful fresh resource snapshots are reused, incomplete resources
refresh. Exact M1 publication of the same supplied retrieval remains idempotent.
HTTP retry is bounded within each request; it does not pretend a later response
is the same immutable event. Failed new-company resolution has no invented company
or run. Existing-company runs finish COMPLETE/PARTIAL/FAILED; infrastructure failure
may leave RUNNING only if Turso itself cannot record terminal status.

## Observations and missingness

Observations use resource-prefixed canonical concepts, for example
OFFICERS_APPOINTED_ON, PSC_NOTIFIED_ON and FILINGS_LINKS_DOCUMENT_METADATA.
All carry subject_identifier, run, source, ApiLocator, fact_evidence and a typed
value/status. Director-only interpretation remains future risk logic. Stable
appointment self links are preferred; the fallback combines officer appointments
link, role and supplied appointment/before date. Missing/ambiguous identity fails
explicitly, never falls back to name or page index.

Absent resignation/cessation dates have NOT_APPLICABLE semantics for unceased
records; a ceased PSC with no supplied cessation date is NOT_DISCLOSED.
Corporate identification fields for individual PSCs are NOT_APPLICABLE.
Other optional absence is NOT_DISCLOSED. appointed_before is source text, never
fabricated into an exact appointment date. Returned booleans remain booleans,
dates are strictly ISO, integer observations use Decimal, and company numbers stay
text. PSC controls remain source codes, never risk conclusions. AVAILABLE denotes
structural usability only. Complete HTTP-200 empty lists have complete snapshots
with item_count=0, no fabricated facts or zero-risk conclusion. HTTP failures
and JSON/type failures remain RETRIEVAL_FAILED and EXTRACTION_FAILED respectively.

Selected compound filing context (annotations, associated_filings, resolutions,
description_values, subcategory) uses explicitly named *_JSON TEXT observations
with exact source locators; original bytes always remain authoritative. Additional
personal data is retained only in private raw evidence, not profiled unnecessarily.
No financial statement numerical facts or risk/reliability/ER output are produced.

## HTTP and security

Uses the standard library; no added dependency. API credentials come through
existing Settings. Transport uses one fixed TLS host, no redirect following,
20-second socket timeout, a 16-MiB response bound, and three attempts by default.
429, transient 5xx and transport failures retry; 401 does not. Retry-After seconds
and HTTP dates are honored within a bounded wait budget; longer waits return a
controlled failure rather than retrying prematurely. These are application policy
bounds, not claims about Companies House service limits.

Only request identity, retrieval UTC, HTTP status, Content-Type, ETag, pagination
and checksums are retained as operational metadata. Request headers, Authorization,
keys and provider exception payloads are not logged or persisted. Normal tests
block sockets and use synthetic fixtures only. Real evidence is never committed.

## Use and verification

Library number entry: `CompaniesHouseIngestion(...).ingest(number, date, run_id)`.
Name entry: `search_companies(...).select(number)` then ingest the selected number.

For an explicitly authorized live operation, supply credentials in the process
environment and invoke (the script does not implicitly read .env):

```powershell
.venv\Scripts\python.exe examples\ingest_company.py --live --company 08624397 --assessment-date 2026-09-29 --run-id YOUR_UNIQUE_RUN_ID
```

The script applies checked-in migrations, ingests, and verifies every referenced
R2 object, coverage page count, fact/evidence lineage and SQL foreign keys. Output
contains safe counts and run IDs, not personal source fields or credentials.
It exits nonzero for incomplete runs. Real smoke data remains in R2/Turso.
An explicit `--allow-statements-not-found` smoke option accepts only the documented
PSC Statements HTTP 404 branch after checking failed-source provenance. It does
not change the stored PARTIAL run, RETRIEVAL_FAILED status, incomplete flag or reuse
eligibility, and does not claim a zero-item population. Authentication failures,
other resource failures and malformed responses still fail the smoke check.

```powershell
.venv\Scripts\python.exe -m pytest tests/m2 -q
.venv\Scripts\python.exe -m pytest -q
git diff --check
```

## Official source contracts consulted

- [API authentication](https://developer.company-information.service.gov.uk/authentication)
- [Developer guidelines](https://developer.company-information.service.gov.uk/developer-guidelines/)
- [Company profile](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/companyprofile?v=latest)
- [Officer list](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/officerlist)
- [PSC list](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/persons-with-significant-control/list)
- [PSC statements](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/persons-with-significant-control/list-statements)
- [Filing pagination](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/filing-history/list)
- [Provider filing-order clarification](https://forum.companieshouse.gov.uk/t/order-of-filings-in-filinghistorylist/391)

These contracts were checked during M2 implementation. M3 document acquisition,
M4 validation/reliability, M5 beliefs, M6 ER and M7 UI remain unimplemented.

## Real acceptance evidence: 29 September 2026

Canonical company 08624397 was retrieved as **PIP & NUT LTD.** (including the
source-supplied final period). Ingestion run
`m2-pipnut-20260929T104358-28b1e518` froze assessment date 2026-09-29 and inclusive
horizon start 2023-09-29.

| Resource | Raw pages | In-scope/population items | Structured observations | State |
| --- | ---: | ---: | ---: | --- |
| Profile | 1 | 1 | 32 | Complete |
| Officers | 1 | 10 | 110 | Complete |
| PSC | 1 | 1 | 14 | Complete |
| PSC Statements | 0 | Unknown | 0 | HTTP 404; incomplete / RETRIEVAL_FAILED |
| Filing History | 1 | 26 | 297 | Window-complete |

The initial strict live entry point correctly exited nonzero with PARTIAL because
PSC Statements returned HTTP 404. Source-availability verification, permitted by
the approved smoke scope, then explicitly tested the documented not-found branch;
it did not reinterpret the response as an empty population or alter completeness.
Real authentication/storage and the other four resources succeeded.

Run `m2-pipnut-reuse-20260929T104936-44b9f30d` demonstrated resource-level reuse:
all four successful resources were reused without new raw objects/facts; only
PSC Statements was retried, again returning 404. Both runs remain PARTIAL honestly.
The explicit observed-availability verification exited successfully and rechecked
all four stored objects' SHA-256 and all 453 fact/evidence edges. The 26 retained
filings include document metadata links for later M3 acquisition; no documents
were downloaded. All data remains in private R2 and Turso, including both run
contexts, ten resource snapshots and failed-source provenance. No real response
body or personal officer/PSC details are stored in Git.

Offline closure checks: 51 M2 tests and 294 total tests passed, with zero failures,
skips or warnings. HTTP 404 remains a source-data limitation for future consumers;
it is not proof that no PSC statements exist. No data-complete assessment is claimed.
