"""Direct multimodal semantic extraction from filed PDF pages.

This Foundation route deliberately does not use OCR as an extraction or admission gate.
The filed PDF is immutable evidence; OpenAI reads the complete file and returns bounded
structured candidates. Deterministic code then enforces requested concept, COMPANY scope,
current reporting period, numeric/currency shape and preserves page/quote provenance.
"""
from datetime import date
from hashlib import sha256

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import ReportingPeriod
from risk_intelligence.ingestion.companies_house.client import ParseError
from .llm import Candidate, PdfSemanticCandidate
from .models import SourceFinancialFact
from .semantic_values import semantic_amount, semantic_period

PARSER_VERSION = 'openai-pdf-semantic-v30-closest-column'


def admit_pdf_candidate(candidate: Candidate | PdfSemanticCandidate, *, document_id: str, company_number: str,
                        rendered_pages: frozenset[int], requested: frozenset[str],
                        requested_reporting_year: int, authoritative_period_end: date | None = None) -> SourceFinancialFact:
    """Admit substantive PDF evidence without OCR/layout-specific hard gates."""
    if candidate.concept not in requested:
        raise ParseError('Candidate concept was not requested')
    if candidate.scope != 'COMPANY':
        raise ParseError(f'OpenAI could not establish COMPANY scope (returned scope={candidate.scope}); not confirmed nondisclosure')
    if candidate.support != 'SUPPORTED':
        raise ParseError('OpenAI could not establish a supported monetary value; this is unresolved extraction, not confirmed nondisclosure')
    if candidate.page not in rendered_pages:
        raise ParseError('Candidate page is outside submitted filed PDF evidence')
    if not candidate.label.strip() or not candidate.quote.strip():
        raise ParseError('Candidate lacks supporting filed-PDF label/quote')
    if candidate.raw_value is None or candidate.value is None:
        raise ParseError('Candidate has no supported monetary value')
    # Year/date describe the extracted column. The search preference cannot reject it.
    period_end = semantic_period(candidate.period_end, requested_reporting_year, authoritative_period_end)
    value, scale = semantic_amount(candidate.raw_value, candidate.unit, candidate.currency)
    label = ' '.join(candidate.label.split()).lower()
    transformation = 'openai-pdf-semantic'
    if candidate.concept == 'CURRENT_LIABILITIES' and value < 0:
        value = value.copy_abs()
        transformation += ';liability-magnitude'
    if candidate.concept == 'NET_ASSETS' and 'net liabilities' in label and value > 0:
        value = value.copy_negate()
        transformation += ';net-liabilities-sign'
    if candidate.kind == 'COMPONENT':
        if candidate.concept != 'TOTAL_ASSETS':
            raise ParseError('Unsupported semantic bridge candidate')
        source_concept = 'pdf-component:total assets less current liabilities'
    else:
        source_concept = 'llm-semantic:' + candidate.concept
    period = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=period_end,
                             comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    identity = sha256((PARSER_VERSION + ':' + document_id + ':' + period_end.isoformat() + ':' + candidate.model_dump_json()).encode()).hexdigest()
    return SourceFinancialFact(source_fact_id=identity, document_id=document_id, evidence_id='e-' + identity,
        source_concept=source_concept, source_label=candidate.label.strip(), raw_value=candidate.raw_value,
        value=value, availability_status=AvailabilityStatus.AVAILABLE, currency='GBP', unit='GBP',
        context_ref=f'pdf-page-{candidate.page}:{period_end.isoformat()}', entity_identifier=company_number,
        entity_scheme='M2_DOCUMENT_LINEAGE', period=period, period_role='CURRENT', page=candidate.page,
        statement_context='Company balance sheet', scale=scale, sign='-' if value < 0 else '+',
        transformation=transformation, extraction_method=ExtractionMethod.LLM_NATIVE_TEXT,
        parser_version=PARSER_VERSION)
