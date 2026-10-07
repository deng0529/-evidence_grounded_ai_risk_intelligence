"""Saved-source leaf testing invokes M4/M5 only, replays SQL and explains uncertainty."""
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from risk_intelligence.services.leaf_belief_test import (
    calculate_saved_leaf_beliefs, saved_companies, leaf_explanation, reliability_rows,
)
from risk_intelligence.persistence.connection import IntegrityError
from risk_intelligence.services.data_foundation import load_foundation, latest_saved_run
from tests.maintenance.test_retain_latest import history  # noqa: F401
from tests.m2.conftest import NOW, NUMBER
from tests.m5.test_company_runner import services
from tests.m8.test_application import ENTRY, environment


def seed(database, storage, api, ixbrl):
    m2, m3, documents = services(database, storage, api, ixbrl)
    # A saved UI-style Foundation pair, with complete financial extraction.
    api.payloads['profile']['accounts']['next_accounts']['period_end_on'] = '2025-12-31'
    api.payloads['filing-history'][0]['description_values']['made_up_date'] = '2025-12-31'
    m2.ingest(NUMBER, NOW.date(), 'saved-m2')
    m3.ingest(NUMBER, NOW.date(), 'saved-m3', reporting_year=2025)
    return api, documents


def test_saved_leaf_button_never_ingests_or_fuses_and_replays_without_duplicates(database, storage, api, ixbrl, monkeypatch):
    seed(database, storage, api, ixbrl)
    before = load_foundation(database, 'saved-m2', 'saved-m3')
    import risk_intelligence.ingestion.accounts.service as accounts
    import risk_intelligence.ingestion.companies_house.service as governance
    import risk_intelligence.services.aggregation as aggregation
    def forbidden(*args, **kwargs): raise AssertionError('Only SQL validation and M5 are allowed')
    monkeypatch.setattr(accounts.AccountsIngestion, 'ingest', forbidden)
    monkeypatch.setattr(governance.CompaniesHouseIngestion, 'ingest', forbidden)
    monkeypatch.setattr(aggregation.AggregationService, 'calculate_and_persist', forbidden)
    view = calculate_saved_leaf_beliefs(database, NUMBER)
    assert len(view.leaves) == 6 and not view.reused
    assert view.assessment_date == NOW.date()
    assert view.foundation == before
    assert not database.query('SELECT * FROM m6_aggregation_result')
    counts = database.query('SELECT count(*) n FROM m5_variable_result')
    again = calculate_saved_leaf_beliefs(database, NUMBER)
    assert again.reused and again.leaves == view.leaves
    assert database.query('SELECT count(*) n FROM m5_variable_result') == counts == [{'n': 6}]
    assert load_foundation(database, 'saved-m2', 'saved-m3') == before
    for leaf in view.leaves:
        b = leaf.result.final_belief
        assert abs(b.high_belief + b.low_belief + b.unknown_belief - 1) < Decimal('1e-25')
        assert leaf_explanation(leaf)
        assert isinstance(reliability_rows(database, leaf), list)


def test_no_saved_company_fails_without_creating_runs(database):
    assert not saved_companies(database)
    with pytest.raises(IntegrityError, match='never starts ingestion'):
        calculate_saved_leaf_beliefs(database, NUMBER)
    assert not database.query('SELECT * FROM processing_run')


def test_leaf_ui_has_six_indicators_explanations_and_no_overall(database, storage, api, ixbrl, tmp_path, monkeypatch):
    seed(database, storage, api, ixbrl)
    environment(monkeypatch, tmp_path / 'm2.sqlite3')
    at = AppTest.from_file(str(ENTRY), default_timeout=30).run()
    at.radio[0].set_value('Six-variable belief test').run()
    assert not at.exception and not at.error
    assert not at.dataframe
    assert not database.query('SELECT * FROM m5_variable_result')
    assert at.selectbox[0].value is None
    at.selectbox[0].set_value(NUMBER).run()
    assert not any(button.label == 'Calculate six variable beliefs' for button in at.button)
    assert not at.exception and not at.error
    assert not at.expander
    assert not any(s.value == 'Overall risk belief' for s in at.subheader)
    headers = [s.value for s in at.subheader]
    assert headers.index('Six-variable risk beliefs') < headers.index('Risk reference standards') < headers.index('Calculation method and explanations')
    assert len(database.query('SELECT * FROM risk_reference_standard')) == 6
    assert len(at.dataframe) == 2
    assert list(at.dataframe[0].value.columns) == ['Variable', 'Value', 'Domain', 'Value basis / formula', 'Unit', 'High risk', 'Low risk', 'Unknown', 'Unknown reason']
    assert len(at.dataframe[0].value) == 6
    assert 'Code' not in at.dataframe[1].value.columns
    assert 'Equity Ratio' in list(at.dataframe[0].value['Variable'])
    assert 'Equity Ratio' in list(at.dataframe[1].value['Variable'])
    import re
    for column in ('High risk', 'Low risk', 'Unknown'):
        assert all(re.fullmatch(r'0\.\d{2}|1\.00', value) for value in at.dataframe[0].value[column])
    assert 'Reliability' not in at.dataframe[0].value.columns
    assert any('Unknown = 0.00' in c.value for c in at.code)
    assert not database.query('SELECT * FROM m5_variable_result')
    assert len(database.query('SELECT * FROM saved_reference_belief')) == 1
    at.run()
    assert not database.query('SELECT * FROM m5_variable_result')
    assert len(database.query('SELECT * FROM saved_reference_belief')) == 1


