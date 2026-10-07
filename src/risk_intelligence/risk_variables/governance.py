"""Date-bounded governance leaves over exact persisted validated populations."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.domain.facts import StructuredFact
from risk_intelligence.persistence.validated_members import ValidatedMembers
from risk_intelligence.validation.obligations import ValidatedObligation
from .core import Calculation, DECIMAL_CONTEXT, Reason, TraceStep, ValidatedInput, unavailable


def months_before(day: date, months: int) -> date:
    """Subtract calendar months, clamping only nonexistent month-end days."""
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def set_input(members: ValidatedMembers) -> ValidatedInput:
    """Retain set-level reliability as supplied by M4."""
    record = members.validated
    return ValidatedInput(kind="SET", validated_id=record.validated_evidence_set_id,
                          reliability_r=record.reliability_r, validation_version=record.validation_ruleset_version,
                          reliability_version=record.reliability_policy_version)


def obligation_input(record: ValidatedObligation, *, mandatory: bool = True) -> ValidatedInput:
    """Expose the obligation's own validation provenance, not unvalidated profile fields."""
    return ValidatedInput(kind="OBLIGATION", validated_id=record.validated_obligation_id, mandatory=mandatory,
                          reliability_r=record.assessment.calculation.reliability_r,
                          validation_version=record.assessment.validation.ruleset_version,
                          reliability_version=record.assessment.calculation.policy_version)


def calculate_lateness(kind: str, obligations: tuple[ValidatedObligation, ...], *,
                       company_id: str, company_number: str, assessment_date: date) -> Calculation:
    """Select the latest observed obligation; future reporting periods are eligible."""
    candidates = sorted((o for o in obligations if o.company_id == company_id and o.company_number == company_number
                         and o.obligation_kind == kind and o.assessment_date == assessment_date
                         and o.snapshot_observed_at.date() <= assessment_date),
                        key=lambda o: (o.snapshot_observed_at, o.validated_obligation_id))
    if not candidates:
        return unavailable(Reason.MISSING_INPUT, availability=AvailabilityStatus.NOT_DISCLOSED)
    latest = [o for o in candidates if o.snapshot_observed_at == candidates[-1].snapshot_observed_at]
    inputs = tuple(obligation_input(o, mandatory=o in latest) for o in candidates)
    if len(latest) != 1:
        return unavailable(Reason.AMBIGUOUS_SELECTION, inputs)
    selected = latest[0]
    if (not selected.assessment.calculation.supported_analytical_evidence or selected.due_date is None
            or selected.filing_state == "UNRESOLVED"):
        return unavailable(Reason.UNRESOLVED_OBLIGATION, inputs)
    end = selected.filing_date if selected.filing_state == "FILED" else assessment_date
    if end is None or end > assessment_date:
        return unavailable(Reason.UNRESOLVED_OBLIGATION, inputs)
    value = Decimal(max(0, (end - selected.due_date).days))
    return Calculation(value=value, inputs=inputs, selected_dates=(selected.due_date, end), trace=(
        TraceStep(operation="obligation_selection", detail=f"observed={selected.snapshot_observed_at.isoformat()}; "
                  f"period={selected.obligation_period}; state={selected.filing_state}; due={selected.due_date}; "
                  f"filing={selected.filing_date}; assessment={assessment_date}"),
        TraceStep(operation="lateness", detail=f"max(0, {end} - {selected.due_date})={value} days"),
    ))


def _groups(facts: tuple[StructuredFact, ...]) -> dict[str, dict[str, StructuredFact]] | None:
    result: dict[str, dict[str, StructuredFact]] = {}
    for fact in facts:
        if fact.subject_identifier is None:
            return None
        subject = result.setdefault(fact.subject_identifier, {})
        if fact.canonical_concept in subject:
            return None
        subject[fact.canonical_concept] = fact
    return result


def _value(fields: dict[str, StructuredFact], concept: str) -> object:
    fact = fields.get(concept)
    return fact.value.value if fact and fact.availability_status == AvailabilityStatus.AVAILABLE else None


@dataclass(frozen=True)
class Director:
    """One explicit appointment interval attached to a stable director identity."""

    identity: str
    appointed: date
    resigned: date | None

    def active(self, day: date, *, before: bool = False) -> bool:
        """Evaluate inclusive appointment/exclusive resignation, or the instant before day."""
        return ((self.appointed < day if before else self.appointed <= day)
                and (self.resigned is None or (self.resigned >= day if before else self.resigned > day)))


