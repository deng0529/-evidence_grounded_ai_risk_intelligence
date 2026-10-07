CREATE TABLE reference_narrative (
 fingerprint TEXT PRIMARY KEY,
 calculation_id TEXT NOT NULL REFERENCES saved_reference_belief(calculation_id),
 variable_code TEXT NOT NULL,
 model TEXT NOT NULL,
 prompt_version TEXT NOT NULL,
 payload TEXT NOT NULL CHECK(json_valid(payload))
) STRICT;
CREATE TABLE reference_source_audit (
 calculation_id TEXT PRIMARY KEY REFERENCES saved_reference_belief(calculation_id),
 assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id)
) STRICT;
