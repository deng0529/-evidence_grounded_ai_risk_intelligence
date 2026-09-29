-- M3 source observations and processing lineage; existing evidence/facts remain intact.
CREATE TABLE accounts_document (
    document_id TEXT PRIMARY KEY REFERENCES document(document_id),
    filing_fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    metadata_source_id TEXT NOT NULL REFERENCES raw_evidence(source_id),
    remote_document_id TEXT NOT NULL,
    media_type TEXT NOT NULL,
    selection_reason TEXT NOT NULL
) STRICT;
CREATE TABLE financial_source_fact (
    source_fact_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(document_id),
    evidence_id TEXT NOT NULL REFERENCES evidence_reference(evidence_id),
    source_concept TEXT NOT NULL, source_label TEXT, raw_value TEXT, value TEXT,
    availability_status TEXT NOT NULL CHECK(availability_status IN
        ('AVAILABLE','NOT_DISCLOSED','NOT_APPLICABLE','RETRIEVAL_FAILED','EXTRACTION_FAILED',
         'VALIDATION_FAILED','CONFLICT_UNRESOLVED','NON_COMPARABLE')),
    currency TEXT, unit TEXT, unit_ref TEXT, context_ref TEXT NOT NULL,
    entity_identifier TEXT NOT NULL, entity_scheme TEXT NOT NULL,
    dimensions_json TEXT NOT NULL CHECK(json_valid(dimensions_json) AND json_type(dimensions_json)='array'),
    period_type TEXT NOT NULL CHECK(period_type IN ('INSTANT','DURATION')),
    period_start TEXT, period_end TEXT NOT NULL, period_length_days INTEGER,
    comparability_status TEXT NOT NULL CHECK(comparability_status IN ('COMPARABLE','NON_COMPARABLE','REVIEW_REQUIRED','NOT_APPLICABLE')),
    period_role TEXT NOT NULL CHECK(period_role IN ('CURRENT','COMPARATIVE')),
    scale INTEGER NOT NULL CHECK(scale BETWEEN -18 AND 18), sign TEXT NOT NULL CHECK(sign IN ('+','-')),
    decimals TEXT, precision TEXT, transformation TEXT,
    extraction_method TEXT NOT NULL CHECK(extraction_method IN
        ('IXBRL_DIRECT','PDF_NATIVE_DETERMINISTIC','PDF_OCR_DETERMINISTIC','LLM_NATIVE_TEXT','LLM_OCR_TEXT')),
    parser_version TEXT NOT NULL, page INTEGER CHECK(page >= 1),
    CHECK((availability_status IN ('AVAILABLE','NON_COMPARABLE')) = (value IS NOT NULL)),
    CHECK(value IS NULL OR (currency IS NOT NULL AND unit IS NOT NULL AND upper(trim(value)) != 'UNKNOWN')),
    CHECK(period_start IS NULL OR period_start <= period_end),
    CHECK(period_type != 'DURATION' OR period_start IS NOT NULL)
) STRICT;
CREATE TABLE financial_observation_lineage (
    fact_id TEXT PRIMARY KEY REFERENCES fact(fact_id),
    origin TEXT NOT NULL CHECK(origin IN ('DIRECT','DERIVED')),
    mapping_version TEXT NOT NULL,
    derivation_version TEXT,
    derivation_rule TEXT,
    CHECK((origin='DERIVED') = (derivation_version IS NOT NULL AND derivation_rule IS NOT NULL))
) STRICT;
CREATE TABLE financial_observation_component (
    fact_id TEXT NOT NULL REFERENCES financial_observation_lineage(fact_id),
    source_fact_id TEXT NOT NULL REFERENCES financial_source_fact(source_fact_id),
    position INTEGER NOT NULL CHECK(position >= 0),
    PRIMARY KEY(fact_id, position), UNIQUE(fact_id,source_fact_id)
) STRICT;
CREATE TABLE accounts_processing (
    fingerprint TEXT PRIMARY KEY,
    stage TEXT NOT NULL CHECK(stage IN ('PARSE','OCR','LLM','CANONICAL')),
    input_raw_id TEXT NOT NULL REFERENCES raw_evidence(raw_evidence_id),
    processing_run_id TEXT NOT NULL REFERENCES processing_run(processing_run_id),
    version TEXT NOT NULL, config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETE','FAILED')),
    output_raw_id TEXT REFERENCES raw_evidence(raw_evidence_id), error_code TEXT,
    CHECK((status='COMPLETE') = (output_raw_id IS NOT NULL))
) STRICT;
CREATE TABLE accounts_run (
    processing_run_id TEXT PRIMARY KEY REFERENCES processing_run(processing_run_id),
    assessment_date TEXT NOT NULL, max_documents INTEGER NOT NULL CHECK(max_documents BETWEEN 1 AND 10),
    mapping_version TEXT NOT NULL, stopping_reason TEXT NOT NULL
) STRICT;
CREATE TABLE accounts_run_document (
    processing_run_id TEXT NOT NULL REFERENCES accounts_run(processing_run_id),
    filing_fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    document_id TEXT REFERENCES document(document_id),
    status TEXT NOT NULL CHECK(status IN ('COMPLETE','PARTIAL','FAILED')),
    availability_status TEXT NOT NULL CHECK(availability_status IN ('AVAILABLE','RETRIEVAL_FAILED','EXTRACTION_FAILED','VALIDATION_FAILED')),
    reason TEXT NOT NULL,
    reused_raw INTEGER NOT NULL CHECK(reused_raw IN (0,1)),
    reused_parse INTEGER NOT NULL CHECK(reused_parse IN (0,1)),
    PRIMARY KEY(processing_run_id,filing_fact_id)
) STRICT;
CREATE TRIGGER accounts_run_document_no_update BEFORE UPDATE ON accounts_run_document
BEGIN SELECT RAISE(ABORT,'immutable document outcome'); END;
CREATE TRIGGER accounts_run_document_no_delete BEFORE DELETE ON accounts_run_document
BEGIN SELECT RAISE(ABORT,'immutable document outcome'); END;
CREATE TRIGGER accounts_run_no_delete BEFORE DELETE ON accounts_run
BEGIN SELECT RAISE(ABORT,'retain accounts run context'); END;
CREATE TRIGGER accounts_run_frozen BEFORE UPDATE ON accounts_run
WHEN OLD.stopping_reason != 'RUNNING' OR NEW.processing_run_id != OLD.processing_run_id
 OR NEW.assessment_date != OLD.assessment_date OR NEW.mapping_version != OLD.mapping_version
 OR NEW.max_documents != OLD.max_documents
