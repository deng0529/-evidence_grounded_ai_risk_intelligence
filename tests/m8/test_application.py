"""M8 verifies exact wiring, deliberate writes and fail-safe presentation."""

from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from risk_intelligence.persistence.connection import IntegrityError, PersistenceError
from risk_intelligence.services.application import AssessmentApplication, belief_row, error_message, variable_row
from risk_intelligence.services.presentation import belief_display, variable_display
from risk_intelligence.services.application_runtime import application_database
from risk_intelligence.services.explanation import ExplanationService
from tests.m2.conftest import NOW, NUMBER
from tests.m5.test_company_runner import services
from tests.m5.test_obligations import prepare
from tests.m6.test_service import context

ENTRY = Path(__file__).resolve().parents[2] / 'maintenance_app.py'


def test_exact_view_hierarchy_beliefs_reliability_year_and_trace(database, assessed):
    report, parents = assessed
    app = AssessmentApplication(database)
    view = app.load(report.assessment_id)
    assert view == app.load(report.assessment_id)
    assert view.explanation == ExplanationService(database).for_assessment(report.assessment_id)
    assert tuple(v.leaf for v in view.explanation.variables) == report.leaves
    assert tuple(v.leaf.result.variable_code for v in view.explanation.variables) == ('G1.1','G1.2','G2.2','F1.1','F2.2','F2.3')
    assert [tuple(e.child_code for e in d.children) for d in view.explanation.domains] == [('G1.1','G1.2','G2.2'),('F1.1','F2.2','F2.3')]
    assert [e.importance_weight for e in view.explanation.overall.children] == [Decimal('.40'),Decimal('.60')]
    assert tuple(d.result for d in view.explanation.domains)+(view.explanation.overall.result,) == parents
    for node in (*view.explanation.domains,view.explanation.overall):
        assert belief_row(node.result.belief) == {key:str(getattr(node.result.belief,name)) for key,name in
            [('Low','low_belief'),('High','high_belief'),('Unknown','unknown_belief')]}
    for variable in view.explanation.variables:
        row=variable_row(variable)
        assert row['Reliability']==str(variable.leaf.result.reliability_r)
        assert row['Unknown']==str(variable.leaf.result.final_belief.unknown_belief)
        assert variable.reporting_year == (2025 if variable.domain=='FINANCIAL' else None)
        for item in variable.inputs:
            assert item.reference in variable.leaf.calculation.inputs
            if item.reference.kind=='FACT':
                assert item.record.value_numeric==item.observations[0].value_numeric
                assert item.reference.reliability_r==item.record.reliability_r
                if item.record.value_numeric is None:
                    assert item.financial_lineage is None
    assert view.explanation.assessment.assessment_date==NOW.date()
    assert view.explanation.reporting_year==2025
    assert database.query('PRAGMA foreign_key_check')==[]


def test_unknown_and_optional_provenance_are_not_replaced(database, assessed):
    view=AssessmentApplication(database).load(assessed[0].assessment_id)
    unknown=[v for v in view.explanation.variables if v.leaf.result.raw_value is None]
    assert unknown
    for v in unknown:
        row=variable_row(v)
        assert row['Raw value']=='Unavailable'
        assert Decimal(row['Unknown'])==1
        assert row['Availability']==v.leaf.result.availability_status.value
        assert row['Reason']==', '.join(r.value for r in v.leaf.calculation.reasons)
    assert any(e.document is None for v in view.explanation.variables for i in v.inputs for e in i.evidence)


def test_view_cannot_call_math_or_mutate_database(database, assessed, monkeypatch):
    import risk_intelligence.aggregation as er
    import risk_intelligence.services.aggregation as aggregation
    import risk_intelligence.risk_variables.core as core
    import risk_intelligence.persistence.variable_repository as repository
    import risk_intelligence.validation.policy as policy
    before=database.query('SELECT * FROM m5_variable_result ORDER BY variable_result_id')
    def forbidden(*args,**kwargs):
        raise AssertionError('Viewing must not calculate or write')
    for obj,name in [(er,'er_aggregate'),(aggregation,'er_aggregate'),(core,'make_leaf'),
                     (repository,'make_leaf'),(policy,'assess_reliability'),(database,'execute')]:
        monkeypatch.setattr(obj,name,forbidden)
    app=AssessmentApplication(database)
    assert app.choices()
    assert app.load(assessed[0].assessment_id)
    assert before==database.query('SELECT * FROM m5_variable_result ORDER BY variable_result_id')


