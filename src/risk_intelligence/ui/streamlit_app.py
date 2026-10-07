"""M8.1 Streamlit UI: user-first risk explanation over frozen M4-M7 outputs."""
from datetime import UTC, date, datetime
from hashlib import sha256
import os
import json
from decimal import Decimal
from uuid import uuid4
import streamlit as st

from risk_intelligence.ingestion.accounts.coverage import read_coverage, coverage_text, coverage_rows
from risk_intelligence.config import load_settings
from risk_intelligence.services.leaf_belief_test import (
    saved_companies,
)
from risk_intelligence.services.reference_presentation import summary_rows, standards_rows, calculation_explanation
from risk_intelligence.services.saved_reference_beliefs import calculate_saved_reference_beliefs
from risk_intelligence.services.reference_er import (calculate_saved_reference_er, node_rows, child_rows, chart_rows, node_explanation)
from risk_intelligence.explanation import InputExplanation
from risk_intelligence.services.application import AssessmentApplication, AssessmentView, display_value, error_message
from risk_intelligence.services.application_runtime import application_database, ingestion_services
from risk_intelligence.services.data_foundation import existing_run, load_foundation, latest_saved_run
from risk_intelligence.services.model_config import load_model_configuration, RuntimeConfigurationError
from risk_intelligence.services.narrative import generate_narrative, narrative_fingerprint, NarrativeUnavailable
from risk_intelligence.services.presentation import belief_display, risk_sentence, two_dp, variable_display
from risk_intelligence.storage.local import LocalStorage
from risk_intelligence.storage.r2 import R2Storage
from risk_intelligence.ingestion.companies_house.policy import Resource


def _show_error(error: Exception) -> None:
    message = error_message(error)
    st.error(message.message)


def _select_existing(environ: dict[str, str]) -> None:
    with application_database(environ) as database:
        choices = tuple(c for c in AssessmentApplication(database).choices() if c.assessment.risk_model_version == '1.2')
        if not choices:
            st.info('No completed assessments are available in this database.')
            st.session_state.pop('assessment_view', None); return
        numbers = tuple(dict.fromkeys(c.assessment.company_number for c in choices))
        names = {c.assessment.company_number: c.company_name for c in choices}
        number = st.selectbox('Company', numbers, format_func=lambda n: names[n] or n)
        candidates = tuple(c for c in choices if c.assessment.company_number == number)
        years = tuple(dict.fromkeys(c.reporting_year for c in candidates))
        year = st.selectbox('Financial reporting year', years, format_func=display_value)
        selected = tuple(c for c in candidates if c.reporting_year == year)
        # Multiple persisted runs are an audit concern, not a user choice. Use the latest listed v1.2 assessment.
        choice = selected[0]
        selection = (number, year, choice.assessment.assessment_id)
        if st.session_state.get('assessment_selection') != selection:
            st.session_state.pop('assessment_view', None)
            st.session_state.assessment_selection = selection
        if st.button('Load assessment', type='primary'):
            with st.spinner('Loading assessment and supporting evidence…'):
                st.session_state.assessment_view = AssessmentApplication(database).load(choice.assessment.assessment_id)


def _new_assessment(environ: dict[str, str]) -> None:
    settings = load_settings(environ)
    with st.form('new_assessment'):
        number = st.text_input('Company number', max_chars=8,
                               help='Use the Companies House company number. If you only know the company name, use the official register search link below.')
        st.markdown('[Find a company number on Companies House](https://find-and-update.company-information.service.gov.uk/)')
        day = st.date_input('Assessment date', value=date.today())
        year = st.number_input('Financial reporting year', min_value=1900, max_value=9999, value=None, step=1)
        refresh = st.checkbox('Refresh source evidence', value=False,
                              help='Reuse an existing assessment for the same company, year and assessment date unless refresh is selected.')
        submitted = st.form_submit_button('Run new assessment', type='primary')
    if not submitted: return
    st.session_state.pop('assessment_view', None)
    if year is None or not number.strip(): st.error('Enter a company number and reporting year.'); return
    run_id = 'ui-' + uuid4().hex
    with st.spinner('Collecting, validating and assessing evidence…'):
        with application_database(environ, write=refresh) as database:
            application = AssessmentApplication(database)
            existing = None if refresh else application.existing(
                number=number, reporting_year=int(year), assessment_date=day)
            if existing is not None:
                st.session_state.assessment_view = existing
            else:
                m2, m3 = ingestion_services(database, settings, environ, enable_llm=False)
                st.session_state.assessment_view = application.create(
                    number=number, assessment_date=day, reporting_year=int(year), run_id=run_id,
                    calculated_at=datetime.now(UTC), m2=m2, m3=m3, max_documents=5)
    st.success('Assessment loaded from recorded evidence.' if existing is not None else 'Assessment processed. Review the results and evidence gaps below.')



