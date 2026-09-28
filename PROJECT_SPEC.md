# PROJECT_SPEC.md — Evidence-Grounded AI Risk Intelligence

## 1. Project objective
Build a working AI-assisted risk intelligence prototype that combines:
- automated public-document and web-data ingestion;
- structured data extraction;
- source-level evidence validation;
- data provenance;
- explainable risk assessment; and
- an interactive web dashboard.

The central design principle is:

**Source → Evidence → Structured Fact → Validation → Risk Indicator → Risk Assessment → Explanation**

The prototype is intended to demonstrate practical data/AI engineering, reliability, traceability, and explainability rather than merely generate an LLM-written company summary.

## 2. Target use case
Initial target users are SMEs, analysts, researchers, consultants, and hiring/interview audiences who need a fast, traceable view of publicly available company risk information.

The first release should focus on a small number of UK companies and public sources. It is a prototype, not a regulated credit-rating, investment-advice, legal, or compliance product.

## 3. Initial data sources
Primary sources:
1. UK Companies House public data/API and publicly available filing documents.
2. Official company websites and publicly accessible pages/documents.

Potential future sources may include other authoritative public datasets, but they are outside the first MVP unless required.

## 4. Initial risk domains
The frozen MVP contains exactly two top-level risk domains:
- Governance Risk
- Financial Risk

The 11 leaf variables, indicators, formulas, thresholds and importance weights
are defined in `docs/design-docs/risk-model-v1.md` and are based on observable
evidence. Business/operational Resilience is deferred and outside the current
MVP risk model; it is not a third domain.

## 5. Core requirements

### R1 — Company identification
The system must identify a company using a stable identifier such as Companies House company number where applicable.

### R2 — Source ingestion
The system must retrieve or ingest relevant public information while retaining source metadata.

### R3 — Document processing
The system should support common public formats needed by the MVP, especially HTML and PDF, with a modular parser design.

### R4 — Structured extraction
Important facts must be represented as structured fields rather than only free text.

Examples:
- financial metric;
- value;
- unit;
- reporting period;
- filing date;
- officer information;
- company status;
- business information.

### R5 — Evidence grounding
Every material extracted fact used in risk assessment should be traceable to supporting evidence.

An evidence record should, where available, include:
- source type;
- source name;
- source URL or stable identifier;
- retrieval timestamp/date;
- document title;
- document date;
- page/section/paragraph/location;
- extracted evidence text;
- extraction method;
- confidence/validation status.

### R6 — Validation
The system should distinguish:
- source retrieved;
- evidence located;
- fact extracted;
- fact validated;
- fact uncertain;
- fact conflicting.

Validation should not silently convert uncertainty into certainty.

### R7 — Risk assessment
Risk assessment should be as reproducible as practical. The MVP should favour deterministic rules/indicators for core scoring and use AI for extraction, interpretation, and explanation where appropriate.

### R8 — Explainability
A user should be able to move from a risk result to:
1. the risk factor;
2. the underlying structured data;
3. the evidence supporting that data; and
4. the original source.

### R9 — Auditability
Important transformations should be reproducible or inspectable through stored metadata, logs, structured records, and tests.

### R10 — Dashboard
The MVP should provide an interactive dashboard that allows a user to:
- select/search a company;
- view risk domains;
- inspect key indicators;
- inspect supporting evidence;
- understand uncertainty and validation status.

## 6. Non-goals for MVP
Do not initially build:
- a production-grade enterprise platform;
- automated investment recommendations;
- regulated credit scoring;
- a large-scale crawler;
- multi-agent orchestration unless later justified;
- Kubernetes or microservices;
- model fine-tuning;
- a complex vector database/RAG system unless a demonstrated requirement emerges.

## 7. AI usage policy
LLMs may assist with:
- document understanding;
- structured extraction;
- classification;
- summarisation;
- evidence interpretation;
- natural-language explanations.

LLMs must not be treated as the authoritative source of factual company data. Source documents and authoritative structured APIs remain the evidence base.

## 8. MVP success criteria
A successful MVP should allow a user to choose a company and obtain:
- structured company information;
- a small set of risk indicators;
- a risk assessment for the defined domains;
- an explanation of material findings;
- evidence and source traceability for the findings.

The prototype should be demonstrable through a web interface and publishable as a GitHub portfolio project.

## 9. Quality priorities
In order of importance:
1. Evidence correctness and traceability.
2. Reproducibility and validation.
3. Clear data model and architecture.
4. Useful risk explanation.
5. Robustness.
6. UI polish.
7. Scale.

## 10. Evolution
The architecture must allow additional data sources, risk indicators, document types, validation methods, and UI components to be added without rewriting unrelated modules.
