"""Route-independent monetary cleaning for semantic extraction; no label/format whitelist."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import re

from risk_intelligence.ingestion.companies_house.client import ParseError


def semantic_amount(raw: str | None, unit: str, currency: str) -> tuple[Decimal, int]:
    """Parse exact printed money with common display scales; preserve zero/negative signs.

    Unit wording such as 'pounds sterling', 'GBP units', '£000s' and 'thousands'
    is presentation metadata. It must not reject otherwise supported amounts.
    Explicit unsupported currencies remain unavailable rather than being relabelled.
    """
    if raw is None or not raw.strip():
        raise ParseError('The financial value was not identified')
    display = ' '.join((currency + ' ' + unit).split()).lower()
    if re.search(r'\b(?:usd|eur|dollars?|euros?)\b|[$€]', display):
        raise ParseError('The statement explicitly uses an unsupported currency')
    if re.search(r'\b(?:million|millions)\b|(?:gbp|£)\s*m\b', display):
        scale = 6
    elif re.search(r'\b(?:thousand|thousands)\b|(?:gbp|£)?[\s\'’]*000s?\b|(?:gbp|£)\s*k\b', display):
        scale = 3
    else:
        scale = 0
    token = raw.strip().replace('\u2212', '-').replace('\u00a0', '').replace(' ', '')
    token = re.sub(r'(?i)GBP|£', '', token).replace(',', '')
    if token in ('-', '—', '–'):
        # A dash is not automatically a source-disclosed zero.
        raise ParseError('The statement amount is a dash; zero was not established')
    negative = token.startswith('(') and token.endswith(')')
    if negative:
        token = token[1:-1]
    if not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?', token) or len(token) > 100:
        raise ParseError('The statement monetary token could not be parsed')
    try:
        value = Decimal(token)
    except InvalidOperation:
        raise ParseError('The statement monetary token could not be parsed') from None
    with localcontext() as context:
        context.prec = max(50, len(value.as_tuple().digits) + abs(scale) + 10)
        value = value * Decimal(10) ** scale
    return (-abs(value) if negative else value), scale


def semantic_period(displayed: str | int | None, preferred: int, filing_end: date | None) -> date:
    """Keep the displayed year/date; no exact requested-year rejection."""
    text = str(displayed or '')
    try:
        return date.fromisoformat(text)
    except ValueError:
        match = re.search(r'(?<![0-9])((?:19|20)[0-9]{2})(?![0-9])', text)
        year = int(match[1]) if match else (filing_end.year if filing_end else preferred)
    if filing_end is not None and filing_end.year == year:
        return filing_end
    return date(year, 12, 31)
