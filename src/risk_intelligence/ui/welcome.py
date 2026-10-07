"""Responsive welcome panel for the initial company-selection state."""
import streamlit as st


def render_welcome(company_count: int) -> None:
    """Fill the empty overview with helpful guidance rather than placeholder results."""
    st.html(f"""
<style>
.risk-welcome {{background:linear-gradient(115deg,#EAF2FF 0%,#F2EEFF 64%,#E8FAF4 100%);border:1px solid #D9E5F5;border-radius:24px;padding:36px;margin:18px 0 24px;}}
.risk-kicker {{color:#2563EB;font-size:15px;font-weight:700;letter-spacing:1.3px;}}
.risk-welcome h2 {{color:#173B70;font-size:32px;margin:12px 0;line-height:1.3;}}
.risk-welcome p {{color:#415675;font-size:19px;max-width:780px;line-height:1.65;}}
.risk-prompt {{display:inline-block;background:#2563EB;color:white;padding:12px 18px;border-radius:12px;font-size:18px;font-weight:600;}}
.risk-cards {{display:flex;gap:18px;flex-wrap:wrap;}}
.risk-card {{flex:1;min-width:220px;background:#FFF;border:1px solid #DEE7F3;border-radius:17px;padding:24px;}}
.risk-card strong {{display:block;font-size:19px;color:#173B70;margin:10px 0;}}
.risk-card p {{font-size:17px;color:#526782;line-height:1.6;margin:0;}}
.risk-step {{font-size:15px;font-weight:700;color:#2563EB;}}
@media(max-width:650px){{.risk-welcome{{padding:24px;}}.risk-welcome h2{{font-size:26px;}}}}
</style>
<section class="risk-welcome" aria-label="Welcome to the company risk explorer">
<div class="risk-kicker">EVIDENCE INTO INSIGHT</div>
<h2>Your next insight starts with a company.</h2>
<p>Explore an overall risk assessment, follow its Governance and Financial drivers, and discover the saved values and standards behind each result.</p>
<div class="risk-prompt">↑ Choose a company above to begin</div>
<p style="font-size:16px;margin-bottom:0">{company_count} saved companies · 6 variables · 2 risk domains</p>
</section>
<div class="risk-cards">
<section class="risk-card"><span class="risk-step">01 · OVERVIEW</span><strong>See the big picture</strong><p>High, Low and Unknown support in one clear company risk chart.</p></section>
<section class="risk-card"><span class="risk-step" style="color:#7C3AED">02 · DOMAIN ANALYSIS</span><strong>Understand the drivers</strong><p>Follow how each domain combines its three variables using ER.</p></section>
<section class="risk-card"><span class="risk-step" style="color:#059669">03 · VALUES & STANDARDS</span><strong>Follow the reasoning</strong><p>Inspect the saved values, formulas and reference benchmarks.</p></section>
</div>
""")
    st.caption('Curious about the complete project? Open How it works to see the data, reasoning and cloud architecture.')