def _foundation(environ: dict[str, str]) -> None:
    """Observable A-E acceptance runner; every external boundary is shown separately."""
    settings = load_settings(environ)
    with st.form('data_foundation'):
        company_options = {
            'LODI — 05127466': '05127466',
            'Westpoint Homes Limited — SC137690': 'SC137690',
            'Pip & Nut — 08624397': '08624397',
            'Country Style Foods Limited — 02554051': '02554051',
            'HP Foods Limited — 02251694': '02251694',
            'Other company — enter Companies House number': None,
        }
        company_label = st.selectbox('Company', tuple(company_options), key='foundation_company')
        preset_number = company_options[company_label]
        custom_number = st.text_input(
            'Companies House number', value='', key='foundation_custom_company_number',
            placeholder='e.g. 01234567 or SC123456',
            disabled=preset_number is not None,
            help='Choose Other company to test any UK company by Companies House number.')
        number = preset_number or custom_number.strip()
        today = date.today()
        assessment_dates = tuple(today.fromordinal(today.toordinal() - offset) for offset in range(0, 367))
        day = st.selectbox('Assessment date', assessment_dates, index=0, key='foundation_day',
                           format_func=lambda d: d.isoformat())
        reporting_years = tuple(range(today.year, max(1900, today.year - 15), -1))
        default_year = reporting_years.index(2025) if 2025 in reporting_years else 0
        year = st.selectbox('Financial reporting year', reporting_years, index=default_year, key='foundation_year')
        run_mode = st.radio('Run mode', ('REUSE PERSISTED RESULT', 'FRESH END-TO-END'), horizontal=True,
            help='Fresh forces new Companies House retrieval, new raw evidence, new extraction, Turso persistence/read-back, then UI. Reuse reads the latest saved company result independently of the current date; it never starts fresh ingestion.')
        refresh = run_mode == 'FRESH END-TO-END'
        submitted = st.form_submit_button('Validate data foundation', type='primary')

    def fresh_board(run_id: str | None = None) -> list[dict[str, str]]:
        return [
            {'Stage':'0', 'Boundary':'Turso database connection', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'1', 'Boundary':'Companies House API: profile / filings / officers', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'2', 'Boundary':'Accounts filing + document metadata', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'3', 'Boundary':'Companies House iXBRL/XHTML acquisition', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'4', 'Boundary':'PDF semantic fallback (direct OpenAI; no OCR)', 'Status':'WAITING', 'Detail':'Used only when iXBRL/XHTML is unavailable'},
            {'Stage':'5', 'Boundary':'R2 raw evidence write + read-back + SHA-256', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'6', 'Boundary':'Deterministic extraction + 5-fact completeness', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'7', 'Boundary':'Primary accounts evidence validation', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'8.0', 'Boundary':'OpenAI configuration / semantic need', 'Status':'WAITING', 'Detail':'Not reached'},
            {'Stage':'8.1', 'Boundary':'OpenAI request', 'Status':'WAITING', 'Detail':'Not reached'},
            {'Stage':'8.2', 'Boundary':'OpenAI response', 'Status':'WAITING', 'Detail':'Not reached'},
            {'Stage':'8.3', 'Boundary':'Semantic candidates + evidence validation', 'Status':'WAITING', 'Detail':'Not reached'},
            {'Stage':'8.4', 'Boundary':'Semantic interpretation persistence to Turso', 'Status':'WAITING', 'Detail':'Not reached'},
            {'Stage':'9', 'Boundary':'Turso structured write + read-back', 'Status':'WAITING', 'Detail':'Not attempted'},
            {'Stage':'10', 'Boundary':'UI from Turso read-back', 'Status':'WAITING', 'Detail':'Not attempted'},
        ]

    def set_stage(board: list[dict[str, str]], stage: str, status: str, detail: str) -> None:
        for row in board:
            if row['Stage'] == stage:
                row['Status'], row['Detail'] = status, detail
                return

    if submitted:
        st.session_state.pop('foundation_view', None)
        st.session_state.pop('foundation_storage_check', None)
        st.session_state.pop('foundation_semantic_trace', None)
        st.session_state.pop('foundation_coverage', None)
        st.session_state.pop('foundation_before_openai', None)
        if year is None or not number.strip():
            st.error('Enter a company number and reporting year.'); return
        from risk_intelligence.ingestion.companies_house.client import company_number
        number = company_number(number)
        run_id = 'foundation-' + uuid4().hex if refresh else None
        board = fresh_board(run_id)
        st.session_state.foundation_stage_board = board
        st.session_state.foundation_run_id = run_id or 'reuse lookup'
        st.session_state.foundation_run_mode = run_mode
        st.subheader('Live pipeline progress')
        st.caption(f"Run ID: `{st.session_state.foundation_run_id}` · Mode: **{run_mode}**")
        board_slot = st.empty()
        board_slot.dataframe(board, hide_index=True, width='stretch')
        try:
            # Gate 0: prove the configured database can be opened before any network ingestion.
            with application_database(environ, write=True) as database:
                set_stage(board, '0', 'PASS', 'Configured database opened for ' + ('read/write' if refresh else 'read-only reuse'))
                board_slot.dataframe(board, hide_index=True, width='stretch')
                pair = None if refresh else latest_saved_run(database, number)
                if pair is None:
                    if not refresh:
                        raise RuntimeConfigurationError('No saved company result. Select Fresh End-to-End explicitly to acquire data.')
                    m2, m3 = ingestion_services(database, settings, environ, enable_llm=True)
                    m2_id, m3_id = run_id + '-m2', run_id + '-m3'
                    set_stage(board, '1', 'RUNNING', 'Requesting fresh profile, filing history and officers')
                    board_slot.dataframe(board, hide_index=True, width='stretch')
                    m2.ingest(number, day, m2_id, force_refresh=True, resources=(Resource.PROFILE, Resource.FILINGS, Resource.OFFICERS))
                    set_stage(board, '1', 'PASS', 'Fresh Companies House API retrieval completed')
                    set_stage(board, '5', 'IN PROGRESS', 'API JSON persisted; accounts raw objects will be added before final independent read-back')
                    set_stage(board, '2', 'RUNNING', 'Selecting eligible accounts filing and requesting document metadata')
                    set_stage(board, '8.0', 'READY' if settings.openai_api_key else 'NOT CONFIGURED',
                              'OpenAI credentials/model configured; waiting to determine semantic need' if settings.openai_api_key else 'No OpenAI key configured')
                    board_slot.dataframe(board, hide_index=True, width='stretch')

                    def accounts_progress(event: str, detail: str) -> None:
                        if event == 'accounts_metadata_request':
                            set_stage(board, '2', 'RUNNING', detail)
                        elif event == 'accounts_metadata_stored':
                            set_stage(board, '2', 'PASS', detail)
                        elif event == 'representations':
                            set_stage(board, '3', 'READY' if 'xhtml' in detail.lower() or 'xml' in detail.lower() else 'NOT AVAILABLE', detail)
                            set_stage(board, '4', 'READY' if ('pdf' in detail.lower() and not ('xhtml' in detail.lower() or 'xml' in detail.lower())) else 'NOT NEEDED', 'PDF fallback available but skipped because iXBRL/XHTML is primary' if ('xhtml' in detail.lower() or 'xml' in detail.lower()) else detail)
                        elif event in {'ixbrl_route_selected', 'pdf_route_selected'}:
                            if event == 'ixbrl_route_selected':
                                set_stage(board, '4', 'NOT NEEDED', detail)
                            else:
                                set_stage(board, '4', 'READY', detail)
                        elif event == 'representation_request':
                            target = '4' if 'PDF' in detail else '3'; set_stage(board, target, 'RUNNING', detail)
                        elif event == 'representation_retrieved':
                            target = '4' if 'PDF' in detail else '3'; set_stage(board, target, 'RUNNING', detail)
                        elif event == 'representation_stored':
                            target = '4' if 'PDF' in detail else '3'; set_stage(board, target, 'PASS', detail)
                        elif event == 'pdf_kind':
                            set_stage(board, '4', 'RUNNING', detail)
                        elif event == 'multimodal_llm':
                            set_stage(board, '8.0', 'PASS', 'No iXBRL: OpenAI asked to examine all five concepts from complete PDF')
                            set_stage(board, '8.1', 'RUNNING', detail)
                        elif event == 'semantic_llm':
                            set_stage(board, '8.0', 'PASS', st.session_state.get('foundation_before_openai', detail))
                            set_stage(board, '8.1', 'RUNNING', detail)
                        elif event == 'deterministic_coverage':
                            st.session_state.foundation_before_openai = detail
                            set_stage(board, '6', 'PASS', detail)
                        elif event == 'financial_route_summary':
                            coverage = read_coverage(detail)
                            if coverage:
                                st.session_state.foundation_coverage = coverage
                                set_stage(board, '6', 'PASS', coverage_text(coverage))
                                if coverage['openai_requested']:
                                    set_stage(board, '8.3', 'PASS', coverage_text(coverage))
                        elif event == 'semantic_not_needed':
                            set_stage(board, '8.0', 'NOT NEEDED', detail)
                        elif event == 'canonical_persist_start':
                            set_stage(board, '8.4', 'RUNNING', detail)
                        elif event == 'canonical_persist_done':
                            set_stage(board, '8.4', 'RUNNING', detail + '; finalizing run selection')
                        elif event == 'selection_finalized':
                            set_stage(board, '8.4', 'PASS', detail)
                        elif event == 'semantic_required':

                            if not (detail.startswith('No unresolved semantic context') and any(r['Stage']=='8.1' and r['Status'] in {'RUNNING','PASS'} for r in board)):
                                set_stage(board, '8.0', 'NOT NEEDED' if detail.startswith('No unresolved semantic context') else 'PASS', detail)
                        elif event == 'openai_request':
                            set_stage(board, '8.1', 'RUNNING', detail)
                        elif event == 'openai_response':
                            set_stage(board, '8.1', 'PASS', 'OpenAI request completed')
                            set_stage(board, '8.2', 'PASS', detail)
                        elif event == 'openai_failed':
                            set_stage(board, '8.1', 'FAILED', detail)
                        elif event == 'semantic_candidates':
                            set_stage(board, '8.3', 'RUNNING', detail)
                        elif event == 'semantic_decision':
                            trace = st.session_state.setdefault('foundation_semantic_trace', [])
                            trace.append(detail)
                        elif event == 'semantic_validation':
                            set_stage(board, '8.3', 'PASS', detail)
                        elif event == 'semantic_persist_start':
                            set_stage(board, '8.4', 'RUNNING', detail)
                        elif event == 'semantic_persist_done':
                            set_stage(board, '8.4', 'PASS', detail)
                        elif event == 'representation_extract_failed':
                            set_stage(board, '6', 'RUNNING', detail)
                        elif event == 'representation_extracted':
                            set_stage(board, '6', 'RUNNING', detail)
                        elif event == 'cross_validation':
                            set_stage(board, '7', 'PASS' if not detail.startswith('CONFLICT') else 'FAILED', detail)
                        elif event == 'representation_selected':
                            set_stage(board, '6', 'PASS', detail)
                        board_slot.dataframe(board, hide_index=True, width='stretch')

                    m3_final = m3.ingest(number, day, m3_id, reporting_year=int(year), max_documents=5,
                                          force_refresh=True, progress=accounts_progress)
                    pair = (m2_id, m3_id)
                    # Requested reporting year + selected filing control the run.
                    # accounts_run_selection is provenance/bookkeeping only; it is not
                    # an OpenAI admission condition and cannot block Gate 9.
                    selection_rows = database.query(
                        "SELECT requested_reporting_year,evidence_reporting_year,selected_period_end "
                        "FROM accounts_run_selection WHERE processing_run_id=?", (m3_id,))
                    selected_period = (str(selection_rows[0]['selected_period_end'])
                                       if len(selection_rows) == 1 else f'{year} (year-level)')
                    coverage = st.session_state.get('foundation_coverage')
                    detail = coverage_text(coverage) if coverage else 'Deterministic/semantic extraction completed'
                    set_stage(board, '6', 'PASS', detail + f'; selected reporting period {selected_period}')
                    if any(r['Stage']=='8.0' and r['Status']=='PASS' for r in board):
                        if next((r for r in board if r['Stage']=='8.3'), {}).get('Status') in {'RUNNING','WAITING','READY'}:
                            set_stage(board, '8.3', 'PASS', 'Semantic candidates admitted and canonical facts persisted')
                        if next((r for r in board if r['Stage']=='8.4'), {}).get('Status') in {'RUNNING','WAITING','READY'}:
                            set_stage(board, '8.4', 'PASS',
                                      f'Canonical financial facts persisted for requested year {year}')
                    board_slot.dataframe(board, hide_index=True, width='stretch')

                    # Finalise raw-evidence integrity immediately after ingestion, before
                    # any structured read-back. A later Turso/UI failure must not leave
                    # a successfully verified R2 boundary displayed as PARTIAL.
                    storage = (R2Storage.from_settings(settings) if settings.evidence_storage_backend == 'r2'
                               else LocalStorage(settings.local_data_directory / 'raw'))
                    raw_rows = database.query(
                        "SELECT object_path,checksum FROM raw_evidence WHERE processing_run_id IN (?,?) "
                        "ORDER BY processing_run_id,raw_evidence_id", (m2_id, m3_id))
                    checked = 0
                    for item in raw_rows:
                        content = storage.read(str(item['object_path']))
                        if sha256(content).hexdigest() != str(item['checksum']):
                            raise RuntimeError('Raw evidence integrity verification failed')
                        checked += 1
                    st.session_state.foundation_storage_check = (
                        'R2' if settings.evidence_storage_backend == 'r2' else 'Local', checked)
                    set_stage(board, '5', 'PASS',
                              f"{'R2' if settings.evidence_storage_backend == 'r2' else 'Local'} read-back + SHA-256 verified for {checked} objects")

                    # m3 returned successfully, so semantic/multimodal processing itself
                    # did not throw. Resolve its status before starting Gate 9 so a later
                    # database read error cannot be mislabelled as an OpenAI failure.
                    llm_rows = database.query(
                        "SELECT p.status,p.error_code FROM accounts_run_processing rp "
                        "JOIN accounts_processing p USING(fingerprint) "
                        "WHERE rp.processing_run_id=? AND p.stage='LLM' ORDER BY p.created_at", (m3_id,))
                    if llm_rows:
                        failed_llm = [r for r in llm_rows if str(r['status']) != 'COMPLETE']
                        if failed_llm:
                            codes = ', '.join(sorted({str(r['error_code'] or 'provider/processing error') for r in failed_llm}))
                            set_stage(board, '8.1', 'PARTIAL',
                                      f'OpenAI semantic attempt had a technical failure ({codes}); unresolved concepts are persisted with explicit reasons')
                            if next((r for r in board if r['Stage']=='8.2'), {}).get('Status') == 'WAITING':
                                set_stage(board, '8.2', 'NOT REACHED', 'No usable OpenAI response artifact was produced for the failed attempt')
                        else:
                            if next((r for r in board if r['Stage']=='8.2'), {}).get('Status') == 'WAITING':
                                set_stage(board, '8.2', 'PASS', f'OpenAI artifact completed ({len(llm_rows)} artifact(s))')
                    else:
                        for stage in ('8.0','8.1','8.2','8.3','8.4'):
                            if next((r for r in board if r['Stage']==stage), {}).get('Status') in {'WAITING','READY'}:
                                set_stage(board, stage, 'NOT NEEDED', 'No LLM processing artifact was required')
                    board_slot.dataframe(board, hide_index=True, width='stretch')
                else:
                    for stage in ('1','2','3','4','5','6','7'):
                        set_stage(board, stage, 'SKIPPED', 'Reuse mode: no fresh acquisition/extraction')

                    for stage in ('8.0','8.1','8.2','8.3','8.4'):
                        set_stage(board, stage, 'NOT NEEDED', 'Reuse mode')
                board_slot.dataframe(board, hide_index=True, width='stretch')

                # Gate 9 is an independent persistence acceptance boundary.  Do not
                # validate Turso using the same long-lived connection that performed
                # ingestion writes: a fresh connection proves the committed state is
                # actually visible to a new reader and avoids carrying provider/driver
                # statement state from the write session into the read-back check.
                set_stage(board, '9', 'RUNNING', 'Opening an independent database connection for persisted read-back')
                board_slot.dataframe(board, hide_index=True, width='stretch')
                with application_database(environ) as readback_database:
                    view = load_foundation(readback_database, *pair)
                st.session_state.foundation_view = view
                set_stage(board, '9', 'PASS', 'Structured facts and run lineage read back successfully on an independent connection')

                # R2 integrity and LLM status were finalised before Gate 9.
                set_stage(board, '10', 'PASS', 'UI is displaying the independent Turso/database read-back object')
                board_slot.dataframe(board, hide_index=True, width='stretch')
                st.session_state.foundation_stage_board = board
            st.success('Fresh A→E run completed.' if refresh else 'Persisted A→E result loaded.')
        except Exception as exc:
            # Preserve completed stages and identify the boundary at which execution stopped.
            # Attribute a terminal exception to the latest active boundary, not the
            # earliest stale RUNNING row.  Earlier versions could therefore display a
            # Gate-9 read-back error as a false Stage-6 extraction failure.
            active = [r for r in board if r['Status'] == 'RUNNING']
            running = active[-1] if active else None
            if running is not None:
                running['Status'] = 'FAILED'
                running['Detail'] = f'{type(exc).__name__}: {str(exc)[:240]}'
            for row in board:
                if row['Status'] == 'WAITING':
                    row['Status'], row['Detail'] = 'NOT REACHED', 'Stopped after the failed stage above'
                elif row['Status'] == 'READY':
                    row['Status'], row['Detail'] = 'NOT REACHED', 'Fallback was available but processing stopped earlier'
                elif row['Stage'] == '5' and row['Status'] == 'IN PROGRESS':
                    row['Status'], row['Detail'] = 'PARTIAL', 'Earlier immutable raw evidence was persisted; final all-object R2 read-back was not reached'
            st.session_state.foundation_stage_board = board
            board_slot.dataframe(board, hide_index=True, width='stretch')
            st.error('Fresh pipeline stopped. The table above identifies the last boundary reached; completed immutable evidence is preserved.')
            return

    board = st.session_state.get('foundation_stage_board')
    if board and not submitted:
        st.subheader('Last pipeline progress')
        st.caption(f"Run ID: `{st.session_state.get('foundation_run_id','—')}` · Mode: **{st.session_state.get('foundation_run_mode','UNKNOWN')}**")
        st.dataframe(board, hide_index=True, width='stretch')

    view = st.session_state.get('foundation_view')
    if view is None:
        st.caption('This workflow stops before M4/M5. Fresh mode validates Companies House → raw evidence → extraction/OpenAI if needed → Turso read-back → UI.')
        return
    st.subheader('A–E acceptance evidence')
    storage_check = st.session_state.get('foundation_storage_check')
    st.write(f'Requested year: **{view.requested_year}** · Evidence year: **{view.evidence_year}** · Period end: **{view.period_end}** · Selection: **{view.selection_mode}**')
    st.markdown('**Gate A — Companies House resources required for the frozen six variables**')
    resources=[]
    for r in view.api_resources:
        item=dict(r); required=item.get('resource') in {'profile','filing-history','officers'}
        item['required_for_six_variables']=required
        item['gate_impact']='REQUIRED' if required else 'SUPPORTING_ONLY'
        resources.append(item)
    st.dataframe(resources, hide_index=True, width='stretch')
    st.markdown('**Gate B — Raw evidence integrity**')
    st.write(f"Storage: **{storage_check[0] if storage_check else 'NOT CHECKED'}** · Objects independently read back and checksum-verified: **{storage_check[1] if storage_check else 0}**")
    st.markdown('**Financial extraction breakdown — five distinct concepts**')
    breakdown = coverage_rows(view.documents)
    if breakdown:
        st.dataframe(breakdown, hide_index=True, width='stretch')
        st.caption('Counts are financial concepts, not API calls or candidate rows. Before OpenAI includes supported Python derivations; recovered totals can include a Python derivation enabled by OpenAI evidence.')
    else:
        st.caption('This earlier run did not record before/after counts. Run Fresh End-to-End to see the exact breakdown; counts are not inferred from extraction methods.')
    st.markdown('**Gate C — Accounts documents and extraction route**')
    display_documents = [{**document, 'reason': str(document.get('reason') or '').split('\nFINANCIAL_COVERAGE_V1:', 1)[0]}
                         for document in view.documents]
    st.dataframe(display_documents, hide_index=True, width='stretch')
    trace = st.session_state.get('foundation_semantic_trace', [])
    if trace:
        st.markdown('**OpenAI semantic candidate admission details**')
        st.dataframe([{'Candidate / admission result': item} for item in trace], hide_index=True, width='stretch')
    st.markdown('**Gate D — Five persisted financial inputs**')
    identified = sum(f.availability == 'AVAILABLE' and f.value is not None for f in view.facts)
    st.info(f'Financial values identified: **{identified}/5** · Unknown: **{5 - identified}/5**. '
            'Pipeline completion records processing; the values and reasons below determine financial coverage.')
    st.dataframe([{'Concept': f.concept, 'Value': str(f.value) if f.value is not None else 'Unknown',
                   'Status': f.availability, 'Reason': f.reason or '—',
                   'Method': f.extraction_method or '—',
                   'Period end': f.period_end or '—', 'Document': f.document_id or '—'} for f in view.facts],
                 hide_index=True, width='stretch')
    st.markdown('**Gate D — Governance base facts**')
    gov = {str(item.get('Variable')): item for item in view.governance_inputs}
    st.dataframe([gov.get('G1.1', {}), gov.get('G1.2', {}), gov.get('G2.2', {})], hide_index=True, width='stretch')
    st.markdown('**Gate E — UI from persisted read-back: deterministic six variables**')
    labels={'G1.1':'Accounts filing lateness','G1.2':'Confirmation statement lateness','G2.2':'Median tenure of active directors',
            'F1.1':'Net assets / total assets','F2.2':'Current assets / current liabilities','F2.3':'Quick ratio'}
    units={'G1.1':'days','G1.2':'days','G2.2':'years','F1.1':'ratio','F2.2':'ratio','F2.3':'ratio'}
    combined=(*view.governance_variables,*view.variables)
    st.dataframe([{'Variable':code,'Name':labels[code],'Raw value':str(value) if value is not None else 'Unknown',
                   'Unit':units[code],'Status':status} for code,value,status in combined], hide_index=True, width='stretch')
    st.caption('Unknown is preserved when evidence is absent/conflicting. DERIVED is deterministic arithmetic, never LLM. OpenAI is used only as evidence extraction fallback and is shown explicitly above.')

