-- M4 validated analytical evidence only; no risk variables, beliefs or ER aggregation.

CREATE TABLE validated_fact (
    validated_fact_id TEXT PRIMARY KEY NOT NULL,
    fact_id TEXT NOT NULL REFERENCES fact(fact_id),
    company_id TEXT NOT NULL,
    company_number TEXT NOT NULL,
    processing_run_id TEXT NOT NULL,
    assessment_date TEXT NOT NULL,

    canonical_concept TEXT NOT NULL,

    -- Frozen analytical observation consumed by M5.
    -- fact_id remains the backward lineage edge to M3.
    value_numeric TEXT,
    currency TEXT,
    unit TEXT,
    period_type TEXT CHECK(
        period_type IS NULL OR period_type IN ('INSTANT','DURATION')
    ),
    period_start TEXT,
    period_end TEXT,
    period_length_days INTEGER CHECK(
        period_length_days IS NULL OR period_length_days >= 1
    ),
    comparability_status TEXT CHECK(
        comparability_status IS NULL OR comparability_status IN (
            'COMPARABLE','NON_COMPARABLE','REVIEW_REQUIRED','NOT_APPLICABLE'
        )
    ),
    source_id TEXT NOT NULL,
    document_id TEXT,
    evidence_ids_json TEXT NOT NULL
        CHECK(json_valid(evidence_ids_json)
          AND json_type(evidence_ids_json)='array'),

    availability_status TEXT NOT NULL CHECK(availability_status IN (
        'AVAILABLE','NOT_DISCLOSED','NOT_APPLICABLE','RETRIEVAL_FAILED',
        'EXTRACTION_FAILED','VALIDATION_FAILED','CONFLICT_UNRESOLVED',
        'NON_COMPARABLE'
    )),

    provenance_type TEXT NOT NULL CHECK(provenance_type IN ('DIRECT','DERIVED')),
    normalization_method TEXT,
    derivation_method TEXT,

    transformation_chain_json TEXT NOT NULL
        CHECK(json_valid(transformation_chain_json)
          AND json_type(transformation_chain_json)='array'),
    critical_transformation TEXT NOT NULL CHECK(critical_transformation IN (
        'STRUCTURED_DETERMINISTIC',
        'TAGGED_IXBRL_DETERMINISTIC',
        'NATIVE_PDF_DETERMINISTIC',
        'OCR_DETERMINISTIC',
        'GROUNDED_LLM_SEMANTIC',
        'COMPLEX_LLM_INTERPRETATION',
        'UNSUPPORTED_LLM_NUMERIC'
    )),

    validation_report_json TEXT NOT NULL CHECK(json_valid(validation_report_json)),
    conflict_state_json TEXT NOT NULL CHECK(json_valid(conflict_state_json)),

    source_quality_s TEXT NOT NULL,
    extraction_quality_e TEXT NOT NULL,
    validation_factor_v TEXT NOT NULL,
    conflict_factor_c TEXT NOT NULL,
    reliability_r TEXT NOT NULL,

    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'PASS','FAIL','INCONCLUSIVE','NOT_APPLICABLE'
    )),
    validation_ruleset_version TEXT NOT NULL,
    reliability_policy_version TEXT NOT NULL,

    FOREIGN KEY(company_id, company_number)
        REFERENCES company(company_id, company_number),
    FOREIGN KEY(processing_run_id, company_id)
        REFERENCES processing_run(processing_run_id, company_id),

    CHECK(length(trim(validation_ruleset_version)) > 0),
    CHECK(length(trim(reliability_policy_version)) > 0)
) STRICT;

CREATE TABLE validated_evidence_set (
    validated_evidence_set_id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL,
    company_number TEXT NOT NULL,
    processing_run_id TEXT NOT NULL,
    assessment_date TEXT NOT NULL,

    evidence_set_type TEXT NOT NULL,
    analytical_window_start TEXT NOT NULL,
    analytical_window_end TEXT NOT NULL,

    source_resources_json TEXT NOT NULL
        CHECK(json_valid(source_resources_json)
          AND json_type(source_resources_json)='array'),

    availability_status TEXT NOT NULL CHECK(availability_status IN (
        'AVAILABLE','NOT_DISCLOSED','NOT_APPLICABLE','RETRIEVAL_FAILED',
        'EXTRACTION_FAILED','VALIDATION_FAILED','CONFLICT_UNRESOLVED',
        'NON_COMPARABLE'
    )),

    validation_report_json TEXT NOT NULL CHECK(json_valid(validation_report_json)),
    conflict_state_json TEXT NOT NULL CHECK(json_valid(conflict_state_json)),

    source_quality_s TEXT NOT NULL,
    extraction_quality_e TEXT NOT NULL,
    validation_factor_v TEXT NOT NULL,
    conflict_factor_c TEXT NOT NULL,
    reliability_r TEXT NOT NULL,

    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'PASS','FAIL','INCONCLUSIVE','NOT_APPLICABLE'
    )),
    validation_ruleset_version TEXT NOT NULL,
    reliability_policy_version TEXT NOT NULL,

    FOREIGN KEY(company_id, company_number)
        REFERENCES company(company_id, company_number),
    FOREIGN KEY(processing_run_id, company_id)
        REFERENCES processing_run(processing_run_id, company_id),

    CHECK(analytical_window_start <= analytical_window_end),
    CHECK(length(trim(evidence_set_type)) > 0),
    CHECK(length(trim(validation_ruleset_version)) > 0),
    CHECK(length(trim(reliability_policy_version)) > 0)
) STRICT;

CREATE TABLE validated_evidence_set_snapshot (
    validated_evidence_set_id TEXT NOT NULL
        REFERENCES validated_evidence_set(validated_evidence_set_id),
    position INTEGER NOT NULL CHECK(position >= 0),
    snapshot_id TEXT NOT NULL REFERENCES resource_snapshot(snapshot_id),
    PRIMARY KEY(validated_evidence_set_id, position),
    UNIQUE(validated_evidence_set_id, snapshot_id)
) STRICT;

CREATE INDEX validated_fact_company_concept
    ON validated_fact(company_id, canonical_concept, assessment_date);

CREATE INDEX validated_fact_run
    ON validated_fact(processing_run_id);

CREATE INDEX validated_set_company_type
    ON validated_evidence_set(company_id, evidence_set_type, assessment_date);

CREATE INDEX validated_set_run
    ON validated_evidence_set(processing_run_id);

CREATE TRIGGER validated_fact_no_update
BEFORE UPDATE ON validated_fact
BEGIN
    SELECT RAISE(ABORT,'immutable M4 validated fact');
END;

CREATE TRIGGER validated_fact_no_delete
BEFORE DELETE ON validated_fact
BEGIN
    SELECT RAISE(ABORT,'immutable M4 validated fact');
END;

CREATE TRIGGER validated_set_no_update
BEFORE UPDATE ON validated_evidence_set
BEGIN
    SELECT RAISE(ABORT,'immutable M4 validated evidence set');
END;

CREATE TRIGGER validated_set_no_delete
BEFORE DELETE ON validated_evidence_set
BEGIN
    SELECT RAISE(ABORT,'immutable M4 validated evidence set');
END;

CREATE TRIGGER validated_set_snapshot_no_update
BEFORE UPDATE ON validated_evidence_set_snapshot
BEGIN
    SELECT RAISE(ABORT,'immutable M4 evidence-set lineage');
END;

CREATE TRIGGER validated_set_snapshot_no_delete
BEFORE DELETE ON validated_evidence_set_snapshot
BEGIN
    SELECT RAISE(ABORT,'immutable M4 evidence-set lineage');
END;
