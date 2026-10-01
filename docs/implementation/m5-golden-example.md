# Current MVP v1.1 golden validation — 1 October 2026

Active authority: `docs/design-docs/risk-model-v1.1.md`. The current run emits
G1.1, G1.2, G2.2, F1.1, F2.2, F2.3 and F3.1 only. Reporting year **2025** is
persisted separately from assessment date **2026-09-29**. Historical results below
remain historical; they do not define the active registry.

## Verified real evidence and outcome

Company PIP & NUT LTD., 08624397. Read-only Turso snapshot (original migrations
001–006) and **57 checksum-verified R2 objects** recovered into a new local bundle.
Current M3 published new v4 source/provenance records and three structured
completeness proofs; existing immutable PDFs, OCR and exact provider-response
fingerprints were reused. No fresh Companies House retrieval, new OCR, new LLM
request, cloud migration or cloud write was needed. The final bundle has **67**
verified original/derived objects. Existing local migrations through 012 apply to
this isolated database only.

Current M4 admitted 2025 NET_ASSETS 1,083,960, CURRENT_ASSETS 11,381,830,
CURRENT_LIABILITIES 10,583,194, INVENTORY 3,273,856 and derived TOTAL_ASSETS
12,232,894 (all GBP). TOTAL_ASSETS has reliability 0.923 from its independent
accounting cross-check; the direct inputs have reliability 0.8075. Consequently
F1.1/F2.2/F2.3 use 0.8075, the minimum required-input reliability. Interest-bearing
debt remains EXTRACTION_FAILED: no exhaustive, correctly scoped total was admitted.
F3.1 remains (0,0,1). No expected numeric values were injected.

M5 values: G1.1=0 days, G1.2=0 days, G2.2=5.933044484144096... years,
F1.1=0.08861026671203069..., F2.2=1.07546266278403287...,
F2.3=0.76611786574072062..., F3.1=NULL. Exact Decimals, individual beliefs,
validation references and typed reasons are in SQL and the JSON, not recomputed
for display. No M6 aggregation is performed.

## Bundle and replay

All paths below are relative to the repository root:

- `data/golden/pipnut-v11-20261001/verified.sqlite3`: final SQL snapshot and results.
- `data/golden/pipnut-v11-20261001/verified.json`: exact final audit export.
- `data/golden/pipnut-v11-20261001/verified.bundle.json`: identities/checksums for all 67 objects.
- `data/golden/pipnut-v11-20261001/evidence/`: immutable original and derived bytes.
- `data/golden/pipnut-v11-20261001/tessdata/eng.traineddata`: verified OCR resource.
- `assessment.sqlite3`, `result.json`: first successful current-processing run;
  retained, not overwritten. `assessment.evidence.json` inventories the 57 R2 objects.

Exact persisted-result replay (no credentials or network):

```powershell
.venv\Scripts\python.exe scripts/run_company_assessment.py --database data/golden/pipnut-v11-20261001/verified.sqlite3 --replay data/golden/pipnut-v11-20261001/verified.json
```

Repeat the pipeline locally into NEW output files; neither destination may exist:

```powershell
.venv\Scripts\python.exe scripts/run_company_assessment.py --company-number 08624397 --assessment-date 2026-09-29 --reporting-year 2025 --run-id pipnut-v11-local-reproduction --snapshot-local-database data/golden/pipnut-v11-20261001/verified.sqlite3 --database data/golden/pipnut-v11-20261001/reproduction.sqlite3 --reuse-m2-run m2-pipnut-reuse-20260929T104936-44b9f30d --max-documents 2 --evidence-directory data/golden/pipnut-v11-20261001/evidence --tessdata data/golden/pipnut-v11-20261001/tessdata --cached-llm-model gpt-5.6-luna --llm-config-version m3-correction-20260929-v1 --verify-evidence-bundle --output data/golden/pipnut-v11-20261001/reproduction.json
```

The model/config identifiers above are taken from the original processing ledger,
not application defaults. `--cached-llm-model` prohibits provider requests even on
cache misses. The current result reuses two complete historical provider outputs;
current deterministic admission checks run over their quoted evidence.

For initial remote recovery use `--snapshot-configured-database` instead of
`--snapshot-local-database`, and add `--recover-configured-evidence`. Configuration
requires the established Turso and R2 variables. Credentials stay in ignored local
configuration; the bundle/CLI never prints them. Ordinary fresh ingestion remains
available through the existing Companies House service, with optional explicit
LLM configuration. Local pipeline reproduction above needs neither service.

## Repairs and boundaries

The working-tree M3 fixes preserve located fallback heading context and version
its admission; current canonical publication persists typed derivation proofs.
M4 now distinguishes derived targets from direct mapping and retains unavailable
placeholders without inventing lineage. Derived semantic deferral requires a
linked supported proof contract; mandatory scope, arithmetic, completeness and
cross-check rules still execute. Missing proof remains an error.

Model-version registries preserve historical v1 replay while v1.1 is the default.
Selected-year filtering also isolates failure reasons/input lineage from unrelated
years. The runner fails on handoff integrity exceptions rather than producing an
apparently successful audit with rejected handoffs. Recovery uses existing storage
adapters and verifies all bytes before reporting success. Replay verifies assessment
identity, reporting year and persisted leaves. Weights/thresholds/belief mathematics
are unchanged; equal domain-child weighting remains metadata for future M6.

The following section is preserved as the historical v1 execution record.

---

# Real-company M5 golden runner

