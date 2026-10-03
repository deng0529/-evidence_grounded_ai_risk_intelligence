# Foundation freeze — 2026-10-03, v33

## Accepted boundary
The user accepted the five-company Foundation results and confirmed saved-result reuse works on 3 October 2026. They explicitly authorized freezing and pushing this stage to GitHub. This document supersedes earlier pending-acceptance instructions in CURRENT_HANDOFF.md and historical milestone plans for this phase.

| Company | Companies House number | Acceptance |
| --- | --- | --- |
| LODI | 05127466 | User tested successfully |
| Westpoint | SC137690 | User tested successfully |
| Pip & Nut | 08624397 | User tested successfully |
| Country Style Foods | 02554051 | User tested successfully |
| HP Foods | 02251694 | User tested successfully; Inventory Unknown is supported by the original-report review |

## Frozen behaviour
Companies House APIs supply governance information. The selected accounts filing supplies financial data: complete deterministic iXBRL extraction ends without AI or PDF; partial iXBRL goes to the English financial-expert prompt with the original XHTML and unresolved concepts; absent iXBRL goes to the complete original PDF through OpenAI, including scanned reports. Missing values remain typed NULL with explicit status and reasons. Financial year is a source-selection preference, not an exact-year rejection gate. Extraction coverage shows deterministic, AI-targeted, AI-recovered and final counts.

Default REUSE PERSISTED RESULT reads each company's latest saved Foundation pair independent of today's date. It performs no source retrieval, OpenAI extraction or R2 download and never automatically switches to fresh ingestion. Explicit FRESH END-TO-END remains available for intentional new collection. This freeze does not guarantee future fresh ingestion will retain only one historical run: the authorized maintenance was a one-time cleanup.

## User-confirmed cloud cleanup
The user supplied the successful maintenance output: 74,423 old database rows removed; 667 old indexed R2 objects removed; five companies retained; LATEST_FIVE_RETAINED. The local backup folder ends in data/maintenance/20261003T155724_161025Z. This is user-confirmed execution against their configured Turso/R2, not an independently repeated cloud audit. Unindexed bucket objects were outside cleanup scope. Latest result lineage, raw evidence, missingness, schema migration ledger and original immutable triggers are preserved.

## Verification
The release suite is run offline with synthetic fixtures; live five-company acceptance was performed by the user. No credentials, cloud raw files or local maintenance backups are committed. The frozen repository passed 824 offline tests in 18.96 seconds and staged git diff --check. Tag: foundation-v33-20261003.

## Next authorized boundary
Stop here. On resumption, develop the six variables' High Risk, Low Risk and Unknown belief values, followed by ER fusion. Start with retained structured Turso data; do not rerun the ingestion/extraction pipeline for those tests. Existing historical belief/ER modules are present, but this freeze does not constitute acceptance of next-phase risk results. No deployment or new risk methodology is part of this change.

## Run
From the project root with the configured .env and existing Python 3.12 environment:

```powershell
& ".\.venv\Scripts\python.exe" -m streamlit run ".\streamlit_app.py"
```

Use REUSE PERSISTED RESULT. The maintenance entry point is scripts/retain_latest_foundation.py; it is explicit, destructive and backed up. The accepted cleanup has already completed; do not rerun it during ordinary next-phase testing.