def _friendly_record(item: InputExplanation) -> None:
    record = item.model_dump(mode='json')['record']
    concept = record.get('canonical_concept') or record.get('obligation_kind') or item.reference.kind.title()
    value = record.get('value_numeric')
    cols = st.columns(3)
    cols[0].metric('Evidence item', str(concept).replace('_',' ').title())
    cols[1].metric('Value', two_dp(value) if value is not None else 'Recorded evidence')
    cols[2].metric('Evidence reliability', two_dp(item.reference.reliability_r))
    period = record.get('period_end') or record.get('obligation_period')
    if period: st.write('Reporting / reference period:', period)
    if item.evidence:
        st.markdown('**Source evidence**')
        for e in item.evidence:
            st.write(f'**Source:** {e.source.source_type.value.replace("_"," ").title()}')
            ref = e.source.source_url or e.source.source_identifier
            if ref: st.write('Source reference:', str(ref))
            loc = e.reference.location.model_dump(mode='json', exclude_none=True)
            friendly = {k.replace('_',' ').title(): v for k,v in loc.items() if k not in {'document_id'}}
            if friendly: st.write('Location:', friendly)
            if e.reference.evidence_text: st.info(e.reference.evidence_text)
    with st.expander('Technical audit details'):
        st.json(item.model_dump(mode='json'), expanded=False)


