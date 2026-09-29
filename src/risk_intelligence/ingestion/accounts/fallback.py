"""Bound relevant PDF evidence and independently verify located LLM candidates."""

from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import ReportingPeriod
from .llm import Candidate, CandidateAdmissionError
from .models import CanonicalConcept, SourceFinancialFact
from .pdf import LABELS, MONTHS, PageText, Word, amount, rows

ADMISSION_VERSION = 'located-financial-admission-v3'
COMPONENTS = {
    'TOTAL_ASSETS': {'fixed assets', 'tangible assets', 'intangible assets', 'current assets', 'investments'},
    'INTEREST_BEARING_DEBT': {'invoice discounting facility', 'invoice discounting', 'other loans',
        'other loans due within one year', 'other loans due after more than one year',
        'other loans due after one year', 'bank loans due after one year',
        'bank loans', 'finance lease liabilities', 'hire purchase liabilities'},
}
RELEVANCE = {
    'CURRENT_ASSETS': r'current assets', 'CURRENT_LIABILITIES': r'creditors|current liabilities',
    'INVENTORY': r'\bstocks\b|inventor', 'NET_ASSETS': r'net assets|net liabilities',
    'TOTAL_ASSETS': r'total assets|fixed assets|tangible assets|intangible assets',
    'INTEREST_BEARING_DEBT': r'invoice discount|other loans|bank loans|borrowings|interest.bearing|finance leas|hire purchase',
}


def _normal(text: str) -> str:
    return ' '.join(text.lower().split())


def page_lines(page: PageText) -> tuple[str, ...]:
    """Stable one-based line locators derive from persisted layout, not model output."""
    return tuple(' '.join(word.text for word in row) for row in rows(page))


def select_evidence(pages: tuple[PageText, ...], targets: tuple[CanonicalConcept, ...]) -> tuple[str, tuple[PageText, ...]]:
    """Select at most four relevant pages/40000 characters, prioritizing supported tables.

    Complete selected rows and headers are supplied. Unsupported or truncated-away
    material never licenses admission; selection is not a completeness assertion.
    """
    candidates = []
    for page in pages:
        lines = page_lines(page)
        normalized = _normal('\n'.join(lines))
        if any(re.fullmatch(r'(?:consolidated|group) (?:balance sheet|statement of financial position)', _normal(line)) for line in lines):
            continue
        matched = tuple(concept for concept in targets if re.search(RELEVANCE[concept], normalized))
        if matched:
            company_statement = any(_normal(line) in ('company balance sheet', 'company statement of financial position') for line in lines)
            table_rows = rows(page)
            supported_table = False
            for index, line in enumerate(lines):
                if not any(re.search(RELEVANCE[concept], _normal(line)) for concept in matched):
                    continue
                try:
                    _columns(table_rows, index)
                    supported_table = True
                    break
                except CandidateAdmissionError:
                    continue
            candidates.append((0 if company_statement else 1 if supported_table else 2, page.page, page, matched))
    selected: list[PageText] = []
    blocks = []
    for _, _, page, matched in sorted(candidates, key=lambda item: item[:2]):
        block = {'page': page.page, 'relevant_concepts': matched,
                 'rows': [{'row': i + 1, 'text': text} for i, text in enumerate(page_lines(page))]}
        trial = json.dumps({'unresolved_concepts': targets, 'pages': blocks + [block]}, ensure_ascii=False, sort_keys=True)
        if len(selected) >= 4 or len(trial) > 40000:
            continue
        selected.append(page)
        blocks.append(block)
    return json.dumps({'unresolved_concepts': targets, 'pages': blocks}, ensure_ascii=False, sort_keys=True), tuple(selected)


def _statement_date(pages: tuple[PageText, ...]) -> tuple[int, int]:
    dates = set()
    for page in pages:
        lines = page_lines(page)
        if not any(_normal(line) in ('company balance sheet', 'company statement of financial position') for line in lines):
            continue
        matches = re.findall(r'\b(?:as at|at)\s+([0-3]?[0-9])\s+(' + '|'.join(MONTHS) + r')\s+(20[0-9]{2})\b', _normal(' '.join(lines)))
        dates.update((int(day), MONTHS.index(month) + 1) for day, month, _ in matches)
    if len(dates) != 1:
        raise CandidateAdmissionError('Reporting date context is ambiguous or absent')
    return next(iter(dates))


