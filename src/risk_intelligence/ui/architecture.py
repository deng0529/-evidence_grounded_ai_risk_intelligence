"""A visual architecture overview, independent of company selection and DB access."""
from html import escape
import streamlit as st

NODES = (
    (30, 90, '01', 'Companies House', ('Company records and', 'accounts filings'), '#2563EB'),
    (430, 90, '02', 'Cloudflare R2', ('Original iXBRL / XHTML', 'and PDF evidence'), '#2563EB'),
    (830, 90, '03', 'AI-assisted extraction', ('iXBRL parsing first;', 'OpenAI supplements gaps'), '#2563EB'),
    (830, 330, '04', 'Turso · structured facts', ('Saved values, availability', 'and source references'), '#0891B2'),
    (430, 330, '05', 'Reference beliefs', ('Six values + YAML standards', '→ High / Low / Unknown'), '#7C3AED'),
    (30, 330, '06', 'ER risk aggregation', ('Variables → Governance / Financial', '→ Overall company risk'), '#7C3AED'),
    (30, 570, '07', 'Turso · saved results', ('One current result per company', 'prepared by maintenance'), '#0891B2'),
    (430, 570, '08', 'Streamlit interface', ('Explore results and explanations', 'without recalculating risk'), '#059669'),
    (830, 570, '09', 'Streamlit Community Cloud', ('Public demo deployment target', 'after acceptance and release'), '#059669'),
)


def architecture_svg() -> str:
    """Draw the complete pipeline with directional links and an API-facts shortcut."""
    parts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 770" role="img" aria-label="MVP architecture: Companies House, R2, extraction, Turso, reference beliefs, ER and Streamlit Cloud">',
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#94A3B8"/></marker></defs>',
           '<rect x="0" y="0" width="1200" height="770" rx="24" fill="#F7FAFF"/>',
           '<text x="32" y="42" font-family="Arial,sans-serif" font-size="24" font-weight="700" fill="#173B70">Evidence → reasoning → interactive product</text>']
    paths=['M360 165 H420','M760 165 H820','M995 242 V320',
           'M820 405 H770','M420 405 H370','M195 482 V560',
           'M360 645 H420','M760 645 H820']
    for d in paths:
        parts.append(f'<path d="{d}" fill="none" stroke="#94A3B8" stroke-width="3" marker-end="url(#arrow)"/>')
    parts.append('<path d="M195 242 V278 H920 V320" fill="none" stroke="#60A5FA" stroke-width="2" stroke-dasharray="6 5" marker-end="url(#arrow)"/>')
    parts.append('<text x="435" y="268" font-family="Arial,sans-serif" font-size="17" fill="#3B6B9A">Governance facts from the API</text>')
    for x,y,number,title,lines,color in NODES:
        parts.append(f'<rect x="{x}" y="{y+4}" width="330" height="150" rx="16" fill="#DEE7F3" opacity="0.65"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="330" height="150" rx="16" fill="white" stroke="#DBE6F3"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="6" height="150" rx="3" fill="{color}"/>')
        parts.append(f'<circle cx="{x+31}" cy="{y+32}" r="17" fill="{color}"/>')
        parts.append(f'<text x="{x+31}" y="{y+38}" text-anchor="middle" font-family="Arial,sans-serif" font-size="15" font-weight="700" fill="white">{number}</text>')
        parts.append(f'<text x="{x+57}" y="{y+39}" font-family="Arial,sans-serif" font-size="19" font-weight="700" fill="{color}">{escape(title)}</text>')
        for i,line in enumerate(lines):
            parts.append(f'<text x="{x+22}" y="{y+83+i*27}" font-family="Arial,sans-serif" font-size="18" fill="#425570">{escape(line)}</text>')
    parts.append('<text x="32" y="750" font-family="Arial,sans-serif" font-size="16" fill="#536A86">Blue: evidence · Cyan: storage · Purple: risk reasoning · Green: product and deployment</text></svg>')
    return ''.join(parts)


def render_architecture() -> None:
    """Render as an SVG image so the diagram survives HTML sanitization."""
    st.markdown('### How the MVP fits together')
    st.write('A complete journey from public company evidence to an explainable risk assessment.')
    st.image(architecture_svg(), width='stretch')
    st.info('Prepare once, explore many times. The public interface reads saved Turso results; it does not download documents, call OpenAI or recalculate risk.')
    st.caption('AI assists extraction. Reference transformation and ER are deterministic. Cloud deployment is the next release step.')