def _why(variable) -> None:
    result = variable.leaf.result
    st.subheader(variable.name)
    st.dataframe([{'Raw value': two_dp(result.raw_value), 'Unit': result.unit,
                   **belief_display(result.final_belief), 'Availability': result.availability_status.value.replace('_',' ').title()}],
                 hide_index=True, width='stretch')
    st.markdown('### Why this risk?')
    st.write(risk_sentence(variable))
    if variable.leaf.calculation.reasons:
        st.warning('Evidence issue: ' + '; '.join(r.value.replace('_',' ').title() for r in variable.leaf.calculation.reasons))
    st.markdown('### Calculation')
    traces = [t.detail for t in variable.leaf.calculation.trace if t.operation in {'arithmetic','lateness','median_tenure'}]
    for trace in traces: st.code(trace, language=None)
    if variable.reporting_year is not None: st.write('Financial reporting year:', variable.reporting_year)
    st.markdown('### Supporting facts and evidence')
    if not variable.inputs: st.info('No validated inputs are available for this variable.')
    for item in variable.inputs: _friendly_record(item)


def _narrative(view: AssessmentView) -> None:
    """Explicit optional action; rerendering never invokes an LLM."""
    settings = load_settings(dict(os.environ))
    if not settings.openai_api_key:
        st.caption('AI-assisted summary is unavailable. The verified explanations remain available below.')
        return
    try:
        configuration = load_model_configuration(dict(os.environ))
    except RuntimeConfigurationError:
        st.caption('Summary assistance needs configuration. Verified results remain available.')
        return
    fingerprint = narrative_fingerprint(view, configuration)
    cached = st.session_state.get('narrative_result')
    if st.button('Prepare evidence-grounded summary'):
        if cached is None or cached[0] != fingerprint:
            try:
                with st.spinner('Preparing the verified explanation summary…'):
                    paragraphs = generate_narrative(view, settings.openai_api_key, configuration)
                cached = (fingerprint, paragraphs)
                st.session_state.narrative_result = cached
            except NarrativeUnavailable:
                st.info('Summary assistance is unavailable. Use the verified indicator explanations below.')
    if cached is not None and cached[0] == fingerprint:
        st.caption('AI assists the reading order. Every sentence is generated from verified stored results.')
        for paragraph in cached[1]:
            st.write(paragraph)


