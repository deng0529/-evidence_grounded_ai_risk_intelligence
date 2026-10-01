"""Streamlit rendering only; production services own computation and traceability."""

from datetime import UTC, date, datetime
import os
from uuid import uuid4

import streamlit as st

from risk_intelligence.config import load_settings
from risk_intelligence.explanation import InputExplanation
from risk_intelligence.services.application import (
    AssessmentApplication, AssessmentView, belief_row, display_value, error_message, variable_row,
)
from risk_intelligence.services.application_runtime import application_database, ingestion_services


def _show_error(error: Exception) -> None:
    message = error_message(error)
    st.error(f'{message.code}: {message.message}')


def _select_existing(environ: dict[str, str]) -> None:
    with application_database(environ) as database:
        choices = AssessmentApplication(database).choices()
        if not choices:
            st.info('No assessments have been recorded. Run a new assessment or configure a database containing persisted results.')
            st.session_state.pop('assessment_view', None)
            return
        company_numbers = tuple(dict.fromkeys(choice.assessment.company_number for choice in choices))
        names = {choice.assessment.company_number: choice.company_name for choice in choices}
        number = st.selectbox('Company', company_numbers,
                              format_func=lambda n: f'{names[n] or "Name unavailable"} · {n}')
        candidates = tuple(choice for choice in choices if choice.assessment.company_number == number)
        years = tuple(dict.fromkeys(choice.reporting_year for choice in candidates))
        year = st.selectbox('Financial reporting year', years, format_func=display_value)
        selected = tuple(choice for choice in candidates if choice.reporting_year == year)
        by_id = {choice.assessment.assessment_id: choice for choice in selected}
        identity = st.selectbox('Assessment', tuple(by_id), format_func=lambda i:
            f'{by_id[i].assessment.assessment_date} · {i} · model {by_id[i].assessment.risk_model_version}')
        previous = st.session_state.get('assessment_view')
        if previous and previous.explanation.assessment.assessment_id != identity:
            st.session_state.pop('assessment_view', None)
        if st.button('Load assessment', type='primary'):
            st.session_state.pop('assessment_view', None)
            with st.spinner('Loading persisted results and evidence references…'):
                st.session_state.assessment_view = AssessmentApplication(database).load(identity)


def _new_assessment(environ: dict[str, str]) -> None:
    settings = load_settings(environ)
    st.caption('A new assessment records a new run. Existing assessments are not overwritten. Assessment date and reporting year are separate inputs.')
    with st.form('new_assessment'):
        number = st.text_input('Company number', max_chars=8)
        day = st.date_input('Assessment date', value=date.today())
        year = st.number_input('Financial reporting year', min_value=1900, max_value=9999,
                               value=None, step=1, placeholder='Enter the explicit reporting year')
        mode = st.selectbox('Evidence workflow', ('Live ingestion', 'Reuse recorded ingestion runs'))
        m2_id = st.text_input('M2 run ID (reuse only)')
        m3_id = st.text_input('M3 run ID (reuse only)')
        maximum = st.number_input('Maximum accounts documents (live)', min_value=1, max_value=10, value=5)
        llm = st.checkbox('Enable configured LLM extraction for live ingestion', value=False)
        st.caption('Live ingestion uses configured Companies House and storage adapters. Reuse requires exact existing M2/M3 run IDs for this company and assessment date.')
        submitted = st.form_submit_button('Run new assessment', type='primary')
    if not submitted:
        return
    st.session_state.pop('assessment_view', None)
    if year is None or not number.strip():
        st.error('Enter a company number and an explicit financial reporting year.')
        return
    if mode == 'Reuse recorded ingestion runs' and not (m2_id.strip() and m3_id.strip()):
        st.error('Both recorded ingestion run IDs are required for reuse.')
        return
    run_id = 'ui-' + uuid4().hex
    st.info(f'Processing run: {run_id}')
    with st.spinner('Running the production assessment pipeline…'):
        with application_database(environ, write=True) as database:
            m2 = m3 = None
            reuse = None
            if mode == 'Live ingestion':
                m2, m3 = ingestion_services(database, settings, environ, enable_llm=llm)
            else:
                reuse = (m2_id.strip(), m3_id.strip())
            st.session_state.assessment_view = AssessmentApplication(database).create(
                number=number, assessment_date=day, reporting_year=int(year), run_id=run_id,
                calculated_at=datetime.now(UTC), m2=m2, m3=m3, reuse_runs=reuse, max_documents=int(maximum))
    st.success('Assessment results persisted. Unknown and any recorded exclusions remain visible below.')


