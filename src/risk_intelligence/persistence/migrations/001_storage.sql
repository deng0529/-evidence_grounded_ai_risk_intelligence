-- M1 only: exact numbers are TEXT; raw bytes never enter this schema.
CREATE TABLE company (
    company_id TEXT PRIMARY KEY NOT NULL,
    company_number TEXT NOT NULL UNIQUE CHECK(length(company_number)=8 AND company_number NOT GLOB '*[^A-Z0-9]*'),
    company_name TEXT NOT NULL CHECK(length(trim(company_name))>0),
    company_status TEXT, company_type TEXT, incorporation_date TEXT, registered_office TEXT,
    sic_codes_json TEXT NOT NULL CHECK(json_valid(sic_codes_json) AND json_type(sic_codes_json)='array'),
    UNIQUE(company_id, company_number)
) STRICT;
CREATE TABLE processing_run (
    processing_run_id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL, company_number TEXT NOT NULL,
    started_at TEXT NOT NULL, completed_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','COMPLETE','PARTIAL','FAILED')),
    current_stage TEXT NOT NULL, trigger_type TEXT NOT NULL CHECK(trigger_type IN ('LIVE','REFRESH','DEMO_PRECOMPUTE')),
    app_version TEXT NOT NULL, error_code TEXT, error_message TEXT,
    CHECK(completed_at IS NULL OR completed_at >= started_at),
    UNIQUE(processing_run_id, company_id),
    FOREIGN KEY(company_id, company_number) REFERENCES company(company_id, company_number)
) STRICT;
CREATE TABLE source (
    source_id TEXT PRIMARY KEY NOT NULL, company_id TEXT NOT NULL, company_number TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('COMPANIES_HOUSE_API','COMPANIES_HOUSE_IXBRL','COMPANIES_HOUSE_PDF','OFFICIAL_WEBSITE')),
    source_name TEXT NOT NULL, source_url TEXT, source_identifier TEXT,
    retrieved_at TEXT NOT NULL,
    retrieval_status TEXT NOT NULL CHECK(retrieval_status IN ('SUCCESS','FAILED')),
    processing_run_id TEXT NOT NULL, http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
    checksum TEXT CHECK(checksum IS NULL OR (length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*')),
    CHECK(source_url IS NOT NULL OR source_identifier IS NOT NULL),
    UNIQUE(source_id, company_id),
    FOREIGN KEY(company_id, company_number) REFERENCES company(company_id, company_number),
    FOREIGN KEY(processing_run_id, company_id) REFERENCES processing_run(processing_run_id, company_id)
) STRICT;
CREATE TABLE document (
    document_id TEXT PRIMARY KEY NOT NULL, company_id TEXT NOT NULL, company_number TEXT NOT NULL,
    source_id TEXT NOT NULL, document_type TEXT NOT NULL, representation_type TEXT NOT NULL,
    filing_id TEXT, title TEXT, period_start TEXT, period_end TEXT, filing_date TEXT,
    object_path TEXT, checksum TEXT,
    CHECK(period_start IS NULL OR period_end IS NULL OR period_start <= period_end),
    CHECK((object_path IS NULL) = (checksum IS NULL)),
    UNIQUE(document_id, source_id), UNIQUE(document_id, company_id),
    FOREIGN KEY(company_id, company_number) REFERENCES company(company_id, company_number),
    FOREIGN KEY(source_id, company_id) REFERENCES source(source_id, company_id),
    -- A document pointer cannot commit without matching raw metadata.
    FOREIGN KEY(source_id, object_path, checksum)
        REFERENCES raw_evidence(source_id, object_path, checksum) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE raw_evidence (
    raw_evidence_id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL UNIQUE,
    document_id TEXT, object_path TEXT NOT NULL,
    checksum TEXT NOT NULL CHECK(length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'),
    retrieved_at TEXT NOT NULL, processing_run_id TEXT NOT NULL, media_type TEXT NOT NULL,
    UNIQUE(source_id, object_path, checksum),
    FOREIGN KEY(source_id) REFERENCES source(source_id),
    FOREIGN KEY(document_id, source_id) REFERENCES document(document_id, source_id),
    FOREIGN KEY(processing_run_id) REFERENCES processing_run(processing_run_id)
) STRICT;
CREATE TABLE evidence_reference (
    evidence_id TEXT PRIMARY KEY NOT NULL, source_id TEXT NOT NULL, document_id TEXT,
    locator_kind TEXT NOT NULL CHECK(locator_kind IN ('JSON_PATH','IXBRL_FACT','PDF_REGION')),
    endpoint TEXT, json_path TEXT, concept TEXT, context_id TEXT,
    page INTEGER CHECK(page>=1), label TEXT, section TEXT, table_label TEXT, evidence_text TEXT,
    FOREIGN KEY(source_id) REFERENCES raw_evidence(source_id),
    FOREIGN KEY(document_id, source_id) REFERENCES document(document_id, source_id),
    CHECK(
      (locator_kind='JSON_PATH' AND endpoint IS NOT NULL AND json_path IS NOT NULL
       AND concept IS NULL AND context_id IS NULL AND page IS NULL AND label IS NULL AND section IS NULL AND table_label IS NULL)
      OR (locator_kind='IXBRL_FACT' AND document_id IS NOT NULL AND concept IS NOT NULL AND context_id IS NOT NULL
       AND endpoint IS NULL AND json_path IS NULL AND page IS NULL AND label IS NULL AND section IS NULL AND table_label IS NULL)
      OR (locator_kind='PDF_REGION' AND document_id IS NOT NULL AND page IS NOT NULL AND label IS NOT NULL
       AND endpoint IS NULL AND json_path IS NULL AND concept IS NULL AND context_id IS NULL)
    )
) STRICT;
CREATE TABLE fact (
    fact_id TEXT PRIMARY KEY NOT NULL,
    record_kind TEXT NOT NULL CHECK(record_kind IN ('STRUCTURED','FINANCIAL')),
    company_id TEXT NOT NULL, company_number TEXT NOT NULL, canonical_concept TEXT NOT NULL,
    source_id TEXT NOT NULL, document_id TEXT, processing_run_id TEXT NOT NULL,
    extraction_method TEXT NOT NULL CHECK(extraction_method IN ('API_DIRECT','IXBRL_DIRECT','PDF_NATIVE_DETERMINISTIC','PDF_OCR_DETERMINISTIC','LLM_NATIVE_TEXT','LLM_OCR_TEXT','DERIVED')),
    availability_status TEXT NOT NULL CHECK(availability_status IN ('AVAILABLE','NOT_DISCLOSED','NOT_APPLICABLE','RETRIEVAL_FAILED','EXTRACTION_FAILED','VALIDATION_FAILED','CONFLICT_UNRESOLVED','NON_COMPARABLE')),
    fact_type TEXT NOT NULL CHECK(fact_type IN ('NUMERIC','DATE','TEXT','BOOLEAN','CODES')),
    value_numeric TEXT, value_date TEXT, value_text TEXT, value_boolean INTEGER CHECK(value_boolean IN (0,1)),
    value_codes_json TEXT CHECK(value_codes_json IS NULL OR (json_valid(value_codes_json) AND json_type(value_codes_json)='array')),
    candidate_numeric TEXT, candidate_date TEXT, candidate_text TEXT, candidate_boolean INTEGER CHECK(candidate_boolean IN (0,1)),
    candidate_codes_json TEXT CHECK(candidate_codes_json IS NULL OR (json_valid(candidate_codes_json) AND json_type(candidate_codes_json)='array')),
    subject_identifier TEXT, source_concept TEXT, currency TEXT, unit TEXT,
    period_type TEXT CHECK(period_type IN ('INSTANT','DURATION')),
    period_start TEXT, period_end TEXT, period_length_days INTEGER CHECK(period_length_days>=1),
    comparability_status TEXT CHECK(comparability_status IN ('COMPARABLE','NON_COMPARABLE','REVIEW_REQUIRED','NOT_APPLICABLE')),
    FOREIGN KEY(company_id, company_number) REFERENCES company(company_id, company_number),
    FOREIGN KEY(source_id, company_id) REFERENCES source(source_id, company_id),
    FOREIGN KEY(document_id, source_id) REFERENCES document(document_id, source_id),
    FOREIGN KEY(processing_run_id, company_id) REFERENCES processing_run(processing_run_id, company_id),
    CHECK(record_kind!='FINANCIAL' OR (fact_type='NUMERIC' AND subject_identifier IS NULL)),
    CHECK(record_kind!='STRUCTURED' OR (source_concept IS NULL AND currency IS NULL AND unit IS NULL
       AND period_type IS NULL AND period_start IS NULL AND period_end IS NULL
       AND period_length_days IS NULL AND comparability_status IS NULL)),
    CHECK((period_type IS NULL AND period_start IS NULL AND period_end IS NULL
       AND period_length_days IS NULL AND comparability_status IS NULL)
       OR (period_type IS NOT NULL AND period_end IS NOT NULL AND comparability_status IS NOT NULL
       AND (period_type!='DURATION' OR period_start IS NOT NULL))),
    CHECK(period_start IS NULL OR period_end IS NULL OR period_start<=period_end),
    CHECK(record_kind!='FINANCIAL' OR value_numeric IS NULL OR (unit IS NOT NULL AND period_type IS NOT NULL)),
    CHECK(value_text IS NULL OR upper(trim(value_text))!='UNKNOWN'),
    CHECK(candidate_text IS NULL OR upper(trim(candidate_text))!='UNKNOWN'),
    CHECK(value_numeric IS NULL OR upper(trim(value_numeric))!='UNKNOWN'),
    CHECK(candidate_numeric IS NULL OR upper(trim(candidate_numeric))!='UNKNOWN'),
    CHECK(value_date IS NULL OR upper(trim(value_date))!='UNKNOWN'),
    CHECK(candidate_date IS NULL OR upper(trim(candidate_date))!='UNKNOWN'),
    CHECK(fact_type='NUMERIC' OR (value_numeric IS NULL AND candidate_numeric IS NULL)),
    CHECK(fact_type='DATE' OR (value_date IS NULL AND candidate_date IS NULL)),
    CHECK(fact_type='TEXT' OR (value_text IS NULL AND candidate_text IS NULL)),
    CHECK(fact_type='BOOLEAN' OR (value_boolean IS NULL AND candidate_boolean IS NULL)),
    CHECK(fact_type='CODES' OR (value_codes_json IS NULL AND candidate_codes_json IS NULL)),
    CHECK((availability_status IN ('AVAILABLE','NON_COMPARABLE')) =
      (value_numeric IS NOT NULL OR value_date IS NOT NULL OR value_text IS NOT NULL OR value_boolean IS NOT NULL OR value_codes_json IS NOT NULL))
) STRICT;
CREATE TABLE fact_evidence (
    fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    position INTEGER NOT NULL CHECK(position>=0),
    evidence_id TEXT NOT NULL REFERENCES evidence_reference(evidence_id),
    PRIMARY KEY(fact_id, position)
) STRICT;
CREATE TABLE assessment (
    assessment_id TEXT PRIMARY KEY NOT NULL, company_id TEXT NOT NULL, company_number TEXT NOT NULL,
    processing_run_id TEXT NOT NULL, assessment_date TEXT NOT NULL, data_current_to TEXT,
    status TEXT NOT NULL CHECK(status IN ('COMPLETE','PARTIAL','FAILED')),
    risk_model_version TEXT NOT NULL, reliability_model_version TEXT NOT NULL,
    er_model_version TEXT NOT NULL, data_dictionary_version TEXT NOT NULL,
    FOREIGN KEY(company_id, company_number) REFERENCES company(company_id, company_number),
    FOREIGN KEY(processing_run_id, company_id) REFERENCES processing_run(processing_run_id, company_id)
) STRICT;
CREATE INDEX source_company_time ON source(company_id, retrieved_at);
CREATE INDEX source_run ON source(processing_run_id);
CREATE INDEX document_source ON document(source_id);
CREATE INDEX document_filing ON document(company_id, filing_id);
CREATE INDEX raw_document ON raw_evidence(document_id);
CREATE INDEX raw_object ON raw_evidence(object_path);
CREATE INDEX raw_run ON raw_evidence(processing_run_id);
CREATE INDEX evidence_source_document ON evidence_reference(source_id, document_id);
CREATE INDEX evidence_document ON evidence_reference(document_id);
CREATE INDEX fact_concept_run ON fact(company_id, canonical_concept, processing_run_id);
CREATE INDEX fact_source ON fact(source_id);
CREATE INDEX fact_document ON fact(document_id);
CREATE INDEX fact_run ON fact(processing_run_id);
CREATE INDEX evidence_facts ON fact_evidence(evidence_id, fact_id);
CREATE INDEX run_company_time ON processing_run(company_id, started_at);
CREATE INDEX assessment_company_date ON assessment(company_id, assessment_date);
CREATE INDEX assessment_run ON assessment(processing_run_id);
-- Reverse links may include corroborating evidence from other sources, but never another company.
CREATE TRIGGER fact_evidence_company BEFORE INSERT ON fact_evidence
WHEN (SELECT company_id FROM fact WHERE fact_id=NEW.fact_id) !=
     (SELECT s.company_id FROM evidence_reference e JOIN source s USING(source_id) WHERE e.evidence_id=NEW.evidence_id)
BEGIN SELECT RAISE(ABORT, 'cross-company evidence link'); END;
CREATE TRIGGER source_no_update BEFORE UPDATE ON source
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER source_no_delete BEFORE DELETE ON source
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER document_no_update BEFORE UPDATE ON document
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER document_no_delete BEFORE DELETE ON document
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER raw_evidence_no_update BEFORE UPDATE ON raw_evidence
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER raw_evidence_no_delete BEFORE DELETE ON raw_evidence
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER evidence_reference_no_update BEFORE UPDATE ON evidence_reference
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER evidence_reference_no_delete BEFORE DELETE ON evidence_reference
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER fact_no_update BEFORE UPDATE ON fact
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER fact_no_delete BEFORE DELETE ON fact
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER fact_evidence_no_update BEFORE UPDATE ON fact_evidence
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER fact_evidence_no_delete BEFORE DELETE ON fact_evidence
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER assessment_no_update BEFORE UPDATE ON assessment
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
CREATE TRIGGER assessment_no_delete BEFORE DELETE ON assessment
BEGIN SELECT RAISE(ABORT, 'immutable historical record'); END;