def render_assessment(view: AssessmentView) -> None:
    ex = view.explanation
    st.header(view.company_name or 'Company')
    st.caption((f'Requested financial reporting year: {ex.reporting_year} · Evidence reporting year used: {ex.evidence_reporting_year} · ' if ex.evidence_reporting_year != ex.reporting_year else f'Financial reporting year: {ex.reporting_year} · ') + f'Evidence assessed as of {ex.assessment.assessment_date}')
    gaps = [v.name for v in ex.variables if v.leaf.result.raw_value is None]
    if gaps:
        st.warning('Some indicators could not be assessed: ' + ', '.join(gaps) + '. See Why this risk? for the evidence gaps.')
    overview, variables, why, methodology = st.tabs(['Overview', 'Variables', 'Why this risk?', 'Methodology'])
    with overview:
        st.subheader('Overall risk belief')
        st.dataframe([belief_display(ex.overall.result.belief)], hide_index=True, width='stretch')
        _narrative(view)
        st.subheader('Governance and Financial')
        st.dataframe([{'Domain': n.result.node_name, **belief_display(n.result.belief)} for n in ex.domains],
                     hide_index=True, width='stretch')
    with variables:
        st.subheader('Risk indicators')
        st.dataframe([variable_display(v) for v in ex.variables], hide_index=True, width='stretch')
    with why:
        by_name = {v.name: v for v in ex.variables}
        name = st.selectbox('Variable', tuple(by_name))
        _why(by_name[name])
    with methodology:
        st.subheader('How an individual indicator is assessed')
        st.write('Each indicator is compared with predefined low-risk and high-risk reference levels. The result is expressed as Low, High and Unknown beliefs rather than forcing the evidence into one score.')
        st.info('Example: Low 0.10, High 0.80 and Unknown 0.10 means the available evidence supports the high-risk side more strongly, while 0.10 remains unresolved because of evidence uncertainty.')
        st.subheader('How the indicators are combined')
        st.write('Evidential Reasoning (ER) combines the three Governance indicators and the three Financial indicators while preserving unresolved uncertainty. The two domain results are then combined using their predefined importance weights to produce the Overall belief.')
        st.write('Evidence → indicator beliefs → Governance / Financial → Overall risk belief')
        with st.expander('Technical methodology'):
            st.write('M4 validates evidence and records reliability. M5 calculates the six indicator beliefs. M6 performs hierarchical ER aggregation. M7 resolves the persisted traceability tree shown by this interface.')