def _input_details(item: InputExplanation, key: str) -> None:
    payload = item.model_dump(mode='json')
    record = payload['record']
    st.caption(f'{item.reference.kind} · {item.reference.validated_id} · mandatory: {item.reference.mandatory}')
    st.write('Persisted M4 reliability:', str(item.reference.reliability_r))
    summary = {name: record[name] for name in (
        'canonical_concept', 'value_numeric', 'currency', 'unit', 'analytical_scope', 'period_start', 'period_end',
        'availability_status', 'validation_status', 'provenance_type', 'normalization_method', 'derivation_method',
        'obligation_kind', 'obligation_period', 'due_date', 'filing_date', 'filing_state',
    ) if name in record}
    st.json(summary, expanded=True)
    with st.expander('Validation, conflict and persisted M4 record'):
        st.json(record, expanded=False)
    with st.expander('Source observations and canonical lineage'):
        if not item.observations:
            st.info('No source observations recorded for this input.')
        else:
            st.json(payload['observations'], expanded=False)
        if item.financial_lineage is None:
            st.caption('Financial mapping/derivation lineage: unavailable or not applicable to this input.')
        else:
            st.json(payload['financial_lineage'], expanded=False)
    with st.expander('Coverage snapshots (separate from field-level locators)'):
        if item.snapshots:
            st.json(payload['snapshots'], expanded=False)
        else:
            st.caption('No coverage snapshots recorded for this input.')
    st.markdown('**Evidence and provenance**')
    st.caption('A citation does not by itself establish independent validation support. See the retained validation roles and reasons.')
    if not item.evidence:
        st.info('No field-level evidence references recorded. No provenance has been inferred.')
        return
    by_id = {evidence.reference.evidence_id: evidence for evidence in item.evidence}
    identity = st.selectbox('Evidence reference', tuple(by_id), key=f'{key}-evidence',
        format_func=lambda i: f'{by_id[i].reference.location.kind} · {i}')
    evidence = by_id[identity]
    st.write('Source type:', evidence.source.source_type.value)
    st.write('Retrieved at:', evidence.source.retrieved_at.isoformat())
    st.text('Source ID: ' + evidence.source.source_id)
    st.text('Source URL/reference: ' + display_value(evidence.source.source_url or evidence.source.source_identifier))
    st.json(evidence.reference.location.model_dump(mode='json'), expanded=True)
    st.text('Evidence text: ' + display_value(evidence.reference.evidence_text))
    if evidence.document:
        st.json(evidence.document.model_dump(mode='json'), expanded=False)
    else:
        st.caption('Document metadata: unavailable / not applicable to this source.')


def render_assessment(view: AssessmentView) -> None:
    """Render only M7-resolved values; all numeric dataframe cells stay exact strings."""
    explanation = view.explanation
    context = explanation.assessment
    st.header(view.company_name or 'Company name unavailable')
    st.dataframe([{'Company number': context.company_number, 'Assessment ID': context.assessment_id,
                   'Assessment date': context.assessment_date.isoformat(), 'Reporting year': str(explanation.reporting_year),
                   'Risk model': context.risk_model_version, 'ER model': context.er_model_version,
                   'Recorded status': context.status.value}], hide_index=True)
    overview, variables, trace, methodology = st.tabs(['Overview', 'Variables', 'Traceability', 'Methodology'])
    with overview:
        st.subheader('Overall risk belief')
        st.caption('Persisted M6 ER result. Low, High and Unknown are shown without renormalisation.')
        st.dataframe([belief_row(explanation.overall.result.belief)], hide_index=True)
        st.subheader('Governance and Financial')
        weights = {edge.child_code: edge.importance_weight for edge in explanation.overall.children}
        st.dataframe([{'Domain': node.result.node_name, **belief_row(node.result.belief),
                       'Importance weight': str(weights[node.result.node_code])} for node in explanation.domains], hide_index=True)
        st.info('Unknown represents unresolved evidence uncertainty. High belief is not a probability of company failure.')
    with variables:
        st.subheader('Six active variables · model v1.2')
        st.dataframe([variable_row(variable) for variable in explanation.variables], hide_index=True)
        st.caption('All figures are persisted exact decimal strings. Use Traceability for calculation inputs, exclusions and source evidence.')
    with trace:
        choices = {variable.leaf.result.variable_code: variable for variable in explanation.variables}
        code = st.selectbox('Variable', tuple(choices), format_func=lambda c: f'{c} · {choices[c].name}')
        variable = choices[code]
        st.dataframe([variable_row(variable)], hide_index=True)
        st.write('Selected financial reporting year:', display_value(variable.reporting_year))
        with st.expander('Persisted calculation and reasons', expanded=True):
            st.json(variable.leaf.calculation.model_dump(mode='json'), expanded=False)
        if not variable.inputs:
            st.info('No validated calculation inputs recorded. See the persisted availability and exclusion reasons above.')
        else:
            index = st.selectbox('Validated input', range(len(variable.inputs)), key=f'{context.assessment_id}-{code}-input',
                format_func=lambda n: f'{variable.inputs[n].reference.kind} · {variable.inputs[n].reference.validated_id}')
            _input_details(variable.inputs[index], f'{context.assessment_id}-{code}-{index}')
    with methodology:
        st.write('M4 validates evidence and records reliability. M5 calculates variables and Low/High/Unknown leaf beliefs. M6 aggregates them using ER. M7 resolves the stored traceability tree. This interface displays those outputs.')
        st.write('Governance and Financial each contain three equally weighted active variables. Overall uses persisted domain weights 0.40 and 0.60. G1/G2/F1/F2 are explanatory labels only.')
        st.write('Unavailable inputs retain their stored status and cause. No missing value is replaced with zero and no weight is redistributed.')


def main() -> None:
    """One entry point with an explicit exception boundary and no secret-bearing errors."""
    st.set_page_config(page_title='Evidence-Grounded AI Risk Intelligence', layout='wide')
    st.title('Evidence-Grounded AI Risk Intelligence')
    st.caption('Explore a company assessment from risk beliefs to supporting evidence.')
    environ = dict(os.environ)
    mode = st.radio('Workflow', ('Load existing assessment', 'New assessment'), horizontal=True)
    if st.session_state.get('workflow_mode') != mode:
        st.session_state.pop('assessment_view', None)
        st.session_state.workflow_mode = mode
    try:
        if mode == 'Load existing assessment':
            _select_existing(environ)
        else:
            _new_assessment(environ)
        view = st.session_state.get('assessment_view')
        if view is not None:
            render_assessment(view)
    except Exception as error:
        # Provider exceptions may contain credentials. Never print/log their text.
        # Fail visibly and clear stale results rather than showing a prior success.
        st.session_state.pop('assessment_view', None)
        _show_error(error)
