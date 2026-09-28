# AGENTS.md — Evidence-Grounded AI Risk Intelligence

## Purpose
This repository contains an evidence-grounded AI risk intelligence prototype for SMEs and other organisations. The system ingests public information, extracts structured facts, validates each fact against source evidence, and produces traceable and explainable risk assessments.

## Scope and authoritative documentation
These standards apply repository-wide to M1–M8 and later maintenance unless a later explicitly approved instruction changes them.

- Inspect the repository and relevant active specifications before implementation. Follow this file and the frozen project specifications; archived/pre-freeze documents are non-authoritative unless explicitly designated otherwise.
- Implement only the authorized milestone. Scope is an engineering constraint: do not silently implement future work, change frozen methodology for convenience, or continue beyond the requested acceptance boundary.
- Preserve the architecture unless a change is genuinely required and authorized. Surface material specification contradictions and stop affected work rather than inventing a resolution.

## Evidence integrity and reproducibility
- Never invent, silently infer or fabricate source data, evidence, facts, validation results or risk results. Source evidence must support every material risk finding; do not hide uncertainty behind confident language.
- Retain provenance for every externally sourced factual datum: source, URL or identifier where available, retrieval date/time and evidence location. Preserve traceability across layers, processing-run lineage and required model/methodology versions. Raw evidence remains immutable.
- Separate extraction from assessment. LLM output is not source truth and must not overwrite source facts, validated values, reliability or risk/ER results. Use LLM assistance for extraction, interpretation and explanation only within approved methodology and milestone scope.
- Missing data is not zero; retrieval failure is not evidence of absence; extraction failure is not a valid fact. Preserve typed `None`/`NULL` plus `AvailabilityStatus`, candidate-value separation and fail-safe behaviour. Never put sentinel strings such as `"UNKNOWN"` in typed value fields. ER Unknown is a belief-layer concept.
- Prefer deterministic validation, transformations, reliability, risk-variable calculations, ER aggregation and tests. Do not introduce randomness without an explicit project requirement.
- Use stable external web/API interfaces, record source metadata and respect source terms and project policy. Do not depend on undocumented behaviour or commit raw confidential or personal data.

## Architecture and side effects
- Keep responsibilities distinct: Source/Evidence → Structured Facts → Validation → Evidence Reliability → Risk Variables/Leaf Beliefs → ER Aggregation → Assessment/Explanation → UI. Keep ingestion, extraction and database access modular; evidence reliability is separate from ER importance weights.
- Give modules clear responsibilities. Avoid monolithic files, hidden coupling, circular dependencies, unnecessary global state and hidden side effects.
- Separate presentation and application orchestration from domain logic. Streamlit calls application/service boundaries; it must not contain ingestion, validation, reliability, risk or ER business logic.
- Keep network, storage, filesystem and UI effects explicit and separate from pure/domain computation where practical. Prefer immutable or controlled domain structures; avoid unexpected mutation.
- Follow the frozen storage/deployment boundaries: Turso for structured data, R2 for raw evidence, a local raw-storage adapter behind interfaces, and Streamlit Community Cloud for the application/UI. FastAPI remains deferred from the MVP. Implement adapters only in their authorized milestones.

## Python engineering quality
- Prefer clear, maintainable Python: small cohesive functions, descriptive intermediate variables and explicit control flow over compressed tricks, deep nesting or clever abstractions.
- Use domain-oriented names and Python conventions: `snake_case` for modules/functions/variables, `PascalCase` for classes and `UPPER_SNAKE_CASE` for constants. Avoid unclear abbreviations and meaningless names except in trivial, obvious scopes.
- Type public functions/methods, protocols, important internal functions and domain structures explicitly. Prefer stable typed models to `Any` or loosely structured dictionaries. Use appropriate `Decimal`, `date`, `datetime`, enums, literals and nullable types; never binary float for money. Preserve exact numeric, UTC and serialization contracts.
- Give every public class/protocol, non-trivial public function and non-obvious public method a concise useful docstring covering relevant purpose, domain meaning, inputs/outputs, invariants and missing/error behaviour. Do not merely repeat the identifier.
- Explain why non-obvious logic exists, especially provenance, missingness, exact numbers, UTC, validation, reliability/ER semantics, serialization and source-specific edge cases. Prefer self-explanatory code; do not comment every trivial line.
- Fail explicitly and predictably with errors identifying the violated contract or failed operation. Do not silently swallow errors or use broad catch-and-ignore patterns without a specific documented justification. External-source failures must not silently become valid data.
- Reuse existing components and avoid unrelated refactors. Do not add speculative factories, inheritance, wrappers, dependency-injection frameworks, generic interfaces, unused helpers or placeholder engines without a concrete current project need.
- Keep dependencies minimal. Prefer adequate standard-library or existing project functionality; evaluate necessity, maintenance, security, reproducibility and deployment compatibility before adding a dependency.
- Write for professional collaborative review: module responsibilities, domain decisions, provenance, missingness and test protection should be understandable without reverse engineering. Clarity and correctness matter more than apparent sophistication.

## Testing and completion review
- Add or update tests when behaviour changes. Use descriptive names and meaningful domain assertions covering applicable valid, invalid, boundary, missing-data and deterministic regression cases; do not inflate test count with empty checks.
- Unit tests should normally be deterministic and offline, with synthetic fixtures and no real credentials. Credential-dependent integration tests require explicit milestone scope and deliberate isolation/configuration.
- Before declaring work complete, run relevant required tests and configured checks, including `git diff --check`; report results and limitations. Never report a milestone as passing while required tests fail.
- Review changed code for unclear names, missing types/docstrings, unexplained logic, duplication, dead code, unused imports, oversized functions/modules, broad/silent exceptions, secrets, unnecessary dependencies, scope creep and architectural violations. Correct straightforward issues within scope; do not expand the milestone through refactoring.

## Security and repository hygiene
- Keep secrets out of source code, Git history, logs, tests and documentation. Never hard-code API keys, tokens, passwords, credentials or secret-bearing endpoints. Use environment variables/approved configuration; `.env` is local only and `.env.example` contains safe placeholders only.
- Respect ignore rules. Do not commit `.venv/`, `data/` reference material, `docs/human_review/` Word files, caches, build output or editor artifacts unless explicitly authorized. Inspect changes for accidental secrets and local artifacts before committing; never commit a real `.env`.

## Change protocol
For non-trivial changes:
1. Read this file and the relevant project documentation.
2. Inspect the existing implementation and tests.
3. State the proposed approach before making broad changes.
4. Implement the smallest coherent change.
5. Test it and perform the completion review above.
6. Update relevant documentation when architecture, schemas, data flow or important behaviour changes; report verification and limitations.

## Human review and Git boundaries
- Passing tests is not human approval. When milestone instructions require review, follow: implementation → automated tests → inspection/report → human review → authorized commit/push → explicitly authorized next milestone.
- Do not commit or push before required human approval. Keep milestone commits focused and reviewable, and inspect the staged diff for intended scope and hygiene.
- Stop at the requested acceptance boundary. Do not start the next milestone without explicit instruction, even after a successful commit/push.

## Project documentation
- `PROJECT_SPEC.md` defines the product requirements and MVP scope.
- `ARCHITECTURE.md` defines the system architecture and boundaries.
- `docs/` contains deeper design and product documentation.
- `docs/implementation/roadmap-v1.md` and the active milestone document define scope and acceptance; `docs/DOCS_INDEX.md` locates active specifications.
- `README.md` is the public-facing project introduction and setup guide.