def _leaf_belief_test(environ: dict[str, str]) -> None:
    """Explicit SQL-only test button; rerenders replay stored results without ER."""
    st.subheader('Six-variable belief test')
    st.caption('Read saved company values and apply the approved six-variable reference standards.')
    with application_database(environ) as database:
        companies = saved_companies(database)
    if not companies:
        st.info('No saved Foundation companies are available. This workflow never starts ingestion.')
        st.session_state.pop('leaf_test_view', None)
        return
    names = dict(companies)
    number = st.selectbox('Saved company', tuple(names),
        format_func=lambda n: f'{names[n]} — {n}', key='leaf_test_company',
        index=None, placeholder='Select a saved company to view its beliefs')
    if number is None:
        st.session_state.pop('leaf_test_view', None)
        st.session_state.leaf_test_selection = None
        return
    if st.session_state.get('leaf_test_selection') != number:
        st.session_state.pop('leaf_test_view', None)
        st.session_state.leaf_test_selection = number
    if st.session_state.get('leaf_test_view') is None:
        st.session_state.pop('leaf_test_view', None)
        with st.spinner('Reading saved values and applying reference standards…'):
            with application_database(environ, write=True) as database:
                view = calculate_saved_reference_beliefs(database, number)
                st.session_state.leaf_test_view = view
    view = st.session_state.get('leaf_test_view')
    if view is None:
        return
    st.success('Saved reference beliefs loaded.' if view.reused else 'Six reference beliefs calculated and saved.')
    st.caption(f'{view.company_name} · {number} · Saved assessment date: {view.assessment_date} · '
               f'Requested year: {view.foundation.requested_year} · Evidence year: {view.foundation.evidence_year}')
    st.subheader('Six-variable risk beliefs')
    st.dataframe(summary_rows(view), hide_index=True, width='stretch')
    st.caption('Unknown means the saved data does not provide a usable value for this variable. The reason is listed per row; '
               'a failed extraction does not prove the company did not disclose the information.')
    st.subheader('Risk reference standards')
    st.caption('These are the approved initial MVP reference levels, not universal industry cut-offs or thresholds prescribed by ER. '
               'ER-style linear transformation uses the reference levels; it does not determine their numerical values.')
    st.dataframe(standards_rows(view), hide_index=True, width='stretch')
    st.subheader('Calculation method and explanations')
    st.code('High = clip((value − Low reference) / (High reference − Low reference), 0.00, 1.00)\n'
            'Low = 1.00 − High; Unknown = 0.00 when the value is available\n'
            'No usable value: High = 0.00; Low = 0.00; Unknown = 1.00', language=None)
    st.write('clip limits the result to the interval 0.00–1.00. Values on or beyond the Low-risk side receive full Low support; '
             'values on or beyond the High-risk side receive full High support. Values between the two references are linearly interpolated. '
             'The same formula works when a higher value means less risk, such as director tenure and the financial ratios.')
    for belief in view.beliefs:
        st.write(calculation_explanation(view, belief))
    st.caption('Beliefs are decimal shares, not percentages or probabilities of company failure. Displays use two decimal places; '
               'calculations retain full precision. Rounded shares may not sum exactly to 1.00.')



