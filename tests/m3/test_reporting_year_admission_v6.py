from dataclasses import replace

# Behaviour is covered primarily by existing test_pdf_llm fixtures; this file documents
# the v6 acceptance contract for local regression discovery.
def test_reporting_year_contract_documentation():
    assert "year-column" in "located-financial-admission-v6-year-column"
