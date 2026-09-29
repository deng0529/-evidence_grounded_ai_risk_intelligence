# M2 - Companies House API Evidence Ingestion

The approved 29 September 2026 M2 execution requirements supersede the older
governance-only scope below. The implementation covers company-name/number
resolution, Profile, Officers, PSC, PSC Statements and window-complete Filing
History with explicit per-resource reuse/completeness/freshness. Charges and
additional reference-company seeding are excluded. The real closure company is
PIP & NUT LTD (08624397). See [M2 implementation notes](m2-ingestion-notes.md)
for current contracts, verification and the M3 boundary.

## Original milestone context

## Objective

Retrieve and normalize governance evidence from Companies House for the
three reference companies. Do not calculate risk.

## Required sources

-   Company profile
-   Officers
-   Persons with Significant Control
-   Filing history
-   Charges where useful as supporting evidence

## Implement

-   Companies House client with controlled retries/timeouts/errors.
-   Raw JSON persistence before transformation.
-   Company identity resolution by company number.
-   Filing-event normalization.
-   Director records/events.
-   PSC/control records/events.
-   Source/document/evidence metadata and locators.
-   Controlled failure statuses.

## Reference companies

-   LODI UK LIMITED - 05127466
-   WESTPOINT HOMES LIMITED - SC137690
-   PIP & NUT LTD - 08624397

## Do not implement

-   Governance risk scores.
-   LLM extraction.
-   Silent inference of missing dates.
-   Treat absence as zero.

## Acceptance criteria

-   Raw responses are traceable to normalized records.
-   Re-running does not destroy prior retrieval provenance.
-   Missing/retrieval failures produce controlled statuses.
-   Tests use fixtures/mocks and do not require live API access for the
    normal test suite.
