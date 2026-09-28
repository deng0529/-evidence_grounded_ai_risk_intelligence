# ARCHITECTURE.md — Evidence-Grounded AI Risk Intelligence

## 1. Architectural principle

The system is an evidence-grounded pipeline:

Source
→ Ingestion
→ Raw artefact
→ Extraction
→ Structured fact
→ Evidence validation
→ Validated fact
→ Risk indicator
→ Risk assessment
→ Explanation
→ Dashboard

The architecture separates what a source says from what the system concludes.

## 2. Logical components

### 2.1 Ingestion
Responsible for acquiring public information from approved sources.

Examples:
- Companies House API/client;
- Companies House filing/document retrieval;
- company website retrieval.

Ingestion must record source metadata and should not perform final risk scoring.

### 2.2 Document processing
Responsible for converting HTML/PDF/text into a consistent internal representation.

It should preserve enough location information to support later evidence citation.

### 2.3 Extraction
Responsible for converting source material into structured facts.

Possible approaches:
- deterministic parsers;
- regular expressions;
- table extraction;
- LLM structured-output extraction.

Extraction output must retain provenance.

### 2.4 Evidence and validation
Responsible for determining whether extracted facts can be supported by source evidence.

Validation states should include, as appropriate:
- validated;
- partially validated;
- uncertain;
- conflicting;
- rejected.

### 2.5 Database layer
Responsible for persistence of:
- companies;
- sources;
- documents;
- extracted facts;
- evidence;
- validation results;
- risk indicators;
- risk assessments;
- processing runs.

Database access must be isolated from business logic as far as practical.

### 2.6 Risk calculation and aggregation

#### M5 — Risk Variable & Leaf Belief Engine
Computes the 11 risk-variable values from validated facts using frozen
formulas, directions, thresholds and leaf rules. It consumes M4 evidence
reliability results and applies frozen Reliability-to-Unknown and
missing/unavailable/non-comparable input handling. M5 ends with all 11 final
Low / High / Unknown leaf distributions; it performs no parent aggregation.

#### M6 — Hierarchical ER Aggregation Engine
Accepts those final M5 leaf distributions unchanged and applies frozen
importance weights and single-child pass-through rules to aggregate
Variables → Indicators → Domains → Overall. It produces indicator,
Governance, Financial and Overall Low / High / Unknown distributions and
must pass frozen ER regression and stress tests. It must not recalculate
source facts, financial ratios, governance metrics, leaf thresholds,
evidence reliability or leaf beliefs.

The interface and existing persistence contracts are described in
`docs/implementation/roadmap-v1.md`.

Risk calculations should be inspectable and versioned where practical.

### 2.7 Explanation layer
Responsible for turning validated indicators and evidence into user-readable explanations.

It must not introduce unsupported factual claims.

### 2.8 Dashboard
Responsible for interaction and presentation only.

The UI should call application/service functions rather than embedding ingestion, extraction, or scoring logic directly in UI code.

## 3. Suggested repository structure

```text
evidence-grounded-ai-risk-intelligence/
├── AGENTS.md
├── PROJECT_SPEC.md
├── ARCHITECTURE.md
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
│
├── src/
│   ├── ingestion/
│   │   ├── companies_house/
│   │   └── web/
│   ├── documents/
│   ├── extraction/
│   ├── validation/
│   ├── risk/
│   ├── database/
│   └── common/
│
├── app/
├── tests/
├── data/
│   ├── raw/
│   ├── processed/
│   └── evidence/
│
└── docs/
    ├── product-specs/
    └── design-docs/
```

This is a starting structure, not a requirement to create every file immediately.

## 4. Data-flow boundaries

### External sources
The system may read public source material but should not alter source systems.

### Ingestion boundary
External content enters the system as a raw source artefact plus metadata.

### Extraction boundary
Raw content becomes structured candidate facts.

### Validation boundary
Candidate facts are compared with evidence.

### Risk boundary
Only sufficiently supported/validated facts should contribute to material risk indicators.

### Presentation boundary
The dashboard displays results and links them back to evidence.

## 5. Provenance model

At minimum, a material fact should be traceable through:

```text
Risk assessment
  ↓
Risk indicator
  ↓
Structured fact
  ↓
Evidence record
  ↓
Document/source
  ↓
External source
```

No material risk conclusion should be a provenance dead-end.

## 6. Change management

When a new feature is requested:
1. Determine which architectural component owns it.
2. Inspect existing interfaces and tests.
3. Reuse existing components where possible.
4. Add a new module only when it has a clear responsibility.
5. Update this document when boundaries materially change.

## 7. Technology direction

Current MVP implementation architecture:
- Python;
- Turso for structured relational data;
- Cloudflare R2 for immutable raw evidence/object storage;
- local filesystem raw-evidence adapter behind storage interfaces for development;
- Streamlit Community Cloud for the Python application and UI;
- FastAPI deferred from the MVP;
- Companies House API;
- public web/document retrieval;
- OpenAI API for selected AI tasks;
- pytest;
- Git/GitHub.

Technology choices may evolve based on evidence from the implementation.

## 8. Reliability principle

The system should prefer:
**authoritative source + deterministic extraction/validation**
over:
**LLM-generated assertion**.

AI should increase the usefulness of evidence, not replace evidence.
