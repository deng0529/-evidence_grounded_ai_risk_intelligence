-- M4.0a handoff only; existing interpretation and evidence records stay immutable.
CREATE TABLE financial_semantic_support (
    interpretation_id TEXT PRIMARY KEY REFERENCES financial_interpretation(interpretation_id),
    schema_version TEXT NOT NULL CHECK(schema_version='financial-semantic-support-v1'),
    rationale TEXT NOT NULL CHECK(length(trim(rationale))>0),
    context_json TEXT NOT NULL CHECK(json_valid(context_json) AND json_type(context_json)='object')
) STRICT;
CREATE TRIGGER semantic_support_no_update BEFORE UPDATE ON financial_semantic_support
BEGIN SELECT RAISE(ABORT,'immutable semantic support'); END;
CREATE TRIGGER semantic_support_no_delete BEFORE DELETE ON financial_semantic_support
BEGIN SELECT RAISE(ABORT,'retain semantic support'); END;
CREATE TRIGGER semantic_support_accepted BEFORE INSERT ON financial_semantic_support
WHEN NOT EXISTS (SELECT 1 FROM financial_interpretation i
    WHERE i.interpretation_id=NEW.interpretation_id AND i.status='AVAILABLE'
      AND i.method='LLM_SEMANTIC' AND i.source_fact_id IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'semantic support requires accepted semantic normalization'); END;