def _columns(lines: tuple[tuple[Word, ...], ...], start: int) -> tuple[int, list[Word], list[str]]:
    headers = [(i, [w for w in row if re.fullmatch(r'20[0-9]{2}', w.text)])
               for i, row in enumerate(lines[:start])]
    headers = [(i, words) for i, words in headers if len(words) in (2, 4)]
    if not headers:
        raise CandidateAdmissionError('No supported reporting-year header')
    index, columns = headers[-1]
    prior = [_normal(' '.join(w.text for w in row)) for row in lines[:index]]
    if len(columns) == 2:
        if not any(text in ('company balance sheet', 'company statement of financial position', 'company') for text in prior):
            raise CandidateAdmissionError('Company scope not established by heading')
        if any(text in ('group', 'consolidated balance sheet', 'group balance sheet') for text in prior):
            raise CandidateAdmissionError('Company/group scope ambiguous')
        scopes = ['COMPANY', 'COMPANY']
    else:
        scope_rows = []
        for row in lines[max(0,index-4):index]:
            words = [w for w in row if w.text.lower() in ('group', 'company')]
            labels = [w.text.upper() for w in words]
            if sorted(labels) == ['COMPANY', 'GROUP']:
                scope_rows.append([scope for scope in labels for _ in range(2)])
            elif sorted(labels) == ['COMPANY', 'COMPANY', 'GROUP', 'GROUP'] and all(
                    abs(word.right-column.right) <= 18 for word,column in zip(words,columns,strict=True)):
                # A scope heading may be repeated above each individual year.
                scope_rows.append(labels)
        if len(scope_rows) != 1:
            raise CandidateAdmissionError('Four-column entity headings ambiguous')
        scopes = scope_rows[0]
    if len({(scope, w.text) for scope, w in zip(scopes, columns, strict=True)}) != len(columns):
        raise CandidateAdmissionError('Duplicate financial year/scope columns')
    return index, columns, scopes


