-- Foundation v1: immutable audit of cleaning/normalization before canonical persistence.
CREATE TABLE financial_normalization_audit (
    fact_id TEXT PRIMARY KEY REFERENCES fact(fact_id),
    source_fact_id TEXT NOT NULL REFERENCES financial_source_fact(source_fact_id),
    normalization_version TEXT NOT NULL,
    raw_value TEXT,
    normalized_value TEXT NOT NULL,
    currency TEXT NOT NULL,
    unit TEXT NOT NULL,
    scale INTEGER NOT NULL,
    rule TEXT NOT NULL
) STRICT;
CREATE INDEX financial_normalization_source ON financial_normalization_audit(source_fact_id);
CREATE TRIGGER financial_normalization_no_update BEFORE UPDATE ON financial_normalization_audit
BEGIN SELECT RAISE(ABORT,'immutable financial normalization audit'); END;
CREATE TRIGGER financial_normalization_no_delete BEFORE DELETE ON financial_normalization_audit
BEGIN SELECT RAISE(ABORT,'retain financial normalization audit'); END;
