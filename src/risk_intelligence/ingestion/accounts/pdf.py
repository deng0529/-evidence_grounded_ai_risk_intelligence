"""Layout-preserving PDF/OCR text and conservative balance-sheet extraction."""

from datetime import date
from decimal import Decimal
from hashlib import sha256
import re

from risk_intelligence.domain.common import Contract, Text
from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import ReportingPeriod
from risk_intelligence.ingestion.companies_house.client import ParseError
from .models import ExtractionResult, SourceFinancialFact, DebtSchedule
from .derivation import COMPONENT_LABELS, COMPLETENESS_QUOTE
from .scope import STATEMENT_HEADING

PARSER_VERSION = 'pdf-table-v4'
LABELS = {
    'current assets': 'CURRENT_ASSETS',
    'total current assets': 'CURRENT_ASSETS',
    'creditors: amounts falling due within one year': 'CURRENT_LIABILITIES',
    'creditors: amounts falling due within 1 year': 'CURRENT_LIABILITIES',
    'current liabilities': 'CURRENT_LIABILITIES',
    'stocks': 'INVENTORY', 'inventories': 'INVENTORY', 'inventory': 'INVENTORY',
    'net assets': 'NET_ASSETS', 'net liabilities': 'NET_ASSETS',
    'net assets/(liabilities)': 'NET_ASSETS', 'net assets / (liabilities)': 'NET_ASSETS',
    'net assets (liabilities)': 'NET_ASSETS',
    'total assets': 'TOTAL_ASSETS',
    'total interest-bearing debt': 'INTEREST_BEARING_DEBT',
    'total interest bearing borrowings': 'INTEREST_BEARING_DEBT',
}
MONTHS = ('january february march april may june july august september october november december').split()


class Word(Contract):
    """Position is PDF geometry, never a financial numeric value."""

    x: float
    y: float
    right: float
    text: Text


class PageText(Contract):
    """Derived layout artifact always references the original one-based PDF page."""

    page: int
    words: tuple[Word, ...]
    method: ExtractionMethod


def pdf_pages(content: bytes, *, ocr: bool = False, tessdata: str | None = None,
              max_pages: int = 100) -> tuple[PageText, ...]:
    """Extract layout, OCR only image/unusable pages when explicitly enabled.

    Callers persist returned OCR artifacts and reuse them by PDF/engine/config
    fingerprint. Absence of OCR resources is an explicit extraction failure.
    """
    import pymupdf
    if not content.startswith(b'%PDF-') or len(content) > 32 * 1024 * 1024:
        raise ParseError('Unsupported PDF content or size')
    try:
        with pymupdf.open(stream=content, filetype='pdf') as document:
            if document.is_encrypted or not 1 <= len(document) <= max_pages:
                raise ParseError('Encrypted PDF or page bound exceeded')
            result = []
            for index, page in enumerate(document):
                words = page.get_text('words')
                # A short header over a scanned body is not a usable native page.
                image_coverage = sum(abs(rect.width * rect.height) for image in page.get_images()
                                     for rect in page.get_image_rects(image[0])) / max(1, page.rect.width * page.rect.height)
                needs_ocr = len(words) < 15 or image_coverage > 0.6
                method = ExtractionMethod.PDF_NATIVE_DETERMINISTIC
                if needs_ocr:
                    if not ocr:
                        raise ParseError('PDF requires OCR')
                    textpage = page.get_textpage_ocr(language='eng', dpi=200, full=True, tessdata=tessdata)
                    words = page.get_text('words', textpage=textpage)
                    method = ExtractionMethod.PDF_OCR_DETERMINISTIC
                result.append(PageText(page=index + 1, words=tuple(Word(x=float(w[0]), y=float(w[1]),
                    right=float(w[2]), text=w[4]) for w in words), method=method))
            return tuple(result)
    except ParseError:
        raise
    except Exception:
        # Native parser/OCR errors can contain file paths or source content.
        raise ParseError('PDF/OCR processing failed; verify parser resources') from None


def rows(page: PageText) -> tuple[tuple[Word, ...], ...]:
    """Group words by baseline tolerance, retaining horizontal column positions."""
    result: list[list[Word]] = []
    for word in sorted(page.words, key=lambda w: (w.y, w.x)):
        if not result or abs(word.y - result[-1][0].y) > 3:
            result.append([])
        result[-1].append(word)
    return tuple(tuple(sorted(row, key=lambda w: w.x)) for row in result)


def statement_context(page: PageText, before_y: float) -> str | None:
    """Retain preceding statement headings verbatim in layout order for a PDF row.

    The evidence page and these quotes locate the context. Competing headings
    are retained, not selected by proximity or converted into Company scope.
    """
    headings = [' '.join(word.text for word in row) for row in rows(page)
                if row[0].y < before_y]
    headings = [heading for heading in headings
                if STATEMENT_HEADING.fullmatch(' '.join(heading.split()))]
    return '\n'.join(headings) or None