def test_deliberate_run_calls_production_pipeline_and_reuse_without_network(database, storage, api, ixbrl):
    m2,m3,documents=services(database,storage,api,ixbrl)
    app=AssessmentApplication(database)
    first=app.create(number=NUMBER,assessment_date=NOW.date(),reporting_year=2025,run_id='m8-first',
                     calculated_at=NOW,m2=m2,m3=m3)
    calls=(tuple(api.calls),tuple(documents.calls))
    second=app.create(number=NUMBER,assessment_date=NOW.date(),reporting_year=2025,run_id='m8-second',
                      calculated_at=NOW,reuse_runs=('m8-first-m2','m8-first-m3'))
    assert (tuple(api.calls),tuple(documents.calls))==calls
    assert first.explanation.overall.result.belief==second.explanation.overall.result.belief
    assert len(app.choices())==2
    assert database.query('PRAGMA foreign_key_check')==[]


@pytest.mark.parametrize('version',['1','1.1'])
def test_historical_assessment_error_is_safe(database,storage,api,version):
    obligation=prepare(database,storage,api)
    context(database,obligation,version)
    with pytest.raises(IntegrityError) as failure:
        AssessmentApplication(database).load('m5')
    assert error_message(failure.value).code=='UNSUPPORTED_MODEL'


@pytest.mark.parametrize('error,code',[
    (IntegrityError('M7 missing persisted assessment'),'NOT_FOUND'),
    (IntegrityError('M7 requires the persisted M6 domains and Overall'),'MISSING_AGGREGATION'),
    (IntegrityError('M7 requires exactly the persisted active M5 leaves'),'INCOMPLETE_VARIABLES'),
    (IntegrityError('M7 missing persisted validated fact'),'MISSING_FACT'),
    (IntegrityError('M7 missing persisted evidence reference'),'MISSING_PROVENANCE'),
    (PersistenceError('SYNTHETIC_PRIVATE_TOKEN'),'DATABASE'),
    (RuntimeError('SYNTHETIC_PRIVATE_TOKEN'),'SERVICE'),
])
def test_error_translation_does_not_expose_provider_text(error,code):
    message=error_message(error)
    assert message.code==code
    assert 'SYNTHETIC_PRIVATE_TOKEN' not in message.message


def environment(monkeypatch,path):
    monkeypatch.setenv('RISK_ENVIRONMENT','test')
    monkeypatch.setenv('RISK_DATABASE_BACKEND','sqlite')
    monkeypatch.setenv('RISK_EVIDENCE_STORAGE_BACKEND','local')
    monkeypatch.setenv('RISK_UI_DATABASE_PATH',str(path))


def load_existing_mode(at):
    """M8 assessment tests explicitly enter the assessment workflow; Foundation is the MVP default."""
    return at.radio[0].set_value('Load existing assessment').run()


def test_readonly_runtime_and_missing_database_never_created(database,tmp_path):
    values={'RISK_UI_DATABASE_PATH':str(tmp_path/'m2.sqlite3')}
    with application_database(values) as reader:
        with pytest.raises(PersistenceError):
            reader.execute('CREATE TABLE forbidden(value TEXT)')
    missing=tmp_path/'missing.sqlite3'
    with pytest.raises(PersistenceError):
        with application_database({'RISK_UI_DATABASE_PATH':str(missing)}):
            pass
    assert not missing.exists()


def test_streamlit_load_and_trace_display_exact_persisted_values(database,assessed,tmp_path,monkeypatch):
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    at=load_existing_mode(AppTest.from_file(str(ENTRY),default_timeout=30).run())
    assert not at.exception and not at.error
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert at.dataframe[0].value.iloc[0].to_dict()==belief_display(assessed[1][-1].belief)
    variables=at.dataframe[2].value
    assert 'Code' not in variables.columns
    assert len(variables) == 6
    assert 'Unknown' in variables.columns
    next(s for s in at.selectbox if s.label=='Variable').select(next(v.name for v in AssessmentApplication(database).load(assessed[0].assessment_id).explanation.variables if v.leaf.result.variable_code=='F1.1')).run()
    assert not at.exception and not at.error
    assert any(e.label=='Technical audit details' for e in at.expander)


def test_streamlit_empty_and_database_errors_have_no_traceback(database,tmp_path,monkeypatch):
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    at=load_existing_mode(AppTest.from_file(str(ENTRY),default_timeout=30).run())
    assert not at.exception and at.info
    environment(monkeypatch,tmp_path/'absent.sqlite3')
    at=load_existing_mode(AppTest.from_file(str(ENTRY),default_timeout=30).run())
    assert not at.exception and at.error
    assert at.error[0].value == error_message(PersistenceError()).message


