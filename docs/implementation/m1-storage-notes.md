# M1 storage implementation notes

Status: implemented, awaiting human review. These notes describe the approved
hybrid implementation; they do not change the frozen dictionary or authorize M2.

## Scope and repositories

The physical schema contains company, processing_run, source, document,
raw_evidence, evidence_reference, fact, fact_evidence, assessment and
schema_migration. Validation/reliability, variable and ER tables remain deferred
to M4/M5/M6. AssessmentService is still a protocol with no implementation.

Concrete adapters:

| M0 port | M1 adapter |
| --- | --- |
| CompanyRepository | SqlCompanyRepository |
| RecordRepository[Source] | SqlSourceRepository |
| RecordRepository[Document] | SqlDocumentRepository |
| RecordRepository[RawEvidence] | SqlRawEvidenceRepository |
| RecordRepository[EvidenceReference] | SqlEvidenceReferenceRepository |
| RecordRepository[StructuredFact] | SqlStructuredFactRepository |
| RecordRepository[FinancialFact] | SqlFinancialFactRepository |
| AssessmentRepository | SqlAssessmentRepository |
| EvidenceStorage | LocalStorage / R2Storage |

Document and raw repositories are low-level relational APIs with no EvidenceStorage
dependency. They enforce local provenance, immutable identity and SQL constraints;
they cannot prove object existence. Application publication MUST use
EvidencePersistence.save, which validates identity, stores bytes, reads and verifies
them, and only then opens the atomic source/document/raw metadata transaction.
The coordinator rejects calls inside an existing managed Database.transaction.
Direct repository writes (or raw SQL) can bypass byte verification and are not
an application publication API. No capability or distributed-transaction framework
is introduced. Company and processing
run context must already exist. Failed source attempts may be saved without raw
objects and linked to unavailable facts without invented evidence references.

## Database and migrations

Normal development uses standard-library SQLite. Production uses the official
`libsql` driver in remote mode, without a replica or sync. The newer Turso engine
and its different drivers are not selected. Database owns one connection, is
single-threaded, enables/verifies foreign keys and closes explicitly. Nested
repository operations join the outer transaction; failed operations make it
rollback-only. SQL values are parameterized and provider error messages are
sanitized to avoid exposing credentials or evidence content.

From the repository root:

```powershell
.venv\Scripts\python.exe -m risk_intelligence.persistence.migrations
```

This uses load_settings(), which reads the process environment, not `.env` files.
With defaults, it creates only the ignored local `data/metadata.sqlite3` file.
Library callers may use `open_sqlite(path)` and `migrate(database)` explicitly.
Imports do neither. Connections created through `open_sqlite` do not create
missing parent directories.

SQL files live in persistence/migrations and are included in the Python package.
Versions are contiguous, numbered from 001. The migration ledger records version,
filename, SHA-256 and UTC application timestamp. Migration checksums normalize
CRLF to LF before hashing UTF-8 SQL, so Windows/Linux Git checkout policy does not
cause false drift. Actual edited content is rejected. A newer database version
is rejected. Pending migrations and ledger writes share one transaction; there
is no automatic downgrade. Schema updates are an explicit operational action.

## Exact representation and integrity

- Decimal is TEXT using `str(Decimal)`, restored with Decimal, with no float or
  SQL REAL step. Digits, trailing zeros and exponent survive.
- Calendar dates use YYYY-MM-DD. Aware datetimes normalize to UTC and use a
  fixed six-digit fractional second followed by Z.
- Enums store their exact M0 value. Booleans use constrained INTEGER 0/1.
- Missing typed fields are SQL NULL with AvailabilityStatus. NON_COMPARABLE
  source values remain present. Candidates occupy separate columns.
- Structured and financial facts share one identity table with record_kind and
  fact_type discriminators. Financial context uses relational columns.
- Code tuples use JSON arrays only; whole records are never JSON blobs.
- Locator variants use explicit columns. Evidence links preserve tuple order,
  including repeated IDs allowed by the M0 tuple contract.
- Restored records are validated, not silently repaired. Database CHECK/FK
  constraints and repository checks protect record and provenance integrity.

Evidence must link to the raw response for its source. Each retrieval source has
at most one raw payload. Separate pages/downloads need separate source IDs.
Documents, sources and runs cannot cross company identities. Fact evidence may
include corroborating sources for the same company. Reprocessing may use evidence
from prior runs. `fact_ids_for_evidence()` provides reverse lookup;
`get_for_source()` resolves raw metadata. Indexed SQL joins expose the remaining
source/document/fact path without a generic query framework.

Evidence records and assessment snapshots are append-only. Same identity and
identical serialized values are idempotent; conflicting saves fail. SQL triggers
also reject update/delete of historical tables. Company is a mutable current
profile with immutable identity; historical reasoning must use preserved evidence
and facts. Processing runs may change lifecycle fields while active, but identity,
start context and app version remain fixed. Finalized runs cannot be rewritten.

