CREATE TABLE saved_reference_belief (
 calculation_id TEXT PRIMARY KEY,
 company_number TEXT NOT NULL,
 m2_run_id TEXT NOT NULL REFERENCES processing_run(processing_run_id),
 m3_run_id TEXT NOT NULL REFERENCES processing_run(processing_run_id),
 standard_version TEXT NOT NULL,
 method_version TEXT NOT NULL,
 payload TEXT NOT NULL
) STRICT;