def _er_aggregation_test(environ: dict[str, str]) -> None:
    """SQL-only ER test over V44 reference memberships, with hierarchical drill-down."""
    import altair as alt
    st.subheader('ER aggregation test')
    with application_database(environ) as database:
        choices = saved_companies(database)
    if not choices:
        st.info('No saved company values are available.')
        return
    names = dict(choices)
    number = st.selectbox('Saved company', tuple(names), format_func=lambda n: f'{names[n]} — {n}',
                          index=None, placeholder='Select a saved company to view its ER risk', key='er_company')
    if number is None:
        st.session_state.pop('er_view', None)
        st.session_state.er_selection = None
        return
    if st.session_state.get('er_selection') != number:
        st.session_state.pop('er_view', None)
        st.session_state.er_selection = number
    if st.session_state.get('er_view') is None:
        with st.spinner('Combining saved variable beliefs using ER…'):
            with application_database(environ, write=True) as database:
                st.session_state.er_view = calculate_saved_reference_er(database, number)
    view = st.session_state.er_view
    reference = view.reference
    st.caption(f'{reference.company_name} · {number} · Saved assessment date: {reference.assessment_date} · Evidence year: {reference.foundation.evidence_year}')
    st.subheader('Overall company risk')
    st.caption('Company risk assessed only from Governance and Financial. Belief shares are not probabilities of company failure.')
    data = alt.InlineData(values=chart_rows(view))
    chart = alt.Chart(data).mark_arc().encode(
        theta=alt.Theta('Start:Q', scale=None, stack=None),
        theta2=alt.Theta2('End:Q'),
        color=alt.Color('Risk:N', scale=alt.Scale(domain=['High risk', 'Low risk', 'Unknown'], range=['#d9534f', '#2f9e69', '#9ca3af']),
                        sort=['High risk', 'Low risk', 'Unknown']),
        tooltip=['Risk:N', 'Percentage:N'])
    labels = alt.Chart(data).transform_filter('datum.Share > 0').mark_text(radius=105, color='white', fontSize=16).encode(
        theta=alt.Theta('Middle:Q', scale=None, stack=None), text='Percentage:N')
    st.altair_chart((chart + labels).properties(height=320), width='stretch')
    st.subheader('Governance and Financial risk')
    st.caption('Domain tables use decimal belief shares from 0.00 to 1.00; the pie chart displays the same overall shares as percentages.')
    st.dataframe(node_rows(view.domains), hide_index=True, width='stretch')
    st.subheader('How ER produces this result')
    st.write('Three Governance variable beliefs are combined into Governance risk, and three Financial variable beliefs into Financial risk. '
             'The two domain beliefs are then combined into overall company risk. Each step uses Yang/Xu evidential reasoning (ER), '
             'a nonlinear combination of weighted belief support, not an arithmetic average.')
    st.write('Within each domain, all three variables have equal importance (1/3 each). At the company level the existing MVP weights '
             'are Governance 0.40 and Financial 0.60. These are model settings, not weights prescribed by the paper.')
    st.write('Unknown is unassigned belief caused by missing usable information. It is not a third risk grade. Missing inputs remain in '
             'the calculation with their weights; their weights are not redistributed. Reliability is not applied in this stage.')
    with st.expander('Step 1 — Overall risk from Governance and Financial', expanded=True):
        st.dataframe(child_rows(view.overall), hide_index=True, width='stretch')
        st.write(node_explanation(view.overall))
    for domain in view.domains:
        with st.expander(f'Step 2 — {domain.code.title()} risk from its three variables', expanded=True):
            st.dataframe(child_rows(domain), hide_index=True, width='stretch')
            st.write(node_explanation(domain))