def amount(token: str, scale: int = 0) -> Decimal:
    """Normalize an explicit printed amount; a dash is not assumed to mean zero."""
    if not re.fullmatch(r'\(?-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?\)?', token):
        raise ParseError('Unsupported PDF monetary token')
    if token.startswith('(') != token.endswith(')'):
        raise ParseError('Unbalanced monetary sign')
    value = Decimal(token.strip('()').replace(',', ''))
    sign, digits, exponent = value.as_tuple()
    return Decimal((1 if token.startswith('(') else sign, digits, exponent + scale))


def extract_pdf(pages: tuple[PageText, ...], document_id: str, company_number: str) -> ExtractionResult:
    """Associate exact approved row labels with aligned reporting-year columns.

    Requires a balance-sheet title, a source day/month/date, explicit currency,
    and uniquely aligned numeric columns. Ambiguous/group tables fail closed.
    """
    facts: list[SourceFinancialFact] = []
    schedules: list[DebtSchedule] = []
    periods: dict[str, ReportingPeriod] = {}
    seen_balance = False
    for page in pages:
        lines = rows(page)
        all_text = '\n'.join(' '.join(w.text for w in row) for row in lines).lower()
        debt_table = COMPLETENESS_QUOTE.lower() in all_text
        titles = [' '.join(w.text for w in row).lower().strip() for row in lines]
        statement_titles = [title for title in titles if re.fullmatch(
            r'(?:consolidated |company |group )?(?:balance sheet|statement of financial position)(?:\s+as at .*)?', title)]
        if not statement_titles and not debt_table:
            continue
        seen_balance = True
        # Scope belongs to the statement heading, not an arbitrary mention in
        # contents, auditors' prose or subsequent notes. Preserve group source
        # facts but never map them as the selected company's standalone figures.
        group_scope = any(title.startswith(('consolidated ', 'group ')) for title in statement_titles)
        dimensions = (('pdf:entity-scope', 'GROUP'),) if group_scope else ()
        date_match = re.search(r'\b(?:as at|at)\s+([0-3]?[0-9])\s+(' + '|'.join(MONTHS) + r')\s+(20[0-9]{2})\b', all_text)
        if date_match is None or not ('£' in all_text or 'gbp' in all_text):
            # Contents/narrative pages can mention a balance sheet without being
            # the statement. They supply no admitted facts or disclosure completeness.
            continue
        if any(currency in all_text for currency in ('usd', 'eur', '$', '€')):
            raise ParseError('Ambiguous PDF currency')
        scale = 3 if re.search(r"(?:£|gbp)\s*(?:'|’)?000", all_text) else 0
        day, month = int(date_match[1]), MONTHS.index(date_match[2]) + 1
        headers = [row for row in lines if len([w for w in row if re.fullmatch(r'20[0-9]{2}', w.text)]) >= 2]
        if len(headers) != 1:
            continue
        columns = [w for w in headers[0] if re.fullmatch(r'20[0-9]{2}', w.text)]
        if len(columns) != 2 or len({w.text for w in columns}) != 2:
            raise ParseError('Unsupported PDF financial column structure')
        latest = max(int(w.text) for w in columns)
        # Accounting statements can print detail and subtotal amounts in two
        # positions within each year. Use disjoint year bands, never nearest
        # number matching; two amounts in one band remain ambiguous.
        spacing = columns[1].right - columns[0].right
        if spacing <= 72:
            raise ParseError('Overlapping PDF year columns')
        bands = [(column.right - spacing * 0.75, column.right + 18) for column in columns]
        def aligned_values(line: tuple[Word, ...]) -> list[list[Word]]:
            return [[word for word in line if left < word.right <= right
                     and re.fullmatch(r'\(?-?[0-9,]+(?:\.[0-9]+)?\)?', word.text)]
                    for left, right in bands]
        for row_index, row in enumerate(lines):
            if row[0].y <= headers[0][0].y:
                continue
            label_words = [w.text for w in row if w.right <= bands[0][0]]
            label = ' '.join(label_words).lower().strip()
            # A separately positioned note reference may follow the financial label.
            label = re.sub(r'\s+[0-9]{1,2}$', '', label)
            if label not in LABELS and not (debt_table and label in COMPONENT_LABELS):
                continue
            values_by_column = aligned_values(row)
            if all(not items for items in values_by_column) and label == 'current assets':
                subtotals = []
                for following in lines[row_index + 1:]:
                    text = ' '.join(w.text for w in following).lower()
                    if text.startswith(('creditors', 'current liabilities', 'net current', 'total assets', 'net assets', 'fixed assets')):
                        break
                    if len(following) == len(columns) and all(re.fullmatch(r'\(?-?[0-9,]+(?:\.[0-9]+)?\)?', w.text) for w in following):
                        aligned = aligned_values(following)
                        if all(len(items) == 1 for items in aligned):
                            subtotals.append(aligned)
                # A unique printed subtotal within the labelled section is a
                # direct source amount, not a sum of arbitrarily chosen components.
                if len(subtotals) == 1:
                    values_by_column = subtotals[0]
            if not all(len(items) == 1 for items in values_by_column):
                continue  # Retain other supported rows; document remains PARTIAL.
            for column, values in zip(columns, values_by_column, strict=True):
                raw = values[0].text
                value = amount(raw, scale)
                if label in ('creditors: amounts falling due within one year',
                             'creditors: amounts falling due within 1 year', 'current liabilities') and raw.startswith('('):
                    value = value.copy_abs()
                if label == 'net liabilities' and value > 0:
                    value = value.copy_negate()
                period = ReportingPeriod(period_type=PeriodType.INSTANT,
                    period_end=date(int(column.text), month, day), comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
                periods[period.model_dump_json()] = period
                identity = sha256(f'{document_id}:{PARSER_VERSION}:{page.page}:{row[0].y}:{column.text}'.encode()).hexdigest()
                facts.append(SourceFinancialFact(source_fact_id=identity, document_id=document_id,
                    evidence_id='e-' + identity, source_concept='pdf-label:' + label, source_label=label,
                    raw_value=raw, value=value, availability_status=AvailabilityStatus.AVAILABLE,
                    currency='GBP', unit='GBP', context_ref=f'page-{page.page}:{column.text}',
                    entity_identifier=company_number, entity_scheme='M2_DOCUMENT_LINEAGE', period=period,
                    dimensions=dimensions,
                    period_role='CURRENT' if int(column.text) == latest else 'COMPARATIVE',
                    scale=scale, sign='-' if value < 0 else '+', extraction_method=page.method,
                    parser_version=PARSER_VERSION, page=page.page,
                    statement_context=statement_context(page, headers[0][0].y)))
        if debt_table:
            for column in columns:
                components = tuple(f.source_fact_id for f in facts if f.page == page.page
                    and f.source_label in COMPONENT_LABELS and f.period.period_end.year == int(column.text))
                # Unrecognized numeric rows mean the schedule may contain another component.
                numeric_rows = [row for row in lines if row[0].y > headers[0][0].y
                    and any(re.fullmatch(r'\(?[0-9,]+\)?', w.text) for w in row)]
                if components and len(numeric_rows) == len(components):
                    schedules.append(DebtSchedule(source_fact_ids=components,
                        completeness_quote=COMPLETENESS_QUOTE, page=page.page))
    if not seen_balance or not facts:
        raise ParseError('No supported balance-sheet table')
    # A parsed table is not proof that all notes were adequately searched for debt.
    return ExtractionResult(facts=tuple(facts), periods=tuple(periods.values()), complete=False, debt_schedules=tuple(schedules),
                            reason='Balance-sheet rows extracted; disclosure completeness requires notes coverage')


def pdf_document_kind(content: bytes) -> str:
    """Classify the filed PDF before extraction: NATIVE_TEXT, SCANNED, or MIXED."""
    import pymupdf
    if not content.startswith(b'%PDF-'):
        raise ParseError('Unsupported PDF content')
    try:
        with pymupdf.open(stream=content, filetype='pdf') as document:
            kinds=[]
            for page in document:
                words=page.get_text('words')
                image_coverage=sum(abs(rect.width*rect.height) for image in page.get_images()
                    for rect in page.get_image_rects(image[0]))/max(1,page.rect.width*page.rect.height)
                kinds.append('SCANNED' if len(words)<15 or image_coverage>0.6 else 'NATIVE_TEXT')
            if kinds and all(k=='SCANNED' for k in kinds): return 'SCANNED'
            if any(k=='SCANNED' for k in kinds): return 'MIXED'
            return 'NATIVE_TEXT'
    except ParseError: raise
    except Exception:
        raise ParseError('PDF type detection failed') from None

def render_pdf_pages(content: bytes, page_numbers: tuple[int, ...], dpi: int = 130) -> tuple[tuple[int, bytes], ...]:
    """Render bounded filed pages for multimodal extraction."""
    import pymupdf
    try:
        with pymupdf.open(stream=content, filetype='pdf') as document:
            out=[]
            matrix=pymupdf.Matrix(dpi/72, dpi/72)
            for page_no in page_numbers[:30]:
                if 1 <= page_no <= len(document):
                    out.append((page_no, document[page_no-1].get_pixmap(matrix=matrix, alpha=False).tobytes('png')))
            return tuple(out)
    except Exception:
        raise ParseError('PDF page rendering failed') from None
