"""Unified saved-data dashboard; presentation only, with no ingestion controls."""
import altair as alt
import streamlit as st

from risk_intelligence.services.application_runtime import application_database
from risk_intelligence.services.leaf_belief_test import saved_companies
from risk_intelligence.services.dashboard_snapshot import DashboardSnapshot, load_dashboard_snapshot, SnapshotUnavailable
from .architecture import render_architecture
from .welcome import render_welcome


def render_pie(view: DashboardSnapshot) -> None:
    """Render explicit sector angles and percentage labels from one ER distribution."""
    data = alt.InlineData(values=view.chart)
    colors = alt.Color('Risk:N', scale=alt.Scale(
        domain=['High risk', 'Low risk', 'Unknown'], range=['#d9534f', '#2f9e69', '#9ca3af']),
        title=None, legend=alt.Legend(orient='bottom', labelFontSize=16, symbolSize=120))
    arcs = alt.Chart(data).mark_arc(innerRadius=65, outerRadius=130).encode(
        theta=alt.Theta('Start:Q', scale=None, stack=None), theta2=alt.Theta2('End:Q'),
        color=colors, tooltip=['Risk:N', 'Percentage:N'])
    labels = alt.Chart(data).transform_filter('datum.Share > 0').mark_text(
        radius=98, color='white', fontSize=17, fontWeight='bold').encode(
        theta=alt.Theta('Middle:Q', scale=None, stack=None), text='Percentage:N')
    st.altair_chart((arcs + labels).properties(height=380, padding={'top': 28, 'bottom': 22, 'left': 15, 'right': 15}), width='stretch')


def render_dashboard(environ: dict[str, str]) -> None:
    """Select a company then show overall, domain and leaf layers of the same result."""
    names = {}
    message = 'Select a company to explore its saved risk assessment.'
    try:
        with application_database(environ) as database:
            names = dict(saved_companies(database))
    except Exception:
        message = 'Saved company data is temporarily unavailable. Please check the connection or contact the maintainer.'
        st.warning(message)
        if st.button('Retry connection', key='database_retry'):
            st.session_state.pop('dashboard_view', None)
            st.rerun()
    if not names:
        st.info('No saved companies are available to select. The project architecture is available under How it works.')
    number = st.selectbox('Choose a company to assess', tuple(names),
        format_func=lambda n: f'{names[n]} — {n}', index=None,
        placeholder='Select a company to explore its risk', key='dashboard_company', disabled=not names)
    view = None
    if number is None:
        st.session_state.pop('dashboard_view', None)
    else:
        try:
            with st.spinner('Reading saved risk results…'):
                with application_database(environ) as database:
                    view = load_dashboard_snapshot(database, number)
            st.session_state.dashboard_view = view
        except SnapshotUnavailable as error:
            message = str(error)
            st.warning(message)
        except Exception:
            message = 'This saved result could not be loaded. Please ask the maintainer to check database access and prepare the results.'
            st.warning(message)
    if view is not None:
        st.subheader(view.company_name)
        st.caption(f'Company {number} · Saved assessment: {view.assessment_date} · Financial evidence year: {view.evidence_year}')
    overview, domains, variables, architecture = st.tabs(['Overview', 'Domain analysis', 'Variables & standards', 'How it works'])
    with architecture:
        render_architecture()
    if view is None:
        st.session_state.pop('dashboard_view', None)
        with overview:
            if number is None and names:
                render_welcome(len(names))
            else:
                st.info(message)
        for tab in (domains, variables):
            with tab:
                st.info(message)
        return
    with overview:
        left, right = st.columns([1.2, 1], gap='large')
        with left:
            st.markdown('### Overall company risk')
            render_pie(view)
        with right:
            st.markdown('### Governance and Financial risk')
            st.dataframe(view.domain_rows, hide_index=True, width='stretch')
            st.write('Three variables form each domain assessment. Governance and Financial are then combined using evidential reasoning (ER).')
            st.caption('Chart labels are percentages; tables show belief shares between 0.00 and 1.00. These are risk assessments, not probabilities of company failure.')
        with st.expander('How the overall risk is formed', expanded=True):
            st.dataframe(view.overall_inputs, hide_index=True, width='stretch')
            st.write(view.overall_explanation)
            st.write('The saved importance weights are shown above. ER combines weighted support nonlinearly rather than taking an arithmetic average.')
        st.caption('Scope: Governance and Financial only. Explore Domain analysis to follow the result down to its contributing variables.')
    with domains:
        st.markdown('### From variables to domain risk')
        st.write('Each domain combines its three variables with equal importance (1/3 each). Unknown retains missing usable information; missing variables keep their weights.')
        for node in view.domains:
            with st.container(border=True):
                st.markdown(f"#### {node['name']}")
                st.dataframe(node['result'], hide_index=True, width='stretch')
                st.dataframe(node['inputs'], hide_index=True, width='stretch')
                st.write(node['explanation'])
        st.caption('ER normalizes combined evidence support. Disagreement between High and Low does not itself mean Unknown. Reliability discounting is deferred for this MVP.')
    with variables:
        st.markdown('### Six variables and their saved values')
        st.dataframe(view.variables, hide_index=True, width='stretch')
        st.caption('Values come from saved structured company data. Ratios and tenure are calculated from those saved inputs; no new document extraction is triggered.')
        st.markdown('### Risk reference standards')
        st.dataframe(view.standards, hide_index=True, width='stretch')
        st.write('These are approved MVP benchmarks. Values at or beyond a reference receive full support for its risk grade; values between the references use linear interpolation. Unknown means a usable value cannot be determined from the saved data, not a numerical risk threshold.')
        for explanation in view.explanations:
            with st.expander(explanation['name']):
                st.write(explanation['text'])
        with st.expander('Saved inputs behind the calculated values'):
            for node in view.domains:
                st.markdown(f"**{node['name']}**")
                st.dataframe(node['sources'], hide_index=True, width='stretch')
