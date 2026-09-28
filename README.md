# Evidence-Grounded AI Risk Intelligence

An AI-assisted risk intelligence prototype that combines automated document ingestion, structured data extraction, evidence validation, data provenance, and explainable risk assessment.

## Core idea

**Source → Evidence → Structured Fact → Validation → Risk → Explanation**

## Status

Early architecture/specification stage.

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