This is an operational example, not a change to the frozen M1–M5 methodology.
The runner stops at the eleven persisted M5 leaves; it produces no ER aggregation
or company score.

## Architecture

`scripts/run_company_assessment.py` supplies configuration and local adapters to
`services/company_assessment.py`. Fresh mode calls the existing Companies House
and accounts ingestion services. Explicit reuse mode selects existing production
M2/M3 runs for the same company and assessment date. Both modes call the existing
financial, governance and obligation validation services, persist an Assessment,
call RiskVariableService, and read the eleven outputs from VariableRepository.
The table and JSON use those persisted outputs without recalculating beliefs.

`services/structured_snapshot.py` can copy the configured structured database into
a new local SQLite database. It validates migration checksums, copies exact SQL
records in a source read transaction, and applies existing later migrations only
to the local copy. It never fetches raw objects or writes to the cloud database.
Use a dedicated database for an example: the frozen M5 service considers all
eligible M4 records in that database, not merely records from this invocation.

Financial service IntegrityError rejections are recorded in `stage_issues`; no
replacement M4 reliability or validated fact is invented. These are operational
handoff failures, distinct from M5's typed missing-input results. Unexpected
execution errors stop the CLI without exposing provider error text. A failed run
may retain partial local records; use a new destination/run ID for another attempt.

## Pip & Nut execution

Company **08624397**, PIP & NUT LTD., was established from
`data/m3/pipnut-amendment-first-readiness.md` and confirmed against persisted company
and ingestion records. Assessment date is **2026-09-29**, matching the reused
production runs; this is not a fresh retrieval as of the execution date.

From the repository root, the actual execution command was:

```powershell
.venv\Scripts\python.exe scripts/run_company_assessment.py --company-number 08624397 --assessment-date 2026-09-29 --run-id pipnut-m5-golden-20260930 --database data/golden/pipnut-m5-20260929.sqlite3 --snapshot-configured-database --reuse-m2-run m2-pipnut-reuse-20260929T104936-44b9f30d --reuse-m3-run m3-amendment-reuse-20260929T170412 --output data/golden/pipnut-m5-20260929.json
```

Snapshot mode refuses an existing destination; JSON export refuses overwrite.
To repeat execution, select new database/output paths and a new run ID. To reproduce
the exact saved table without any credentials or external services, use:

```powershell
.venv\Scripts\python.exe scripts/run_company_assessment.py --database data/golden/pipnut-m5-20260929.sqlite3 --replay data/golden/pipnut-m5-20260929.json
```

Replay verifies all JSON leaves against SQL before printing. The SQL database is
the persisted result; the JSON is an audit export with ingestion/application IDs,
assessment context, exact Decimals, input lineage, reasons and model versions.
The adjacent `.snapshot.json` records source table counts. All are ignored local
artifacts under `data/golden/`.

The cloud source had migrations 001–006. Existing 007–011 were applied only to the
local copy. No Companies House, R2 or OpenAI request was made by this reuse run.

## Observed limitations

The real execution produced eleven leaves: four calculable governance variables
and seven fully Unknown variables. Every belief sum satisfies the frozen tolerance.

- G1.1/G1.2: zero lateness for explicitly observed outstanding obligations not yet
  due (accounts due 2027-09-30; confirmation statement due 2027-08-08).
- G2.1: zero director departure rate. G2.2: median tenure about 5.933044 years.
- G2.3: `NO_COMPUTABLE_WINDOW`. The frozen implementation generates candidate
  windows from departure dates; this population has no departures in its window.
  This is existing behavior, not evidence that the officer population is incomplete.
- G3.1: `INCOMPLETE_POPULATION`; the PSC statements snapshot has `RETRIEVAL_FAILED`.
- F1.1/F2.2/F2.3/F3.1: `MISSING_REQUIRED_INPUT`; F1.2:
  `NON_COMPARABLE_PERIODS`. Sixteen saved financial validations are inadmissible
  because source scope/heading provenance is unresolved. The old direct facts have
  `REVIEW_REQUIRED` comparability. The expected 2025 current assets, current
  liabilities, inventory and net assets values are present, but this does not make
  them admissible M5 inputs.
- Eight additional M4 financial handoffs were rejected: five lack persisted
  canonical lineage; three encounter `Direct deterministic normalization requires
  one source`. Those exact fact IDs and errors are retained in the JSON. Missing
  validated financial inputs here do not prove absence of disclosure by the company.

These limitations are preserved for review. The runner does not backfill source
scope, reconstruct derivation evidence, or modify frozen validation/risk behavior.

## Configuration and tests

The recorded snapshot execution required the existing configured Turso backend,
`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. `.env` is read locally, never printed
or modified, with process environment taking precedence.

Fresh mode omits snapshot/reuse options and requires `COMPANIES_HOUSE_API_KEY`.
It uses local immutable raw storage (`--evidence-directory`). PDF OCR requires
`--tessdata` containing `eng.traineddata`; document redirect hosts must be supplied
explicitly with `--document-download-host`. Optional LLM fallback is opt-in via
`--enable-llm`, requires `OPENAI_API_KEY` and `OPENAI_EXTRACTION_MODEL`, and records
`--llm-config-version`. No model is hard-coded. These optional services were not
exercised by the recorded reuse execution.

Verification: focused M5 tests **68 passed**; full regression **696 passed**.
Four new offline tests cover production service orchestration, persisted replay,
explicit ingestion reuse, exact structured snapshots and invalid input rejection.
Local snapshot integrity and foreign-key checks passed. No frozen production
module, dependency or migration was changed.