def _directors(groups: dict[str, dict[str, StructuredFact]]) -> tuple[tuple[Director, ...], Reason | None]:
    directors: set[Director] = set()
    excluded_roles = {"secretary", "corporate-secretary", "llp-member", "corporate-llp-member",
                      "llp-designated-member", "corporate-llp-designated-member", "nominee-secretary"}
    for fields in groups.values():
        role = _value(fields, "OFFICERS_OFFICER_ROLE")
        if role in excluded_roles:
            continue
        if role not in ("director", "corporate-director"):
            return (), Reason.AMBIGUOUS_ROLE
        identity = _value(fields, "OFFICERS_LINKS_OFFICER_APPOINTMENTS")
        if not isinstance(identity, str):
            return (), Reason.AMBIGUOUS_IDENTITY
        appointed = _value(fields, "OFFICERS_APPOINTED_ON")
        if type(appointed) is not date:
            return (), Reason.MISSING_APPOINTMENT
        resignation = fields.get("OFFICERS_RESIGNED_ON")
        if resignation is None:
            return (), Reason.INCOMPLETE_POPULATION
        resigned = resignation.value.value
        if (resigned is None and resignation.availability_status != AvailabilityStatus.NOT_APPLICABLE
                or resigned is not None and type(resigned) is not date):
            return (), Reason.INCOMPLETE_POPULATION
        directors.add(Director(identity, appointed, resigned))
    return tuple(sorted(directors, key=lambda d: (d.identity, d.appointed, d.resigned or date.max))), None


def calculate_population(code: str, members: ValidatedMembers, *, assessment_date: date) -> Calculation:
    """Calculate from a complete M4 set; never turn unsupported event interpretation into zero."""
    record = members.validated
    inputs = (set_input(members),)
    months = 36 if code == "G3.1" else 24
    start, end = months_before(assessment_date, months), assessment_date + timedelta(days=1)
    expected = "PSC_EVENTS_36M" if code == "G3.1" else "OFFICER_EVENTS_24M"
    if (record.evidence_set_type != expected or record.assessment_date != assessment_date
            or record.analytical_window_start > start or record.analytical_window_end < assessment_date
            or not record.validation_report.admissible or record.availability_status != AvailabilityStatus.AVAILABLE):
        return unavailable(Reason.INCOMPLETE_POPULATION, inputs, dates=(start, end))
    groups = _groups(members.facts)
    if groups is None:
        return unavailable(Reason.AMBIGUOUS_SELECTION, inputs)
    if code == "G3.1":
        return _control_changes(groups, inputs, start, end)
    if code == "G2.2":
        # Tenure concerns active directors only. A definite past resignation
        # excludes the appointment even if its historic start date is unavailable.
        # Missing dates for potentially active directors still fail closed.
        groups = {identity: fields for identity, fields in groups.items()
                  if not (type(_value(fields, "OFFICERS_RESIGNED_ON")) is date
                          and _value(fields, "OFFICERS_RESIGNED_ON") <= assessment_date)}
    directors, failure = _directors(groups)
    if failure:
        return unavailable(failure, inputs)
    population_trace = (TraceStep(operation="director_population", detail="; ".join(
        f"{d.identity}: {d.appointed}/{d.resigned}" for d in directors) or "complete empty population"),)
    with localcontext(DECIMAL_CONTEXT):
        if code == "G2.2":
            active: dict[str, date] = {}
            for director in directors:
                if director.active(assessment_date):
                    if director.identity in active and active[director.identity] != director.appointed:
                        return unavailable(Reason.AMBIGUOUS_IDENTITY, inputs, trace=population_trace)
                    active[director.identity] = director.appointed
            if not active:
                return unavailable(Reason.EMPTY_POPULATION, inputs, trace=population_trace)
            values = sorted(Decimal((assessment_date - appointed).days) / Decimal("365.2425") for appointed in active.values())
            middle = len(values) // 2
            value = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
            return Calculation(value=value, inputs=inputs, selected_dates=(assessment_date,), trace=population_trace + (
                TraceStep(operation="median_tenure", detail=f"sorted years={values}; median={value}"),))
        if code == "G2.1":
            departing = {d.identity for d in directors if d.resigned is not None and start <= d.resigned < end}
            initial = {d.identity for d in directors if d.active(start, before=True)}
            if not initial:
                return unavailable(Reason.ZERO_DENOMINATOR, inputs, trace=population_trace, dates=(start, end))
            value = Decimal(len(departing)) / Decimal(len(initial))
            return Calculation(value=value, inputs=inputs, selected_dates=(start, end), trace=population_trace + (
                TraceStep(operation="departure_rate", detail=f"departures={sorted(departing)}; initial={sorted(initial)}; ratio={value}"),))
        if code != "G2.3":
            raise ValueError("Unsupported governance variable")
        departure_dates = {d.resigned for d in directors if d.resigned is not None and start <= d.resigned < end}
        starts = sorted({max(start, min(end - timedelta(days=90), candidate)) for day in departure_dates
                         for candidate in (day, day - timedelta(days=89))})
        computed: list[tuple[Decimal, date]] = []
        trace = list(population_trace)
        for window in starts:
            stop = window + timedelta(days=90)
            initial = {d.identity for d in directors if d.active(window, before=True)}
            departing = {d.identity for d in directors if d.resigned is not None and window <= d.resigned < stop}
            trace.append(TraceStep(operation="candidate_window", detail=f"[{window},{stop}); initial={sorted(initial)}; departures={sorted(departing)}; "
                                   + ("computable" if initial else "excluded zero denominator")))
            if initial:
                computed.append((Decimal(len(departing)) / Decimal(len(initial)), window))
        if not computed:
            return unavailable(Reason.NO_COMPUTABLE_WINDOW, inputs, trace=tuple(trace), dates=(start, end))
        value, selected = sorted(computed, key=lambda item: (-item[0], item[1]))[0]
        trace.append(TraceStep(operation="maximum", detail=f"selected={selected}; ratio={value}"))
        return Calculation(value=value, inputs=inputs, selected_dates=(selected, selected + timedelta(days=90)), trace=tuple(trace))


