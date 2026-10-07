CREATE TABLE risk_reference_standard (
 standard_version TEXT NOT NULL,
 variable_code TEXT NOT NULL,
 variable_name TEXT NOT NULL,
 domain TEXT NOT NULL CHECK(domain IN ('GOVERNANCE','FINANCIAL')),
 low_reference TEXT NOT NULL,
 high_reference TEXT NOT NULL,
 unit TEXT NOT NULL,
 value_definition TEXT NOT NULL,
 transform_method TEXT NOT NULL,
 approval_basis TEXT NOT NULL,
 PRIMARY KEY(standard_version, variable_code)
) STRICT;
CREATE TABLE leaf_test_reference_standard (
 processing_run_id TEXT PRIMARY KEY REFERENCES processing_run(processing_run_id),
 standard_version TEXT NOT NULL
) STRICT;