def admit_candidate(candidate: Candidate, pages: tuple[PageText, ...], document_id: str,
                    company_number: str) -> SourceFinancialFact:
    """Verify excerpt, exact row label, amount column, date, unit and company scope.

    LLM locators propose where to inspect; they do not establish truth. Component
    candidates stay source-only and never authorize a new derivation/completeness.
    """
    page = next((page for page in pages if page.page == candidate.page), None)
    if page is None or candidate.scope != 'COMPANY' or candidate.support != 'SUPPORTED':
        raise CandidateAdmissionError('Unsupported candidate scope, support or page')
    lines = rows(page)
    start, end = candidate.row_start - 1, candidate.row_end
    if not 0 <= start < end <= len(lines) or end - start > 3:
        raise CandidateAdmissionError('Candidate row locator is invalid')
    quote = '\n'.join(page_lines(page)[start:end])
    if _normal(candidate.quote) != _normal(quote):
        raise CandidateAdmissionError('Candidate excerpt differs from persisted evidence')
    header, columns, scopes = _columns(lines, start)
    day, month = _statement_date(pages)
    try:
        period_end = date.fromisoformat(candidate.period_end)
    except ValueError:
        raise CandidateAdmissionError('Invalid reporting period') from None
    selected = [i for i, (scope, column) in enumerate(zip(scopes, columns, strict=True))
                if scope == candidate.scope and int(column.text) == period_end.year]
    if len(selected) != 1 or (period_end.day, period_end.month) != (day, month):
        raise CandidateAdmissionError('Reporting period lacks source support')
    spacing = min(right.right - left.right for left, right in zip(columns, columns[1:]))
    fraction, tolerance = (0.75,18) if len(columns) == 2 else (0.35,12)
    if spacing * (1-fraction) <= tolerance:
        raise CandidateAdmissionError('Overlapping value columns')
    bands = [(column.right - spacing * fraction, column.right + tolerance) for column in columns]
    label = _normal(' '.join(re.sub(r'\s+[0-9]{1,2}$', '', ' '.join(
        word.text for word in row if word.right <= bands[0][0])) for row in lines[start:end]))
    # A model can include a maturity qualifier from the note's heading. Admit
    # only these exact base labels and the nearest explicit creditor section;
    # finding a maturity phrase elsewhere in the document is insufficient.
    candidate_label = _normal(candidate.label)
    if (candidate.kind == 'COMPONENT' and candidate.concept == 'INTEREST_BEARING_DEBT'
            and label in ('other loans', 'bank loans') and candidate_label == label + ' due after one year'):
        heading_context = _normal(' '.join(page_lines(page)[:header]))
        headings = re.findall(r'creditors:\s*amounts falling due (within one year|after (?:more than )?one year)', heading_context)
        if headings and headings[-1] in ('after one year','after more than one year'):
            label = candidate_label
    if label != candidate_label:
        raise CandidateAdmissionError('Source row label differs from candidate label')
    if candidate.kind == 'DIRECT':
        if LABELS.get(label) != candidate.concept:
            raise CandidateAdmissionError('Label does not support canonical concept')
        source_concept = 'pdf-label:' + label
    else:
        if label not in COMPONENTS.get(candidate.concept, set()):
            raise CandidateAdmissionError('Unsupported component label')
        source_concept = 'pdf-component:' + label
    prefix = ' '.join(' '.join(w.text for w in row) for row in lines[:start])
    if candidate.currency != 'GBP' or candidate.unit not in ('GBP', '£') or not re.search(r'£|\bGBP\b', prefix, re.I):
        raise CandidateAdmissionError('Currency/unit lacks source support')
    if re.search(r'\b(?:USD|EUR)\b|\$|€', prefix, re.I):
        raise CandidateAdmissionError('Ambiguous currency context')
    left, right = bands[selected[0]]
    tokens = [word.text for row in lines[start:end] for word in row if left < word.right <= right
              and re.fullmatch(r'\(?-?[0-9,]+(?:\.[0-9]+)?\)?', word.text)]
    if len(tokens) != 1 or tokens[0] != candidate.raw_value:
        raise CandidateAdmissionError('Numeric token is not unique in cited period/scope column')
    scale = 3 if re.search(r"(?:£|GBP)\s*(?:'|’)?000", prefix, re.I) else 0
    value = amount(tokens[0], scale)
    transformation = None
    # Qualified balance-sheet creditors are a deduction from assets. Parentheses
    # express that presentation, not a negative amount owed. Retain both the raw
    # token and this explicit normalization; do not apply it to generic numbers.
    if candidate.concept == 'CURRENT_LIABILITIES' and label.startswith('creditors: amounts falling due within') and tokens[0].startswith('('):
        if not any(_normal(text) == 'company balance sheet' for text in page_lines(page)[:header]):
            raise CandidateAdmissionError('Liability deduction sign context absent')
        value = value.copy_abs()
        transformation = 'balance-sheet-creditor-deduction'
    if label == 'net liabilities' and value > 0:
        value = value.copy_negate()
    try:
        if candidate.value is None or Decimal(candidate.value) != value:
            raise CandidateAdmissionError('Normalized candidate value differs from source amount')
    except InvalidOperation:
        raise CandidateAdmissionError('Invalid candidate decimal') from None
    period = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=period_end,
                             comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    identity = sha256(f'{document_id}:{ADMISSION_VERSION}:{candidate.model_dump_json()}'.encode()).hexdigest()
    return SourceFinancialFact(source_fact_id=identity, document_id=document_id, evidence_id='e-'+identity,
        source_concept=source_concept, source_label=label, raw_value=tokens[0], value=value,
        availability_status=AvailabilityStatus.AVAILABLE, currency='GBP', unit='GBP',
        context_ref=f'page-{page.page}:rows-{candidate.row_start}-{candidate.row_end}:{period_end}',
        entity_identifier=company_number, entity_scheme='M2_DOCUMENT_LINEAGE', period=period,
        period_role='CURRENT' if period_end.year == max(int(w.text) for w in columns) else 'COMPARATIVE',
        page=page.page, scale=scale, sign='-' if value < 0 else '+', transformation=transformation,
        extraction_method=ExtractionMethod.LLM_OCR_TEXT if page.method == ExtractionMethod.PDF_OCR_DETERMINISTIC
                          else ExtractionMethod.LLM_NATIVE_TEXT, parser_version=ADMISSION_VERSION)