## Immutable raw objects

The key convention is:

```text
raw/v1/{company_number}/{source_type}/{UTC_YYYYMMDDTHHMMSSffffffZ}/{source_id}/{sha256}.{extension}
```

The source model supplies canonical company number, controlled source type and
retrieval timestamp. Safe portable components are required; IDs containing path
characters or Windows reserved names fail explicitly. Extensions come from a
small controlled media-type mapping. No current clock participates in key creation.

SHA-256 covers exact supplied bytes before parsing/transformation. Checksum and
media type live in raw metadata, with matching document pointers where supplied.
Size is derived from bytes/R2 content length; the M0 RawEvidence model is unchanged.
Source retrieval time is distinct from filesystem/R2 upload time.

LocalStorage writes and fsyncs a temporary file, verifies it, then publishes a
same-filesystem hard link without replacement. Temporary names are operational
only and do not affect deterministic final identity. POSIX directory descriptors
use no-follow access. Windows directory handles reject reparse points and deny
rename/deletion while in use. Final files are opened without following links.
Unsupported hard-link filesystems fail explicitly, without unsafe fallback.

R2Storage uses an injected minimal S3 client and conditional PUT (`IfNoneMatch='*'`).
An existing key is read and compared before accepting an identical retry.
Content-Type and SHA-256 user metadata are supplied. ETag is not treated as SHA-256.
GET validates content length. Metadata-aware EvidencePersistence.read recomputes
SHA-256. NoSuchKey becomes FileNotFoundError; access, bucket and transport failures
become StorageAccessError. Integrity failures remain distinct.

Separate retrieval events retain separate source/raw metadata and event keys,
even with identical content. No content-deduplication catalogue exists. An explicit
new metadata reference to existing bytes remains technically possible through
low-level repositories, with verification the caller's responsibility; this is
not the application publication path. The coordinator requires event-specific identity.

Write order is object -> read/verify -> SQL metadata transaction. Upload failure
creates no successful object metadata. SQL failure can leave an orphan object,
retained for retry. No distributed transaction, queue, garbage collector or deletion
API exists. Application immutability does not prevent an administrator from editing
the bucket/filesystem directly; subsequent verified reads detect byte corruption.

## Configuration and dependencies

| Variable | Meaning |
| --- | --- |
| RISK_ENVIRONMENT | development / test / production |
| RISK_LOCAL_DATA_DIRECTORY | Local root; default data |
| RISK_DATABASE_BACKEND | sqlite (default) / turso |
| RISK_EVIDENCE_STORAGE_BACKEND | local (default) / r2 |
| TURSO_DATABASE_URL | Secure libSQL endpoint, required for turso |
| TURSO_AUTH_TOKEN | Required for turso |
| R2_ACCOUNT_ID | Required for r2; standard endpoint derived from account |
| R2_BUCKET_NAME | Required for r2 |
| R2_ACCESS_KEY_ID | Required for r2 |
| R2_SECRET_ACCESS_KEY | Required for r2 |

Production requires both cloud backends and their configuration. There is no silent
local fallback or ambient AWS credential discovery. URL/token/key fields are hidden
from settings repr/serialization. Existing Companies House/OpenAI fields remain
unused and optional. Never put real credentials in Git, fixtures or reports.

M1 adds pinned libsql 0.1.11 and boto3/botocore 1.43.103. libsql provides the intended
database driver; boto3 provides S3 requests; botocore is also pinned because its
configuration, error and testing APIs are used directly. No ORM, migration framework
or cloud abstraction framework was added.

## Acceptance checks and M2 handoff

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe examples\inspect_storage.py
git diff --check
```

Tests use temporary SQLite/local roots, synthetic records, real libSQL in-memory
dialect checks, and boto3 Stubber/fakes. Normal M1 tests block Python socket connects.
The synthetic executable reports company, exact Decimal, NULL/status, byte equality,
checksum lineage, overwrite rejection and reverse evidence-to-fact links. It uses
temporary resources and makes no network calls.

Cloud integration was not required for M1 acceptance and is not included in normal
pytest. No live cloud test is run automatically. A later explicitly authorized
cloud smoke check must use isolated test resources, require explicit opt-in, and
skip when credentials are absent; production resources must never be test defaults.
Offline driver/stub tests do not establish actual cloud credentials, network or
service configuration. Local POSIX code requires a Linux execution check before
claiming cross-platform local-storage verification.

M2 can rely on migrations, immutable byte storage, processing runs, typed source/
document/fact repositories and reverse provenance. M2 still owns source requests,
pagination, identity resolution, normalization and missing-field interpretation.
M1 contains no Companies House client, parser, OCR, OpenAI calls, validation/
reliability/risk/ER engines, UI or deployment.

Human review is required before staging/commit/push or progression to M2.