def test_streamlit_service_failure_clears_stale_view(database,assessed,tmp_path,monkeypatch):
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    at=load_existing_mode(AppTest.from_file(str(ENTRY),default_timeout=30).run())
    at.button[0].click().run()
    def fail(*args,**kwargs):
        raise RuntimeError('SYNTHETIC_PRIVATE_TOKEN')
    monkeypatch.setattr(AssessmentApplication,'load',fail)
    at.button[0].click().run()
    assert not at.exception and at.error
    assert 'SYNTHETIC_PRIVATE_TOKEN' not in at.error[0].value
    assert not at.dataframe


def test_streamlit_new_assessment_reuses_real_production_runs(database, assessed, tmp_path, monkeypatch):
    environment(monkeypatch, tmp_path / 'm2.sqlite3')
    report, _ = assessed
    at = AppTest.from_file(str(ENTRY), default_timeout=30).run()
    at.radio[0].set_value('New assessment').run()
    assert not at.exception and not at.error
    next(w for w in at.text_input if w.label == 'Company number').set_value(NUMBER)
    at.date_input[0].set_value(NOW.date())
    next(w for w in at.number_input if w.label == 'Financial reporting year').set_value(2025)
    assert [w.label for w in at.text_input] == ['Company number']
    assert [w.label for w in at.number_input] == ['Financial reporting year']
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert at.success
    assert len(at.dataframe[2].value) == 6
    assert len(AssessmentApplication(database).choices()) == 1
    assert database.query('PRAGMA foreign_key_check') == []


def test_exact_context_reuse_never_substitutes_company_year_or_date(database, assessed):
    from datetime import timedelta
    application = AssessmentApplication(database)
    view = application.existing(number=NUMBER, reporting_year=2025, assessment_date=NOW.date())
    assert view is not None
    assert application.existing(number='ZZ000003', reporting_year=2025, assessment_date=NOW.date()) is None
    assert application.existing(number=NUMBER, reporting_year=2024, assessment_date=NOW.date()) is None
    assert application.existing(number=NUMBER, reporting_year=2025, assessment_date=NOW.date()+timedelta(days=1)) is None


def test_changing_reporting_year_clears_previous_result(database, assessed, storage, api, ixbrl, tmp_path, monkeypatch):
    environment(monkeypatch, tmp_path / 'm2.sqlite3')
    # A different reporting year requires its own valid M3 selection; a 2025 M3
    # run must never be relabelled/reused as 2024.
    shifted = ixbrl.replace(b'2024-12-31', b'2023-12-31').replace(b'2025-12-31', b'2024-12-31')
    m2, m3, _ = services(database, storage, api, shifted)
    AssessmentApplication(database).create(number=NUMBER, assessment_date=NOW.date(), reporting_year=2024,
        run_id='other-year', calculated_at=NOW, m2=m2, m3=m3)
    at = load_existing_mode(AppTest.from_file(str(ENTRY), default_timeout=30).run())
    at.button[0].click().run()
    assert at.dataframe
    year = next(w for w in at.selectbox if w.label == 'Financial reporting year')
    year.select(2025 if year.value == 2024 else 2024).run()
    assert not at.exception and not at.error and not at.dataframe


def test_summary_failure_keeps_supported_result(database, assessed, tmp_path, monkeypatch):
    from risk_intelligence.ui import streamlit_app as ui
    from risk_intelligence.services.narrative import NarrativeUnavailable
    environment(monkeypatch, tmp_path / 'm2.sqlite3')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic')
    def fail(*args):
        raise NarrativeUnavailable('synthetic secret must not appear')
    monkeypatch.setattr(ui, 'generate_narrative', fail)
    at = load_existing_mode(AppTest.from_file(str(ENTRY), default_timeout=30).run())
    at.button[0].click().run()
    next(b for b in at.button if b.label == 'Prepare evidence-grounded summary').click().run()
    assert not at.exception and not at.error
    assert len(at.dataframe[2].value) == 6
    assert any('Summary assistance is unavailable' in item.value for item in at.info)


def test_summary_cached_rerender_never_repeats_request(database, assessed, tmp_path, monkeypatch):
    from risk_intelligence.ui import streamlit_app as ui
    environment(monkeypatch, tmp_path / 'm2.sqlite3')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic')
    calls = []
    def summary(*args):
        calls.append(args); return ('Verified summary sentence.',)
    monkeypatch.setattr(ui, 'generate_narrative', summary)
    at = load_existing_mode(AppTest.from_file(str(ENTRY), default_timeout=30).run())
    at.button[0].click().run()
    next(b for b in at.button if b.label == 'Prepare evidence-grounded summary').click().run()
    next(b for b in at.button if b.label == 'Prepare evidence-grounded summary').click().run()
    assert not at.exception and not at.error and len(calls) == 1
