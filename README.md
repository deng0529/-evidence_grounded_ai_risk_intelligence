# Evidence-Grounded AI Risk Intelligence

An AI-assisted risk intelligence prototype that combines automated document ingestion, structured data extraction, evidence validation, data provenance, and explainable risk assessment.

## Core idea

**Source → Evidence → Structured Fact → Validation → Risk → Explanation**

## Status

M0 foundation is committed. M1 persistence and immutable evidence storage are
implemented and awaiting human review. No ingestion, scoring engines or UI are
implemented; M2 has not started.

## Local development (Python 3.12)

Use the existing project-local `.venv`. For a fresh checkout, create it with
`py -V:3.12 -m venv .venv`. From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe examples\inspect_contracts.py
.venv\Scripts\python.exe examples\inspect_storage.py
```

The example prints clearly labelled synthetic records constructed with the actual
models. The storage example uses a temporary SQLite database and local raw files,
checks exact Decimal/NULL/byte round trips and provenance, then removes its temporary
directory. Neither example retrieves data or calculates risk. Normal tests are
offline and need no credentials or external services.

`risk_intelligence.config.load_settings()` reads environment variables explicitly;
it does not load `.env` files, create directories or connect to services.
`.env.example` lists safe placeholders. Local SQLite/filesystem defaults require
no credentials. Turso/libSQL and R2 require explicit configuration; production
rejects local backends. Secrets are excluded from representations and serialization.

Run migrations explicitly after configuring the desired backend:

```powershell
.venv\Scripts\python.exe -m risk_intelligence.persistence.migrations
```

With local defaults this creates `data/metadata.sqlite3`; it does not contact
Turso or R2. Imports never create a database or run migrations. Read the
[M1 storage notes](docs/implementation/m1-storage-notes.md) before cloud configuration.

See [M0 contract review notes](docs/implementation/m0-contracts.md) for record
invariants, serialization, interfaces and decisions requiring human review.

## Planned stack

- Python
- Companies House public data/API
- Official company websites
- Turso for structured relational data
- Cloudflare R2 for immutable raw evidence/object storage
- Local filesystem raw-evidence adapter behind storage interfaces for development
- Streamlit Community Cloud for the Python application and UI
- FastAPI deferred from the MVP
- OpenAI API for selected AI tasks
- pytest
- Git/GitHub

## Repository documentation

- `PROJECT_SPEC.md` — product requirements and MVP scope
- `ARCHITECTURE.md` — system architecture
- `AGENTS.md` — Codex development instructions
- `docs/` — detailed design documents

## Important limitation

This is a research/prototype system. It is not a regulated credit rating, investment recommendation, legal opinion, or compliance determination.
