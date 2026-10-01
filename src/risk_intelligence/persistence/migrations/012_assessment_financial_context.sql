-- MVP v1.1: explicit single reporting-year selection; never inferred from assessment date.
CREATE TABLE assessment_financial_context (
    assessment_id TEXT PRIMARY KEY NOT NULL REFERENCES assessment(assessment_id),
    reporting_year INTEGER NOT NULL CHECK(reporting_year BETWEEN 1900 AND 9999)
) STRICT;
CREATE TRIGGER assessment_financial_context_no_update BEFORE UPDATE ON assessment_financial_context
BEGIN SELECT RAISE(ABORT,'immutable assessment financial context'); END;
CREATE TRIGGER assessment_financial_context_no_delete BEFORE DELETE ON assessment_financial_context
BEGIN SELECT RAISE(ABORT,'immutable assessment financial context'); END;