def _control_changes(groups: dict[str, dict[str, StructuredFact]], inputs: tuple[ValidatedInput, ...],
                     start: date, end: date) -> Calculation:
    """Count only dated explicit cessations; notification alone is not an effective entry.

    The current source schema has no explicit effective-entry date or versioned
    before/after control relationship. In-window notifications and statements
    therefore remain Unknown, rather than a speculative substantive event count.
    """
    events: set[tuple[str, date, str]] = set()
    observed: dict[str, tuple[date, date | None]] = {}
    trace: list[TraceStep] = []
    for subject, fields in sorted(groups.items()):
        if any(key.startswith("STATEMENTS_") for key in fields):
            return unavailable(Reason.AMBIGUOUS_CONTROL, inputs)
        identity = _value(fields, "PSC_LINKS_SELF")
        notified = _value(fields, "PSC_NOTIFIED_ON")
        cessation = fields.get("PSC_CEASED_ON")
        if not isinstance(identity, str) or type(notified) is not date or cessation is None:
            return unavailable(Reason.AMBIGUOUS_CONTROL, inputs)
        if start <= notified < end:
            return unavailable(Reason.AMBIGUOUS_CONTROL, inputs, trace=(
                TraceStep(operation="unclassified_notification", detail=f"{subject}: {notified}; not an explicit effective entry"),))
        ceased = cessation.value.value
        if ceased is None and cessation.availability_status != AvailabilityStatus.NOT_APPLICABLE:
            return unavailable(Reason.AMBIGUOUS_CONTROL, inputs)
        if ceased is not None:
            if type(ceased) is not date:
                return unavailable(Reason.AMBIGUOUS_CONTROL, inputs)
            if start <= ceased < end:
                events.add((identity, ceased, "EXIT"))
        if identity in observed and observed[identity] != (notified, ceased):
            return unavailable(Reason.AMBIGUOUS_CONTROL, inputs)
        observed[identity] = (notified, ceased)
        trace.append(TraceStep(operation="control_member", detail=f"{subject}; identity={identity}; notified={notified}; ceased={ceased}"))
    trace.append(TraceStep(operation="substantive_changes", detail=f"deduplicated explicit exits={sorted(events)}; count={len(events)}"))
    return Calculation(value=Decimal(len(events)), inputs=inputs, selected_dates=(start, end), trace=tuple(trace))
