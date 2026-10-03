"""Regression: canonical cleaning must not add a second persistence gate."""
from pathlib import Path


def test_normalization_is_in_canonical_path_without_auxiliary_audit_write():
    text = (Path(__file__).resolve().parents[2] / 'src/risk_intelligence/ingestion/accounts/service.py').read_text(encoding='utf-8')
    assert 'normalize_source_fact(extracted_fact)' in text
    assert 'normalize_canonical_fact(canonical, fact)' in text
    assert 'save_normalization_audit(' not in text
