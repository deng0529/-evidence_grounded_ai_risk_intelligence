# AGENTS.md — Evidence-Grounded AI Risk Intelligence

## Purpose
This repository contains an evidence-grounded AI risk intelligence prototype for SMEs and other organisations. The system ingests public information, extracts structured facts, validates each fact against source evidence, and produces traceable and explainable risk assessments.

## Working principles
1. Inspect the existing repository before changing files.
2. Preserve the architecture unless a change is genuinely required.
3. Keep ingestion, extraction, validation, risk assessment, database access, and UI concerns modular.
4. Never invent, silently infer, or fabricate missing factual data.
5. Every externally sourced factual datum should retain provenance: source, source URL or identifier where available, retrieval date/time, and evidence location.
6. Separate factual extraction from risk assessment. Do not let an LLM directly overwrite source facts with an unsupported risk conclusion.
7. Prefer deterministic validation and scoring rules where practical; use LLMs for extraction, interpretation, and explanation where they add value.
8. Treat source evidence as the basis for every material risk finding.
9. Keep secrets out of source code, Git history, logs, tests, and documentation. Use environment variables and `.env` locally; commit only `.env.example`.
10. Add or update tests when changing behaviour.
11. Do not make unrelated refactors.
12. Update relevant documentation when architecture, schemas, data flow, or important behaviour changes.
13. Before declaring a task complete, run the relevant tests/checks and report what was run and any limitations.
14. Do not commit raw confidential or personal data. Public company data used for the prototype must be handled according to applicable source terms and project policy.
15. For external web/API access, use stable interfaces and record source metadata rather than depending on undocumented behaviour.

## Change protocol
For non-trivial changes:
1. Read this file and the relevant project documentation.
2. Inspect the existing implementation and tests.
3. State the proposed approach before making broad changes.
4. Implement the smallest coherent change.
5. Test it.
6. Update documentation if needed.

## Project documentation
- `PROJECT_SPEC.md` defines the product requirements and MVP scope.
- `ARCHITECTURE.md` defines the system architecture and boundaries.
- `docs/` contains deeper design and product documentation.
- `README.md` is the public-facing project introduction and setup guide.

## Coding preferences
- Prefer clear, maintainable Python over clever abstractions.
- Use type hints for public functions and important data structures.
- Keep functions focused and testable.
- Make external I/O explicit.
- Fail safely when evidence is missing or validation fails.
- Do not hide uncertainty behind confident language.
