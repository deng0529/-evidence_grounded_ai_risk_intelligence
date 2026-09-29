-- Queryable admission outcomes; full proposals/context remain immutable R2 artifacts.
CREATE TABLE financial_interpretation (
    interpretation_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(document_id),
    source_fact_id TEXT REFERENCES financial_source_fact(source_fact_id),
    canonical_fact_id TEXT REFERENCES fact(fact_id),
    artifact_raw_id TEXT NOT NULL REFERENCES raw_evidence(raw_evidence_id),
    llm_artifact_raw_id TEXT REFERENCES raw_evidence(raw_evidence_id),
    target_concept TEXT NOT NULL CHECK(target_concept IN
      ('CURRENT_ASSETS','CURRENT_LIABILITIES','INVENTORY','NET_ASSETS','TOTAL_ASSETS','INTEREST_BEARING_DEBT')),
    period_end TEXT NOT NULL,
    method TEXT NOT NULL CHECK(method IN
      ('DETERMINISTIC_MAPPING','DETERMINISTIC_DERIVATION','LLM_SEMANTIC','LLM_DERIVATION')),
    status TEXT NOT NULL CHECK(status IN ('AVAILABLE','VALIDATION_FAILED','SUPERSEDED')),
    rule_version TEXT NOT NULL,
    reason TEXT NOT NULL,
    CHECK((status='AVAILABLE') = (canonical_fact_id IS NOT NULL))
) STRICT;
CREATE INDEX financial_interpretation_document ON financial_interpretation(document_id, target_concept, period_end);
CREATE TRIGGER financial_interpretation_no_update BEFORE UPDATE ON financial_interpretation
BEGIN SELECT RAISE(ABORT,'immutable financial interpretation'); END;
CREATE TRIGGER financial_interpretation_no_delete BEFORE DELETE ON financial_interpretation
BEGIN SELECT RAISE(ABORT,'immutable financial interpretation'); END;
