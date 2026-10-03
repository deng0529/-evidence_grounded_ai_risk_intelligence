-- Foundation v28: durable explanation for unavailable canonical financial facts.
CREATE TABLE financial_fact_missing_reason (
    fact_id TEXT PRIMARY KEY NOT NULL REFERENCES fact(fact_id),
    reason_code TEXT NOT NULL CHECK(reason_code IN ('NOT_FOUND_IN_SELECTED_ACCOUNTS','EXTRACTION_FAILED','VALIDATION_FAILED','RETRIEVAL_FAILED')),
    reason TEXT NOT NULL,
    document_id TEXT,
    processing_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER financial_fact_missing_reason_no_update BEFORE UPDATE ON financial_fact_missing_reason
BEGIN SELECT RAISE(ABORT,'immutable financial missingness reason'); END;
CREATE TRIGGER financial_fact_missing_reason_no_delete BEFORE DELETE ON financial_fact_missing_reason
BEGIN SELECT RAISE(ABORT,'immutable financial missingness reason'); END;
