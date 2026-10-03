-- M8.1: immutable M3 requested/evidence reporting-year selection provenance.
CREATE TABLE accounts_run_selection (
    processing_run_id TEXT PRIMARY KEY REFERENCES accounts_run(processing_run_id),
    requested_reporting_year INTEGER NOT NULL CHECK(requested_reporting_year BETWEEN 1900 AND 9999),
    evidence_reporting_year INTEGER NOT NULL CHECK(evidence_reporting_year BETWEEN 1900 AND 9999),
    selected_period_end TEXT NOT NULL,
    selected_filing_fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('EXACT','NEAREST'))
) STRICT;
CREATE TRIGGER accounts_run_selection_no_update BEFORE UPDATE ON accounts_run_selection
BEGIN SELECT RAISE(ABORT,'immutable accounts reporting-year selection'); END;
CREATE TRIGGER accounts_run_selection_no_delete BEFORE DELETE ON accounts_run_selection
BEGIN SELECT RAISE(ABORT,'retain accounts reporting-year selection'); END;

CREATE TABLE assessment_financial_evidence_context (
    assessment_id TEXT PRIMARY KEY REFERENCES assessment(assessment_id),
    evidence_reporting_year INTEGER NOT NULL CHECK(evidence_reporting_year BETWEEN 1900 AND 9999)
) STRICT;
CREATE TRIGGER assessment_financial_evidence_context_no_update BEFORE UPDATE ON assessment_financial_evidence_context
BEGIN SELECT RAISE(ABORT,'immutable assessment evidence year'); END;
CREATE TRIGGER assessment_financial_evidence_context_no_delete BEFORE DELETE ON assessment_financial_evidence_context
BEGIN SELECT RAISE(ABORT,'retain assessment evidence year'); END;
