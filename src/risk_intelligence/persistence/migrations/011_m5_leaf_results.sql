-- Immutable M5 leaf results and exact validated-input lineage; no ER aggregation.
CREATE TABLE m5_variable_result (
    variable_result_id TEXT PRIMARY KEY NOT NULL,
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    variable_code TEXT NOT NULL CHECK(variable_code IN
        ('G1.1','G1.2','G2.1','G2.2','G2.3','G3.1','F1.1','F1.2','F2.2','F2.3','F3.1')),
    reliability_id TEXT NOT NULL UNIQUE,
    raw_value TEXT,
    reliability_r TEXT NOT NULL,
    low_belief TEXT NOT NULL,
    high_belief TEXT NOT NULL,
    unknown_belief TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    record_json TEXT NOT NULL CHECK(json_valid(record_json)),
    UNIQUE(assessment_id, variable_code)
) STRICT;
CREATE TABLE m5_validated_input (
    variable_result_id TEXT NOT NULL REFERENCES m5_variable_result(variable_result_id),
    position INTEGER NOT NULL CHECK(position >= 0),
    validated_fact_id TEXT REFERENCES validated_fact(validated_fact_id),
    validated_evidence_set_id TEXT REFERENCES validated_evidence_set(validated_evidence_set_id),
    validated_obligation_id TEXT REFERENCES validated_obligation(validated_obligation_id),
    mandatory INTEGER NOT NULL CHECK(mandatory IN (0,1)),
    PRIMARY KEY(variable_result_id, position),
    CHECK((validated_fact_id IS NOT NULL) + (validated_evidence_set_id IS NOT NULL)
        + (validated_obligation_id IS NOT NULL) = 1)
) STRICT;
CREATE TRIGGER m5_result_no_update BEFORE UPDATE ON m5_variable_result
BEGIN SELECT RAISE(ABORT,'immutable M5 leaf'); END;
CREATE TRIGGER m5_result_no_delete BEFORE DELETE ON m5_variable_result
BEGIN SELECT RAISE(ABORT,'immutable M5 leaf'); END;
CREATE TRIGGER m5_input_no_update BEFORE UPDATE ON m5_validated_input
BEGIN SELECT RAISE(ABORT,'immutable M5 input'); END;
CREATE TRIGGER m5_input_no_delete BEFORE DELETE ON m5_validated_input
BEGIN SELECT RAISE(ABORT,'immutable M5 input'); END;
