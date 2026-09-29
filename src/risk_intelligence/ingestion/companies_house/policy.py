"""Explicit resource freshness and frozen calendar horizon, independent of I/O."""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum


class Resource(StrEnum):
    """Independent retrieval populations; empty PSC never replaces statements."""

    PROFILE = "profile"
    OFFICERS = "officers"
    PSC = "persons-with-significant-control"
    STATEMENTS = "persons-with-significant-control-statements"
    FILINGS = "filing-history"


def horizon_start(assessment_date: date) -> date:
    """Subtract 36 calendar months, clamping leap day to the target month's end."""
    year = assessment_date.year - 3
    return date(year, assessment_date.month,
                min(assessment_date.day, monthrange(year, assessment_date.month)[1]))


@dataclass(frozen=True)
class FreshnessPolicy:
    """Caller-configurable maximum age per resource; zero explicitly forces refresh."""

    max_age: dict[Resource, timedelta] = field(default_factory=lambda: {
        resource: timedelta(hours=24) for resource in Resource})
    page_size: int = 100
    max_pages: int = 1000

    def __post_init__(self) -> None:
        if set(self.max_age) != set(Resource) or any(v < timedelta(0) for v in self.max_age.values()):
            raise ValueError("Freshness must specify each resource with nonnegative age")
        if not 1 <= self.page_size <= 100 or not 1 <= self.max_pages <= 10000:
            raise ValueError("Invalid bounded pagination policy")
