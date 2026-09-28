# Data Model — Initial Design

The detailed database schema will be implemented after the MVP entities and evidence workflow are validated.

## Core entities

### Company
- company_id
- companies_house_number
- name
- status
- incorporation_date
- sic_codes
- created_at
- updated_at

### Source
- source_id
- source_type
- source_name
- url_or_identifier
- retrieved_at
- access_status

### Document
- document_id
- source_id
- title
- document_type
- document_date
- storage_reference
- content_hash

### Fact
- fact_id
- company_id
- fact_type
- field_name
- value
- unit
- period
- source_id
- evidence_id
- extraction_method
- validation_status
- confidence

### Evidence
See the superseded evidence-model document.

### RiskIndicator
- indicator_id
- company_id
- domain
- indicator_name
- value
- severity
- methodology_version
- supporting_fact_ids
- supporting_evidence_ids

### RiskAssessment
- assessment_id
- company_id
- domain
- assessment
- explanation
- methodology_version
- generated_at
- supporting_indicator_ids

### ProcessingRun
Track pipeline execution so results can be reproduced or investigated.

## Important rule
The database schema should evolve from actual MVP requirements rather than being over-engineered at the start.
