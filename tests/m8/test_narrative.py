"""An LLM can order supported sentences, never insert facts or omit uncertainty."""
import pytest
from risk_intelligence.services.application import AssessmentApplication
from risk_intelligence.services.narrative import SentenceOrder, assemble_narrative, sentence_catalog, NarrativeUnavailable, narrative_fingerprint
from risk_intelligence.services.model_config import load_model_configuration


def test_summary_retains_every_supported_sentence(database, assessed):
    view = AssessmentApplication(database).load(assessed[0].assessment_id)
    catalog = sentence_catalog(view)
    result = assemble_narrative(view, SentenceOrder(sentence_ids=list(reversed(catalog))))
    assert result[1:] == tuple(reversed(tuple(catalog.values())))
    assert 'Unknown' in result[0]


@pytest.mark.parametrize('order', [['invented'], [], ['G1.1'] * 6])
def test_unsupported_or_incomplete_summary_is_rejected(database, assessed, order):
    view = AssessmentApplication(database).load(assessed[0].assessment_id)
    with pytest.raises(NarrativeUnavailable):
        assemble_narrative(view, SentenceOrder(sentence_ids=order))


def test_summary_cache_changes_with_model(database, assessed):
    view = AssessmentApplication(database).load(assessed[0].assessment_id)
    config = load_model_configuration({})
    assert narrative_fingerprint(view, config) != narrative_fingerprint(view, config.model_copy(update={'explanation_model': 'other'}))
