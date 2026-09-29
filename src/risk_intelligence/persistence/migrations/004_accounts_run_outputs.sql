-- Preserve the exact processing and observation membership of each M3 run.
-- Historical parser outputs remain immutable without appearing as current inputs.
CREATE TABLE accounts_run_processing (
    processing_run_id TEXT NOT NULL REFERENCES accounts_run(processing_run_id),
    fingerprint TEXT NOT NULL REFERENCES accounts_processing(fingerprint),
    PRIMARY KEY(processing_run_id, fingerprint)
) STRICT;
CREATE TABLE accounts_run_fact (
    processing_run_id TEXT NOT NULL REFERENCES accounts_run(processing_run_id),
    fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    PRIMARY KEY(processing_run_id, fact_id)
) STRICT;
CREATE TRIGGER accounts_run_processing_no_update BEFORE UPDATE ON accounts_run_processing
BEGIN SELECT RAISE(ABORT,'immutable run processing lineage'); END;
CREATE TRIGGER accounts_run_processing_no_delete BEFORE DELETE ON accounts_run_processing
BEGIN SELECT RAISE(ABORT,'retain run processing lineage'); END;
CREATE TRIGGER accounts_run_fact_no_update BEFORE UPDATE ON accounts_run_fact
BEGIN SELECT RAISE(ABORT,'immutable run observation lineage'); END;
CREATE TRIGGER accounts_run_fact_no_delete BEFORE DELETE ON accounts_run_fact
BEGIN SELECT RAISE(ABORT,'retain run observation lineage'); END;
