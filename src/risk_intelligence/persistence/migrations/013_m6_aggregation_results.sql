-- Immutable M6 parent beliefs and exact weighted child lineage.
CREATE TABLE m6_aggregation_result (
    aggregation_result_id TEXT PRIMARY KEY NOT NULL,
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    node_code TEXT NOT NULL CHECK(node_code IN ('G1','G2','G3','F1','F2','F3','GOVERNANCE','FINANCIAL','OVERALL')),
    node_type TEXT NOT NULL CHECK(node_type IN ('INDICATOR','DOMAIN','OVERALL')),
    er_model_version TEXT NOT NULL,
    low_belief TEXT NOT NULL,
    high_belief TEXT NOT NULL,
    unknown_belief TEXT NOT NULL,
    record_json TEXT NOT NULL CHECK(json_valid(record_json)),
    UNIQUE(assessment_id, node_code)
) STRICT;
CREATE TABLE m6_aggregation_input (
    aggregation_result_id TEXT NOT NULL REFERENCES m6_aggregation_result(aggregation_result_id),
    position INTEGER NOT NULL CHECK(position >= 0),
    child_code TEXT NOT NULL,
    child_result_id TEXT NOT NULL,
    importance_weight TEXT NOT NULL,
    PRIMARY KEY(aggregation_result_id, position),
    UNIQUE(aggregation_result_id, child_code)
) STRICT;
CREATE TRIGGER m6_result_no_update BEFORE UPDATE ON m6_aggregation_result
BEGIN SELECT RAISE(ABORT,'immutable M6 result'); END;
CREATE TRIGGER m6_result_no_delete BEFORE DELETE ON m6_aggregation_result
BEGIN SELECT RAISE(ABORT,'immutable M6 result'); END;
CREATE TRIGGER m6_input_no_update BEFORE UPDATE ON m6_aggregation_input
BEGIN SELECT RAISE(ABORT,'immutable M6 input'); END;
CREATE TRIGGER m6_input_no_delete BEFORE DELETE ON m6_aggregation_input
BEGIN SELECT RAISE(ABORT,'immutable M6 input'); END;