def main() -> None:
    st.set_page_config(page_title='Evidence-Grounded AI Risk Intelligence', layout='wide')
    st.title('Evidence-Grounded AI Risk Intelligence')
    st.caption('Evidence-backed company risk assessment with traceable supporting facts.')
    environ = dict(os.environ)
    public_view = environ.get('RISK_UI_PUBLIC', 'false').lower() == 'true'
    if public_view:
        mode = 'Risk dashboard'
    else:
        mode = st.sidebar.radio('Workspace', ('Risk dashboard', 'Data foundation validation', 'Six-variable belief test', 'ER aggregation test', 'Load existing assessment', 'New assessment'))
    if st.session_state.get('workflow_mode') != mode:
        st.session_state.pop('assessment_view', None); st.session_state.pop('leaf_test_view', None); st.session_state.pop('er_view', None); st.session_state.workflow_mode = mode
    try:
        if mode == 'Risk dashboard':
            from risk_intelligence.ui.dashboard import render_dashboard
            render_dashboard(environ)
        elif mode == 'Data foundation validation':
            _foundation(environ)
        elif mode == 'Six-variable belief test':
            _leaf_belief_test(environ)
        elif mode == 'ER aggregation test':
            _er_aggregation_test(environ)
        elif mode == 'Load existing assessment':
            _select_existing(environ)
        else:
            _new_assessment(environ)
        view = st.session_state.get('assessment_view') if mode not in ('Risk dashboard', 'Data foundation validation', 'Six-variable belief test', 'ER aggregation test') else None
        if view is not None: render_assessment(view)
    except Exception as error:
        st.session_state.pop('assessment_view', None); st.session_state.pop('leaf_test_view', None); st.session_state.pop('er_view', None); st.session_state.pop('dashboard_view', None); _show_error(error)
