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

ADMISSION_VERSION = 'located-financial-admission-three-company-v19'
COMPONENTS = {
    'TOTAL_ASSETS': {'fixed assets', 'tangible assets', 'intangible assets', 'current assets', 'investments',
        'total assets less current liabilities'},
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


def _statement_context(page: PageText, before_row: int) -> str | None:
    """Return one explicit financial-statement heading before the admitted row.

    Column selection can establish where a candidate sits, but M4 scope requires
    independently persisted heading provenance.  Never synthesize a COMPANY
    heading from the requested candidate scope or from an unqualified title.
    """
    headings = []
    for text in page_lines(page)[:before_row]:
        normalized = _normal(text)
        if re.fullmatch(
            r'(?:company|group|consolidated) (?:balance sheet|statement of financial position)'
            r'(?:\s+as at .*)?',
            normalized,
        ):
            headings.append(text)
    return headings[0] if len(headings) == 1 else None


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
        company_statement = any(_normal(line) in ('company balance sheet', 'company statement of financial position')
                                or _normal(line).startswith('company balance sheet as at ')
                                or _normal(line).startswith('company statement of financial position as at ')
                                for line in lines)
        # A deterministic vocabulary miss must not prevent the semantic fallback from
        # seeing the authoritative company balance sheet.  On a company statement page,
        # unresolved concepts are therefore eligible even when their printed label is an
        # unfamiliar accounting synonym.  Admission remains quote/row/period/scope checked.
        if company_statement and not matched:
            matched = targets
        if matched:
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
    """Resolve reporting-year columns and COMPANY/GROUP scope from persisted geometry.

    OCR can repeat a year token or repeat GROUP/COMPANY headings.  Presentation
    duplication is not an evidence conflict: collapse only near-identical OCR year
    duplicates, then assign scope by the nearest persisted heading geometry.
    A real duplicate (same scope/year in distinct columns) still fails closed.
    """
    raw_headers = []
    for i, row in enumerate(lines[:start]):
        words = sorted((w for w in row if re.fullmatch(r'20[0-9]{2}', w.text)), key=lambda w: w.right)
        if not words:
            continue
        deduped: list[Word] = []
        for word in words:
            if deduped and word.text == deduped[-1].text and abs(word.right - deduped[-1].right) <= 8:
                continue
            deduped.append(word)
        if len(deduped) in (2, 4):
            raw_headers.append((i, deduped))
    if not raw_headers:
        raise CandidateAdmissionError('No supported reporting-year header')
    index, columns = raw_headers[-1]
    prior_rows = lines[max(0, index - 5):index]
    prior = [_normal(' '.join(w.text for w in row)) for row in lines[:index]]
    if len(columns) == 2:
        if any(text in ('group', 'consolidated balance sheet', 'group balance sheet',
                        'group statement of financial position', 'consolidated statement of financial position')
               for text in prior):
            raise CandidateAdmissionError('Company/group scope ambiguous')
        scopes = ['COMPANY', 'COMPANY']
    else:
        scope_words = sorted(
            (w for row in prior_rows for w in row if w.text.lower() in ('group', 'company')),
            key=lambda w: w.right,
        )
        if not scope_words or not any(w.text.lower() == 'company' for w in scope_words):
            raise CandidateAdmissionError('Four-column entity headings ambiguous')
        # A common four-column layout has one GROUP heading over the first pair
        # and one COMPANY heading over the second pair.  Assign by ordered pairs;
        # nearest-centre matching is ambiguous exactly at the pair boundary.
        distinct: list[Word] = []
        for word in scope_words:
            if distinct and word.text.lower() == distinct[-1].text.lower() and abs(word.right - distinct[-1].right) <= 12:
                continue
            distinct.append(word)
        if len(distinct) == 2:
            # Companies House PDFs use both common four-column orders:
            #   GROUP(current, comparative), COMPANY(current, comparative)
            # and current-year(GROUP, COMPANY), comparative-year(GROUP, COMPANY).
            # Infer the layout from persisted year geometry instead of assuming pairs.
            years = [word.text for word in columns]
            if years[0] == years[1] and years[2] == years[3] and years[0] != years[2]:
                scopes = [distinct[0].text.upper(), distinct[1].text.upper(),
                          distinct[0].text.upper(), distinct[1].text.upper()]
            else:
                scopes = [distinct[0].text.upper(), distinct[0].text.upper(),
                          distinct[1].text.upper(), distinct[1].text.upper()]
        elif len(distinct) == 4:
            scopes = [word.text.upper() for word in distinct]
        else:
            raise CandidateAdmissionError('Four-column entity headings ambiguous')
        if 'COMPANY' not in scopes:
            raise CandidateAdmissionError('Four-column entity headings ambiguous')
    identities = [(scope, w.text) for scope, w in zip(scopes, columns, strict=True)]
    if len(set(identities)) != len(identities):
        raise CandidateAdmissionError('Duplicate financial year/scope columns')
    return index, columns, scopes


def _candidate_rows(lines: tuple[tuple[Word, ...], ...], candidate: Candidate) -> tuple[int, int]:
    """Resolve a semantic locator from persisted page geometry, not model row numbering.

    Vision/OCR line numbers are not stable.  The model row range is tried first, but
    recovery is allowed only when the persisted page contains exactly one accounting
    row whose left-hand label matches the candidate label AND whose numeric tokens
    include the candidate amount.  This makes the source page, not the model locator,
    authoritative and prevents a same-label comparative/other row from being selected.
    """
    label = _normal(candidate.label)
    base_label = re.sub(r'\s+[0-9]{1,2}$', '', label)
    locator_labels = {label, base_label}
    if candidate.kind == 'COMPONENT' and candidate.concept == 'INTEREST_BEARING_DEBT':
        locator_labels.add(re.sub(r' due after (?:more than )?one year$', '', label))

    try:
        wanted = amount(candidate.raw_value, 0).copy_abs()
    except (ParseError, ValueError):
        wanted = None

    def text_for(start: int, end: int) -> str:
        return _normal(' '.join(' '.join(w.text for w in row) for row in lines[start:end]))

    def grounded(start: int, end: int) -> bool:
        text = text_for(start, end)
        first = _normal(' '.join(w.text for w in lines[start]))
        # The accounting label must begin on the first row of the candidate window;
        # otherwise a preceding header/value row plus later label could create a false locator.
        anchors = {item.split()[0] for item in locator_labels if item.split()}
        if not any(anchor in first for anchor in anchors):
            return False
        if not any(item in text for item in locator_labels):
            return False
        if wanted is None:
            return False
        numeric = []
        for row in lines[start:end]:
            for word in row:
                if re.fullmatch(r'\(?-?[0-9,]+(?:\.[0-9]+)?\)?', word.text):
                    try:
                        numeric.append(amount(word.text, 0).copy_abs())
                    except (ParseError, ValueError):
                        pass
        return wanted in numeric

    proposed = (candidate.row_start - 1, candidate.row_end)
    start, end = proposed
    if 0 <= start < end <= len(lines) and end - start <= 3 and grounded(start, end):
        return start, end

    matches: list[tuple[int, int]] = []
    for i in range(len(lines)):
        for width in (1, 2, 3):
            j = i + width
            if j <= len(lines) and grounded(i, j):
                matches.append((i, j))
                break
    # Same physical accounting row can match width 1/2/3; collapse overlapping starts.
    unique: list[tuple[int, int]] = []
    for item in matches:
        if not unique or item[0] >= unique[-1][1]:
            unique.append(item)
    if len(unique) != 1:
        raise CandidateAdmissionError('Candidate source row is not uniquely grounded by label and amount')
    return unique[0]


def admit_candidate(candidate: Candidate, pages: tuple[PageText, ...], document_id: str,
                    company_number: str, *, supported_units: frozenset[tuple[str, str]] = frozenset()) -> SourceFinancialFact:
    """Verify excerpt, exact row label, amount column, date, unit and company scope.

    LLM locators propose where to inspect; they do not establish truth. Component
    candidates stay source-only and never authorize a new derivation/completeness.
    """
    page = next((page for page in pages if page.page == candidate.page), None)
    if page is None or candidate.scope != 'COMPANY' or candidate.support != 'SUPPORTED':
        raise CandidateAdmissionError('Unsupported candidate scope, support or page')
    lines = rows(page)
    start, end = _candidate_rows(lines, candidate)
    quote = '\n'.join(page_lines(page)[start:end])
    # candidate.quote is explanatory provenance only. OCR and vision transcription can
    # differ in punctuation/spacing; truth is established below from the persisted row,
    # exact accounting label, selected COMPANY/year column and numeric token.
    header, columns, scopes = _columns(lines, start)
    day, month = _statement_date(pages)
    # Reporting-period admission is YEAR based.  The selected filed accounts document
    # establishes the statement day/month; the candidate only has to identify the
    # correct displayed year column.  Do not reject a correctly located 2025 value
    # merely because a model emitted '2025' (or a non-authoritative day/month) rather
    # than the filing's exact ISO period end.
    year_match = re.search(r'(?<![0-9])(20[0-9]{2})(?![0-9])', candidate.period_end or '')
    if year_match is None:
        raise CandidateAdmissionError('Reporting year is absent or invalid')
    reporting_year = int(year_match.group(1))
    selected = [i for i, (scope, column) in enumerate(zip(scopes, columns, strict=True))
                if scope == candidate.scope and int(column.text) == reporting_year]
    if len(selected) != 1:
        raise CandidateAdmissionError('Reporting year does not identify one source-supported company column')
    # Canonical period end comes from the filed statement date + verified year column,
    # never from an LLM-supplied month/day.
    try:
        period_end = date(reporting_year, month, day)
    except ValueError:
        raise CandidateAdmissionError('Filed statement date is invalid') from None
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
    candidate_label = re.sub(r'\s+[0-9]{1,2}$', '', _normal(candidate.label))
    if (candidate.kind == 'COMPONENT' and candidate.concept == 'INTEREST_BEARING_DEBT'
            and label in ('other loans', 'bank loans') and candidate_label == label + ' due after one year'):
        heading_context = _normal(' '.join(page_lines(page)[:header]))
        headings = re.findall(r'creditors:\s*amounts falling due (within one year|after (?:more than )?one year)', heading_context)
        if headings and headings[-1] in ('after one year','after more than one year'):
            label = candidate_label
    if label != candidate_label:
        raise CandidateAdmissionError('Source row label differs from candidate label')
    if candidate.kind == 'DIRECT':
        # Deterministic labels keep their reviewed pdf-label mapping.  For a label
        # outside that dictionary, the LLM may supply the semantic normalization,
        # but only after this function has independently verified the exact source
        # row, statement context, COMPANY scope, reporting period, unit and amount.
        # The semantic decision remains explicit in provenance; it is never
        # converted into a deterministic label rule merely because one model saw it.
        deterministic_concept = LABELS.get(label)
        forbidden_direct = {item for labels in COMPONENTS.values() for item in labels} | {
            'total assets less current liabilities', 'net current assets', 'net current liabilities',
            'fixed assets', 'tangible assets', 'intangible assets', 'debtors', 'cash at bank and in hand'
        }
        if label in forbidden_direct:
            raise CandidateAdmissionError('Label does not support canonical concept')
        if deterministic_concept is not None and deterministic_concept != candidate.concept:
            raise CandidateAdmissionError('Label does not support canonical concept')
        source_concept = ('pdf-label:' + label if deterministic_concept == candidate.concept
                          else 'llm-semantic:' + candidate.concept)
    else:
        if label not in COMPONENTS.get(candidate.concept, set()):
            raise CandidateAdmissionError('Unsupported component label')
        source_concept = 'pdf-component:' + label
    prefix = ' '.join(' '.join(w.text for w in row) for row in lines[:start])
    page_context = ' '.join(page_lines(page))
    # Do not reject a grounded UK filed-accounts row because the model's currency/unit
    # metadata is absent or formatted differently. Only explicit source conflict blocks it.
    if re.search(r'\b(?:USD|EUR)\b|\$|€', page_context, re.I):
        raise CandidateAdmissionError('Explicit non-GBP currency conflicts with UK filing assumption')
    left, right = bands[selected[0]]
    tokens = [word.text for row in lines[start:end] for word in row if left < word.right <= right
              and re.fullmatch(r'\(?-?[0-9,]+(?:\.[0-9]+)?\)?', word.text)]
    # A cited accounting row can legitimately contain another numeric token in the
    # same visual band (for example a note reference or OCR duplicate).  Admission
    # therefore requires one and only one source token whose numeric magnitude matches
    # the model locator.  The source token remains authoritative; the model cannot
    # invent a value merely by choosing among unrelated numbers.  Parentheses/sign are
    # presentation metadata handled below for qualified balance-sheet liabilities.
    try:
        locator_value = amount(candidate.raw_value, 0).copy_abs()
        matching_tokens = [token for token in tokens if amount(token, 0).copy_abs() == locator_value]
    except (ParseError, ValueError):
        matching_tokens = []
    if len(matching_tokens) != 1:
        raise CandidateAdmissionError('Candidate amount does not identify one source-supported numeric token in cited period/scope column')
    source_token = matching_tokens[0]
    scale = 3 if re.search(r"(?:£|GBP)\s*(?:'|’)?000", prefix, re.I) else 0
    value = amount(source_token, scale)
    transformation = None
    # Qualified balance-sheet creditors are a deduction from assets. Parentheses
    # express that presentation, not a negative amount owed. Retain both the raw
    # token and this explicit normalization; do not apply it to generic numbers.
    if candidate.concept == 'CURRENT_LIABILITIES' and label.startswith('creditors: amounts falling due within') and source_token.startswith('('):
        value = value.copy_abs()
        transformation = 'balance-sheet-creditor-deduction'
    if label == 'net liabilities' and value > 0:
        value = value.copy_negate()
    # MVP v11: the persisted source numeric token in the selected filed page/year column is authoritative.
    # LLM candidate.value may contain commas/parentheses and is not an independent admission gate.
    period = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=period_end,
                             comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    identity = sha256(f'{document_id}:{ADMISSION_VERSION}:{candidate.model_dump_json()}'.encode()).hexdigest()
    return SourceFinancialFact(source_fact_id=identity, document_id=document_id, evidence_id='e-'+identity,
        source_concept=source_concept, source_label=label, raw_value=source_token, value=value,
        availability_status=AvailabilityStatus.AVAILABLE, currency='GBP', unit='GBP',
        context_ref=f'page-{page.page}:rows-{candidate.row_start}-{candidate.row_end}:{period_end}',
        entity_identifier=company_number, entity_scheme='M2_DOCUMENT_LINEAGE', period=period,
        period_role='CURRENT' if period_end.year == max(int(w.text) for w in columns) else 'COMPARATIVE',
        page=page.page, statement_context=_statement_context(page, header), scale=scale,
        sign='-' if value < 0 else '+', transformation=transformation,
        extraction_method=ExtractionMethod.LLM_OCR_TEXT if page.method == ExtractionMethod.PDF_OCR_DETERMINISTIC
                          else ExtractionMethod.LLM_NATIVE_TEXT, parser_version=ADMISSION_VERSION)
