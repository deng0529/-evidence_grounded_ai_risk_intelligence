"""Foundation semantic completion from original XHTML, independent of parser contexts."""
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import AccountsIngestion
    from risk_intelligence.domain.evidence import RawEvidence

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import ReportingPeriod
from risk_intelligence.ingestion.companies_house.client import ParseError
from .llm import IxbrlSemanticCandidate, IxbrlSemanticResult
from .models import CandidateDecision, ExtractionResult, FallbackAudit, SourceFinancialFact
from .semantic_values import semantic_amount, semantic_period
from .period_selection import select_period
from .coverage import TARGETS, resolved_concepts, with_coverage, coverage_note

VERSION = 'financial-ixbrl-semantic-v32-expert'


class _VisibleText(HTMLParser):
    """Retain visible text for quote verification, ignoring executable/style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _compact(value: str) -> str:
    return ' '.join(value.split())


def _printed_amount_present(raw: str, visible: str) -> bool:
    """Verify numeric source support despite grouping, spaces and HTML boundaries."""
    amount, _ = semantic_amount(raw, '', 'GBP')
    tokens = re.findall(r'(?<![\w.])[+-]?(?:\d{1,3}(?:(?:,\s*|[ \u00a0])\d{3})+|\d+)(?:\.\d+)?(?![\w.])', visible)
    tokens += re.findall(r'(?<![\w.,])[+-]?\d+(?:\.\d+)?(?![\w.,])', visible)
    for token in tokens:
        try:
            printed, _ = semantic_amount(token, '', 'GBP')
        except ParseError:
            continue
        if printed.copy_abs() == amount.copy_abs():
            return True
    return False


def admit(candidate: IxbrlSemanticCandidate, *, visible: str, requested: tuple[str, ...],
          document_id: str, number: str, year: int, period_end: date) -> SourceFinancialFact:
    """Verify company scope and printed money while preserving the displayed year."""
    if candidate.concept not in requested or candidate.scope != 'COMPANY' or candidate.support != 'SUPPORTED':
        raise ParseError('Candidate is not a requested supported COMPANY observation')
    # Semantic excerpts support human review. HTML whitespace/tag boundaries and
    # company-specific labels must not become exact-string admission conditions.
    quote = _compact(candidate.quote)
    if not candidate.label.strip() or not quote:
        raise ParseError('The semantic observation lacks a source label/review excerpt')
    value, scale = semantic_amount(candidate.raw_value, candidate.unit, candidate.currency)
    if not _printed_amount_present(candidate.raw_value or '', visible):
        raise ParseError('The printed monetary amount was not located in the original XHTML')
    period_end = semantic_period(candidate.reporting_year, year, period_end)
    label = _compact(candidate.label).lower()
    if candidate.concept == 'CURRENT_LIABILITIES':
        value = value.copy_abs()
    if candidate.concept == 'NET_ASSETS' and 'net liabilities' in label:
        value = -abs(value)
    if candidate.kind == 'COMPONENT':
        if candidate.concept != 'TOTAL_ASSETS':
            raise ParseError('Unsupported semantic bridge')
        concept = 'pdf-component:total assets less current liabilities'
    else:
        concept = 'llm-semantic:' + candidate.concept
    identity = sha256((VERSION + document_id + period_end.isoformat() + candidate.model_dump_json()).encode()).hexdigest()
    return SourceFinancialFact(source_fact_id=identity, document_id=document_id, evidence_id='e-' + identity,
        source_concept=concept, source_label=candidate.label, raw_value=candidate.raw_value,
        value=value, availability_status=AvailabilityStatus.AVAILABLE, currency='GBP', unit='GBP',
        context_ref='xhtml-quote-' + sha256(quote.encode()).hexdigest(), entity_identifier=number,
        entity_scheme='M2_DOCUMENT_LINEAGE', period=ReportingPeriod(period_type=PeriodType.INSTANT,
            period_end=period_end, comparability_status=ComparabilityStatus.REVIEW_REQUIRED),
        period_role='CURRENT', scale=scale, sign='-' if value < 0 else '+',
        transformation=VERSION, extraction_method=ExtractionMethod.LLM_NATIVE_TEXT, parser_version=VERSION)


def complete(service: 'AccountsIngestion', raw: 'RawEvidence', run_id: str, number: str, deterministic: ExtractionResult,
             year: int | None, authoritative_period_end: date | None) -> ExtractionResult:
    """Complete missing selected-statement facts; preserve facts on technical failure."""
    year = year or max((p.period_end.year for p in deterministic.periods), default=1900)
    deterministic = select_period(deterministic, year, authoritative_period_end)
    selected_end = deterministic.periods[0].period_end
    available = resolved_concepts(deterministic.facts, service.registry, number, raw.source_id, run_id)
    targets = tuple(c for c in TARGETS if c not in available)
    progress = service._progress
    if progress:
        progress('deterministic_coverage', f'iXBRL resolved {len(available)}/5 before OpenAI '
                 f'(including Python derivations); OpenAI targets {len(targets)}/5: {", ".join(targets) or "None"}')
    def finish(result: ExtractionResult) -> ExtractionResult:
        selected = select_period(result, year, authoritative_period_end)
        found = resolved_concepts(selected.facts, service.registry, number, raw.source_id, run_id)
        audited = with_coverage(selected, route='iXBRL/XHTML', before=available,
                                requested=targets, after=found)
        if progress:
            progress('financial_route_summary', coverage_note(audited))
        return audited

    if not targets:
        if progress:
            progress('semantic_not_needed', 'All five selected-statement financial concepts are deterministic; OpenAI is not needed')
        return finish(deterministic.model_copy(update={'complete': True}))
    period_end = selected_end
    periods = {p.model_dump_json(): p for p in deterministic.periods}
    if progress:
        progress('semantic_required', f'iXBRL missing {len(targets)}/5 selected-statement concepts: {", ".join(targets)}')
    try:
        if service.llm is None or not service.llm.enabled:
            raise ParseError('OpenAI iXBRL semantic extraction is not configured')
        original = service.evidence.read(raw.raw_evidence_id).decode('utf-8-sig')
        parser = _VisibleText()
        parser.feed(original)
        visible = _compact(' '.join(parser.parts))
        evidence = json.dumps({'unresolved_concepts': targets, 'preferred_reporting_year': year,
                               'selected_statement_period': period_end.isoformat() if deterministic.facts else None,
                               'original_ixbrl_xhtml': original, 'readable_statement_text': visible}, ensure_ascii=False)
        if progress:
            progress('semantic_llm', 'Sending original iXBRL/XHTML directly to OpenAI; parser contexts are not required')
        output, _ = service.cache.run(raw, run_id, 'LLM', VERSION,
            {'model': service.llm.model, 'config': service.llm.config_version,
             'request_sha': sha256(evidence.encode()).hexdigest()}, lambda _: service.llm.extract_ixbrl(evidence))
        artifact = json.loads(output)
        if artifact.get('status') != 'completed':
            raise ParseError('OpenAI iXBRL response was incomplete')
        candidates = IxbrlSemanticResult.model_validate_json(artifact['output']).candidates
    except (ParseError, ValueError, KeyError, UnicodeError) as error:
        return finish(deterministic.model_copy(update={'periods': tuple(periods.values()),
            'completeness_notes': (*deterministic.completeness_notes, f'TECHNICAL_EXTRACTION_FAILURE: {error}'),
            'fallback': FallbackAudit(targets=targets, pages=(), status='EXTRACTION_FAILED')}))
    if progress:
        progress('openai_response', 'OpenAI iXBRL semantic artifact returned; verifying source candidates')
    facts = list(deterministic.facts)
    decisions = []
    for index, candidate in enumerate(candidates):
        identity = None
        try:
            fact = admit(candidate, visible=visible, requested=targets, document_id=raw.document_id,
                         number=number, year=year, period_end=period_end)
            facts.append(fact)
            identity = fact.source_fact_id
            status, reason = 'AVAILABLE', 'Company statement monetary observation accepted; source excerpt retained'
        except ParseError as error:
            status, reason = ('EXTRACTION_FAILED' if candidate.support == 'UNRESOLVED' else 'VALIDATION_FAILED'), str(error)
        decisions.append(CandidateDecision(candidate_index=index, concept=candidate.concept,
            kind=candidate.kind, period_end=str(candidate.reporting_year or year), status=status,
            reason=reason, source_fact_id=identity))
        if progress:
            progress('semantic_decision', f'{candidate.concept}: {status}; label={candidate.label!r}; raw={candidate.raw_value}; unit={candidate.unit}; reported_year={candidate.reporting_year}; reason={reason}')
    if progress:
        progress('semantic_validation', f'iXBRL semantic candidates verified: {sum(d.status == 'AVAILABLE' for d in decisions)} accepted')
    return finish(deterministic.model_copy(update={'facts': tuple(facts), 'periods': tuple(periods.values()), 'complete': True,
        'fallback': FallbackAudit(targets=targets, pages=(), status='COMPLETE', decisions=tuple(decisions))}))
