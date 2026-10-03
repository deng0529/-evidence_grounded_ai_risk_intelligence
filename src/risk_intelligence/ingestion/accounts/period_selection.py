"""Choose one filing statement period; the search year is a preference, not admission."""
from datetime import date

from risk_intelligence.domain.enums import PeriodType, ComparabilityStatus
from risk_intelligence.domain.facts import ReportingPeriod
from .models import ExtractionResult

VERSION = 'foundation-selected-statement-v30'


def closest_year(years: set[int], requested: int) -> int:
    """Prefer the closest displayed year; ties prefer the newer column."""
    return min(years, key=lambda year: (abs(year - requested), -year)) if years else requested


def select_period(result: ExtractionResult, requested: int, filing_end: date | None = None) -> ExtractionResult:
    """Retain one instant column from one document before canonical persistence.

    Different dates in the same year are different statements, never pooled into
    a numerical conflict. Original extraction artifacts retain all source contexts.
    Per-filing made-up metadata may select a same-year statement; company-wide
    profile dates must not be substituted for this document's period.
    """
    periods = {fact.period.period_end: fact.period for fact in result.facts
               if fact.period.period_type == PeriodType.INSTANT}
    if not periods:
        periods = {p.period_end: p for p in result.periods if p.period_type == PeriodType.INSTANT}
    if not periods:
        end = filing_end or date(requested, 12, 31)
        period = ReportingPeriod(period_type=PeriodType.INSTANT, period_end=end,
                                 comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
    else:
        year = closest_year({end.year for end in periods}, requested)
        dates = {end for end in periods if end.year == year}
        end = filing_end if filing_end in dates else max(dates)
        period = periods[end]
    selected = tuple(f for f in result.facts if f.period.period_type == PeriodType.INSTANT
                     and f.period.period_end == period.period_end)
    note = f'SELECTED_STATEMENT: requested={requested}; evidence={period.period_end.isoformat()}; policy={VERSION}'
    notes = tuple(n for n in result.completeness_notes if not n.startswith('SELECTED_STATEMENT:'))
    return result.model_copy(update={'facts': selected, 'periods': (period,),
        'reason': result.reason,
        'completeness_notes': (*notes, note)})