BEGIN SELECT RAISE(ABORT,'immutable accounts run context'); END;
CREATE TRIGGER accounts_processing_terminal BEFORE UPDATE ON accounts_processing
WHEN OLD.status != 'RUNNING' OR NEW.fingerprint != OLD.fingerprint
  OR NEW.processing_run_id != OLD.processing_run_id OR NEW.created_at != OLD.created_at
  OR NEW.input_raw_id != OLD.input_raw_id OR NEW.version != OLD.version OR NEW.config_json != OLD.config_json
  OR NEW.stage != OLD.stage
BEGIN SELECT RAISE(ABORT,'immutable completed processing'); END;
CREATE TRIGGER accounts_processing_no_delete BEFORE DELETE ON accounts_processing
BEGIN SELECT RAISE(ABORT,'retain processing history'); END;
CREATE INDEX financial_source_document ON financial_source_fact(document_id,parser_version);
CREATE INDEX financial_source_period ON financial_source_fact(entity_identifier,period_end);
CREATE INDEX financial_component_source ON financial_observation_component(source_fact_id);
CREATE TRIGGER accounts_document_no_update BEFORE UPDATE ON accounts_document
BEGIN SELECT RAISE(ABORT,'immutable accounts lineage'); END;
CREATE TRIGGER accounts_document_no_delete BEFORE DELETE ON accounts_document
BEGIN SELECT RAISE(ABORT,'immutable accounts lineage'); END;
CREATE TRIGGER financial_source_no_update BEFORE UPDATE ON financial_source_fact
BEGIN SELECT RAISE(ABORT,'immutable source observation'); END;
CREATE TRIGGER financial_source_no_delete BEFORE DELETE ON financial_source_fact
BEGIN SELECT RAISE(ABORT,'immutable source observation'); END;
CREATE TRIGGER financial_lineage_no_update BEFORE UPDATE ON financial_observation_lineage
BEGIN SELECT RAISE(ABORT,'immutable canonical lineage'); END;
CREATE TRIGGER financial_lineage_no_delete BEFORE DELETE ON financial_observation_lineage
BEGIN SELECT RAISE(ABORT,'immutable canonical lineage'); END;
CREATE TRIGGER financial_component_no_update BEFORE UPDATE ON financial_observation_component
BEGIN SELECT RAISE(ABORT,'immutable component lineage'); END;
CREATE TRIGGER financial_component_no_delete BEFORE DELETE ON financial_observation_component
BEGIN SELECT RAISE(ABORT,'immutable component lineage'); END;
