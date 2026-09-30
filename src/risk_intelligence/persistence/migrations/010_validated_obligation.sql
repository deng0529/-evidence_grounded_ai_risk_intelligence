-- Additive M4-to-M5 obligation handoff; historical rules and rows are unchanged.
CREATE TABLE validated_obligation (
    validated_obligation_id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL,
    company_number TEXT NOT NULL,
    processing_run_id TEXT NOT NULL,
    assessment_date TEXT NOT NULL,
    obligation_kind TEXT NOT NULL CHECK(obligation_kind IN ('ACCOUNTS','CONFIRMATION_STATEMENT')),
    profile_snapshot_id TEXT NOT NULL REFERENCES resource_snapshot(snapshot_id),
    validated_filing_set_id TEXT NOT NULL REFERENCES validated_evidence_set(validated_evidence_set_id),
    record_json TEXT NOT NULL CHECK(json_valid(record_json)),
    FOREIGN KEY(company_id, company_number) REFERENCES company(company_id, company_number),
    FOREIGN KEY(processing_run_id, company_id) REFERENCES processing_run(processing_run_id, company_id)
) STRICT;
CREATE TABLE validated_obligation_fact (
    validated_obligation_id TEXT NOT NULL REFERENCES validated_obligation(validated_obligation_id),
    fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    PRIMARY KEY(validated_obligation_id, fact_id)
) STRICT;
CREATE INDEX obligation_company_date ON validated_obligation(company_id, assessment_date, obligation_kind);
CREATE TRIGGER obligation_no_update BEFORE UPDATE ON validated_obligation
BEGIN SELECT RAISE(ABORT,'immutable validated obligation'); END;
CREATE TRIGGER obligation_no_delete BEFORE DELETE ON validated_obligation
BEGIN SELECT RAISE(ABORT,'immutable validated obligation'); END;
CREATE TRIGGER obligation_fact_no_update BEFORE UPDATE ON validated_obligation_fact
BEGIN SELECT RAISE(ABORT,'immutable obligation lineage'); END;
CREATE TRIGGER obligation_fact_no_delete BEFORE DELETE ON validated_obligation_fact
BEGIN SELECT RAISE(ABORT,'immutable obligation lineage'); END;
