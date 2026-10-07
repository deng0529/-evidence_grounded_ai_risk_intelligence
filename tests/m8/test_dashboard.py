"""Standalone dashboard reads snapshots, with helpful empty/failure responses."""
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from risk_intelligence.services.dashboard_snapshot import prepare_all_dashboard_snapshots, load_dashboard_snapshot, SnapshotUnavailable
from tests.m8.test_leaf_belief_test import seed
from tests.m8.test_application import environment
from tests.m2.conftest import NUMBER

ENTRY=Path(__file__).resolve().parents[2]/'streamlit_app.py'


def test_published_snapshot_deduplicates_and_view_never_calculates(database,storage,api,ixbrl,monkeypatch):
    seed(database,storage,api,ixbrl)
    prepare_all_dashboard_snapshots(database)
    first=load_dashboard_snapshot(database,NUMBER)
    prepare_all_dashboard_snapshots(database)
    assert len(database.query('SELECT * FROM dashboard_snapshot'))==1
    before='\n'.join(database._connection.iterdump())
    import risk_intelligence.services.reference_er as er
    def forbidden(*args,**kwargs): raise AssertionError('Viewing must not calculate')
    monkeypatch.setattr(er,'aggregate_reference_view',forbidden)
    assert load_dashboard_snapshot(database,NUMBER)==first
    assert before=='\n'.join(database._connection.iterdump())


def test_stale_or_missing_snapshot_gives_explicit_reason(database,storage,api,ixbrl):
    seed(database,storage,api,ixbrl)
    with pytest.raises(SnapshotUnavailable,match='no published'):
        load_dashboard_snapshot(database,NUMBER)
    prepare_all_dashboard_snapshots(database)
    database.execute("UPDATE dashboard_snapshot SET config_fingerprint='old'")
    with pytest.raises(SnapshotUnavailable,match='earlier configuration'):
        load_dashboard_snapshot(database,NUMBER)


def test_standalone_complete_ui_no_sidebar_or_writes(database,storage,api,ixbrl,tmp_path,monkeypatch):
    seed(database,storage,api,ixbrl)
    prepare_all_dashboard_snapshots(database)
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    before='\n'.join(database._connection.iterdump())
    at=AppTest.from_file(str(ENTRY),default_timeout=30).run()
    assert not at.exception and not at.error and not at.radio
    assert at.title[0].value=='Evidence-Grounded Company Risk MVP'
    assert at.selectbox[0].value is None and not at.dataframe
    assert len(at.get('image')) == 1
    assert [t.label for t in at.tabs]==['Overview','Domain analysis','Variables & standards','How it works']
    at.selectbox[0].set_value(NUMBER).run()
    assert not at.exception and not at.error and not at.warning
    assert not at.metric and len(at.get('vega_lite_chart'))==1
    tables=[t.value for t in at.dataframe]
    assert any(len(t)==6 and 'Value' in t.columns for t in tables)
    assert before=='\n'.join(database._connection.iterdump())
    assert not at.get('link_button')
    at.selectbox[0].set_value(None).run()
    assert not at.dataframe and 'dashboard_view' not in at.session_state


def test_missing_result_ui_and_connection_failure_have_responses(database,storage,api,ixbrl,tmp_path,monkeypatch):
    seed(database,storage,api,ixbrl)
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    at=AppTest.from_file(str(ENTRY),default_timeout=30).run()
    at.selectbox[0].set_value(NUMBER).run()
    assert not at.exception and not at.error and at.warning
    assert 'no published' in at.warning[0].value
    assert not at.dataframe
    monkeypatch.setenv('RISK_UI_DATABASE_PATH',str(tmp_path/'absent.sqlite3'))
    broken=AppTest.from_file(str(ENTRY),default_timeout=30).run()
    assert not broken.exception and not broken.error and broken.warning
    assert len(broken.tabs)==4 and broken.selectbox[0].disabled
    assert broken.button[0].label=='Retry connection'


def test_preparation_command_publishes_existing_data(database,storage,api,ixbrl,tmp_path,monkeypatch,capsys):
    seed(database,storage,api,ixbrl)
    environment(monkeypatch,tmp_path/'m2.sqlite3')
    from prepare_dashboard import main
    assert main()==0
    assert 'DASHBOARD_RESULTS_READY' in capsys.readouterr().out
    assert len(database.query('SELECT * FROM dashboard_snapshot'))==1


def test_architecture_is_an_actual_linked_image():
    import xml.etree.ElementTree as ET
    from risk_intelligence.ui.architecture import architecture_svg
    svg=ET.fromstring(architecture_svg())
    paths=[element for element in svg.iter() if element.tag.endswith('path') and element.get('marker-end')]
    text=' '.join(element.text or '' for element in svg.iter() if element.tag.endswith('text'))
    assert len(paths)==9
    for name in ('Companies House','Cloudflare R2','Turso','ER risk aggregation','Streamlit Community Cloud'):
        assert name in text
