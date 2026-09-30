-- M4.2b SQL-only handoff for M3 completeness and independent accounting cross-checks.
-- Construction operands remain in financial_observation_component; this table
-- persists only the proof semantics that were previously available only in R2 artifacts.
CREATE TABLE financial_derivation_proof (
    fact_id TEXT PRIMARY KEY REFERENCES financial_observation_lineage(fact_id),
    proof_id TEXT NOT NULL UNIQUE REFERENCES evidence_reference(evidence_id),
    document_id TEXT NOT NULL REFERENCES document(document_id),
    target_concept TEXT NOT NULL CHECK(target_concept IN
      ('TOTAL_ASSETS','INTEREST_BEARING_DEBT')),
    relationship TEXT NOT NULL CHECK(relationship IN
      ('ASSET_SIDE','EXHAUSTIVE_INTEREST_BEARING')),
    page INTEGER NOT NULL CHECK(page >= 1),
    row_start INTEGER NOT NULL CHECK(row_start >= 1),
    row_end INTEGER NOT NULL CHECK(row_end >= row_start),
    evidence_text TEXT NOT NULL CHECK(length(trim(evidence_text)) > 0)
) STRICT;

CREATE TABLE financial_derivation_cross_check (
    fact_id TEXT NOT NULL REFERENCES financial_derivation_proof(fact_id),
    source_fact_id TEXT NOT NULL REFERENCES financial_source_fact(source_fact_id),
    position INTEGER NOT NULL CHECK(position >= 0),
    PRIMARY KEY(fact_id, position),
    UNIQUE(fact_id, source_fact_id)
) STRICT;

CREATE INDEX financial_derivation_cross_check_source
ON financial_derivation_cross_check(source_fact_id);

CREATE TRIGGER financial_derivation_proof_no_update
BEFORE UPDATE ON financial_derivation_proof
BEGIN SELECT RAISE(ABORT,'immutable financial derivation proof'); END;

CREATE TRIGGER financial_derivation_proof_no_delete
BEFORE DELETE ON financial_derivation_proof
BEGIN SELECT RAISE(ABORT,'immutable financial derivation proof'); END;

CREATE TRIGGER financial_derivation_cross_check_no_update
BEFORE UPDATE ON financial_derivation_cross_check
BEGIN SELECT RAISE(ABORT,'immutable financial derivation cross-check'); END;

CREATE TRIGGER financial_derivation_cross_check_no_delete
BEFORE DELETE ON financial_derivation_cross_check
BEGIN SELECT RAISE(ABORT,'immutable financial derivation cross-check'); END;
