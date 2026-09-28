# Evidence-Grounded AI Risk Intelligence

An AI-assisted risk intelligence prototype that combines automated document ingestion, structured data extraction, evidence validation, data provenance, and explainable risk assessment.

## Core idea

**Source → Evidence → Structured Fact → Validation → Risk → Explanation**

## Status

M0 foundation and domain contracts implemented; awaiting human review.
No live ingestion, persistence adapters, scoring engines or UI are implemented.

## Local development (Python 3.12)

Use the existing project-local `.venv`. For a fresh checkout, create it with
`py -V:3.12 -m venv .venv`. From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe examples\inspect_contracts.py
```

The example prints clearly labelled synthetic records constructed with the actual
models. It performs no retrieval or risk calculation. Tests need no credentials
or external services. M0 depends only on Pydantic at runtime and pytest for tests.

`risk_intelligence.config.load_settings()` reads environment variables explicitly;
it does not load `.env` files, create directories or connect to services.
`.env.example` lists safe placeholders. Credentials are optional and excluded
from settings serialization and representation. Service-specific Turso/R2
configuration belongs to M1; the unused generic `DATABASE_URL` placeholder has
been removed.

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
