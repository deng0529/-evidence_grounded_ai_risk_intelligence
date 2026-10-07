"""Standalone public MVP entry point; no maintenance navigation or write controls."""
import os
import streamlit as st
from risk_intelligence.services.dashboard_config import CONFIG
from .dashboard import render_dashboard

STYLE = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display:none;}
[data-testid="stAppViewContainer"] .stMarkdown p,
[data-testid="stAppViewContainer"] .stMarkdown li {font-size:18px;line-height:1.6;}
[data-testid="stCaptionContainer"] p {font-size:16px !important;line-height:1.55;}
[data-testid="stWidgetLabel"] p {font-size:19px !important;font-weight:600;}
[data-baseweb="select"] {font-size:18px;}
button[data-baseweb="tab"] p {font-size:19px !important;font-weight:600;}
[data-testid="stExpander"] summary p {font-size:18px !important;}
[data-testid="stAppViewContainer"] h1 {color:#173B70;}
[data-testid="stAppViewContainer"] h2, [data-testid="stAppViewContainer"] h3 {color:#24568B;}
[data-testid="stCaptionContainer"] p {color:#526782;}
button[data-baseweb="tab"][aria-selected="true"] p {color:#2563EB;}
.block-container {padding-top:2rem;padding-bottom:3rem;max-width:1450px;}
@media(max-width:700px){button[data-baseweb="tab"] p {font-size:16px !important;} h1 {font-size:30px !important;}}
</style>
"""


def main() -> None:
    """Show the standalone dashboard and safe responses for recoverable failures."""
    st.set_page_config(page_title=CONFIG['title'],layout='wide',initial_sidebar_state='collapsed')
    st.html(STYLE)
    st.title(CONFIG['title'])
    st.write(CONFIG['intro'])
    try:
        render_dashboard(dict(os.environ))
    except Exception:
        st.session_state.pop('dashboard_view',None)
        st.warning('This view is temporarily unavailable. Please try again or ask the maintainer to check the saved results. No new risk values have been generated.')
        if st.button('Try again',key='public_retry'):
            st.rerun()