def test_saved_five_company_values_are_preserved_when_source_validation_is_unresolved(history):
    from risk_intelligence.maintenance.retain_latest import COMPANIES
    db, _, _ = history
    before = {n: load_foundation(db, *latest_saved_run(db, n)) for n in COMPANIES}
    for number in COMPANIES:
        view = calculate_saved_leaf_beliefs(db, number)
        leaves = {leaf.result.variable_code: leaf for leaf in view.leaves}
        expected = {'F1.1': Decimal('.1'), 'F2.2': Decimal('2'), 'F2.3': Decimal('1.5')}
        foundation_values = {code: value for code, value, _ in view.foundation.variables}
        assert foundation_values == expected
        # This maintenance fixture deliberately has unapproved synthetic mappings
        # and no source-scope heading. Numeric presence must not bypass M4.
        for code in expected:
            result = leaves[code].result
            assert result.raw_value is None
            assert result.provisional_belief is None
            assert result.final_belief.high_belief == result.final_belief.low_belief == 0
            assert result.final_belief.unknown_belief == 1
            assert any(row['Validation failures'] != 'None' for row in reliability_rows(db, leaves[code]))
        assert view.foundation == before[number]
    assert not db.query('SELECT * FROM m6_aggregation_result')


@pytest.mark.parametrize('code,value,expected_high', [
    ('G1.1', '45', '.5'), ('G1.2', '15', '.5'), ('G2.2', '3', '.5'),
    ('F1.1', '.05', '.5'), ('F2.2', '1.3', '.5'), ('F2.3', '.85', '.5'),
])
def test_explanation_reports_exact_transform_and_reliability_once(code, value, expected_high):
    from risk_intelligence.risk_variables.core import Calculation, ValidatedInput, make_leaf
    from risk_intelligence.domain.enums import AvailabilityStatus
    leaf = make_leaf(code=code, calculation=Calculation(value=Decimal(value),
        inputs=(ValidatedInput(kind='FACT', validated_id='synthetic-input', reliability_r=Decimal('.8'),
            validation_version='synthetic-validation', reliability_version='m4-reliability-v1'),),
        availability=AvailabilityStatus.AVAILABLE), assessment_id='synthetic-assessment', company_id='synthetic-company',
        company_number=NUMBER, assessment_date=NOW.date(), scope='COMPANY', calculated_at=NOW)
    assert leaf.result.provisional_belief.high_belief == Decimal(expected_high)
    assert leaf.result.final_belief.high_belief == leaf.result.final_belief.low_belief == Decimal('.4')
    assert leaf.result.final_belief.unknown_belief == Decimal('.2')
    explanation = leaf_explanation(leaf)
    assert 'minimum mandatory input reliability = 0.8' in explanation
    assert 'Unknown = 1 - r = 0.2' in explanation


def test_reference_standard_is_saved_once_and_same_version_drift_rolls_back(database):
    from risk_intelligence.services.leaf_belief_test import persist_reference_standard, reference_standard_rows
    persist_reference_standard(database)
    persist_reference_standard(database)
    rows = reference_standard_rows(database)
    assert len(rows) == 6
    assert [(r['Low risk reference'], r['High risk reference']) for r in rows] == [
        ('0','90'), ('0','30'), ('5','1'), ('0.10','0'), ('1.50','1.10'), ('1','0.70')]
    database.execute("UPDATE risk_reference_standard SET high_reference='91' WHERE variable_code='G1.1'")
    with pytest.raises(IntegrityError, match='version drift'):
        persist_reference_standard(database)


def test_upgrade_preserves_old_validation_ids_and_selects_only_new_handoff(database, storage, api, ixbrl, monkeypatch):
    seed(database, storage, api, ixbrl)
    import risk_intelligence.services.company_assessment as runner
    original = runner._identity
    def legacy_identity(*parts):
        return original('financial', *parts[1:]) if parts[0] == 'financial-subtotal-validation-v3' else original(*parts)
    monkeypatch.setattr(runner, '_identity', legacy_identity)
    runner.run_company_assessment(database, number=NUMBER, assessment_date=NOW.date(), reporting_year=2025,
        run_id='legacy-assessment', calculated_at=NOW, reuse_runs=('saved-m2','saved-m3'))
    old = database.query('SELECT * FROM validated_fact ORDER BY validated_fact_id')
    old_ids = {r['validated_fact_id'] for r in old}
    monkeypatch.setattr(runner, '_identity', original)
    view = calculate_saved_leaf_beliefs(database, NUMBER)
    for leaf in view.leaves:
        if leaf.result.variable_code.startswith('F'):
            assert not old_ids.intersection(i.validated_id for i in leaf.calculation.inputs)
    assert [r for r in database.query('SELECT * FROM validated_fact ORDER BY validated_fact_id')
            if r['validated_fact_id'] in old_ids] == old
    assert calculate_saved_leaf_beliefs(database, NUMBER).reused
