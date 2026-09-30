"""Deterministic financial conflict classification for M4."""

from risk_intelligence.domain.enums import ConflictLevel, ConflictResolution
from risk_intelligence.domain.facts import FinancialFact
from risk_intelligence.domain.reliability import ConflictState


def classify_financial_conflict(
        selected: FinancialFact,
        competing: tuple[FinancialFact, ...],
) -> ConflictState:
    """Classify competing observations without inferring unsupported resolution.

    Compatibility differences are explanatory, not conflicts.  Material
    disagreement between observations representing the same analytical fact
    remains unresolved unless another evidence-grounded rule supplies an
    explicit resolution.
    """
    relevant = tuple(
        candidate for candidate in competing
        if candidate.financial_fact_id != selected.financial_fact_id
    )

    if not relevant:
        return ConflictState(
            level=ConflictLevel.NONE,
            resolution=ConflictResolution.NONE,
            reason="No competing financial observation",
        )

    same_identity = tuple(
        item for item in relevant
        if item.company_number == selected.company_number
        and item.company_id == selected.company_id
    )
    if not same_identity:
        return ConflictState(
            level=ConflictLevel.NONE,
            resolution=ConflictResolution.NONE,
            reason="Competing observations belong to a different entity",
        )

    same_scope_concept = tuple(
        item for item in same_identity
        if item.canonical_concept == selected.canonical_concept
    )
    if not same_scope_concept:
        return ConflictState(
            level=ConflictLevel.NONE,
            resolution=ConflictResolution.NONE,
            reason="Observations represent different canonical concepts",
        )

    same_period = tuple(
        item for item in same_scope_concept
        if item.period == selected.period
    )
    if not same_period:
        return ConflictState(
            level=ConflictLevel.NONE,
            resolution=ConflictResolution.PERIOD_DIFFERENCE,
            reason="Difference is explained by reporting-period incompatibility",
            evidence_ids=tuple(sorted({
                evidence
                for item in (selected,) + same_scope_concept
                for evidence in item.evidence_ids
            })),
        )

    same_unit = tuple(
        item for item in same_period
        if item.currency == selected.currency and item.unit == selected.unit
    )
    if not same_unit:
        return ConflictState(
            level=ConflictLevel.NONE,
            resolution=ConflictResolution.UNIT_DIFFERENCE,
            reason="Difference is explained by currency/unit incompatibility",
            evidence_ids=tuple(sorted({
                evidence
                for item in (selected,) + same_period
                for evidence in item.evidence_ids
            })),
        )

    available = tuple(
        item for item in same_unit
        if item.value_numeric is not None
    )
    disagreements = tuple(
        item for item in available
        if item.value_numeric != selected.value_numeric
    )

    if not disagreements:
        return ConflictState(
            level=ConflictLevel.NONE,
            resolution=ConflictResolution.NONE,
            reason="Compatible observations do not materially disagree",
        )

    evidence_ids = tuple(sorted({
        evidence
        for item in (selected,) + disagreements
        for evidence in item.evidence_ids
    }))

    return ConflictState(
        level=ConflictLevel.SERIOUS_UNRESOLVED,
        resolution=ConflictResolution.UNRESOLVED,
        reason=(
            "Compatible observations disagree materially; no explicit "
            "restatement, supersession, extraction-error or rounding evidence "
            "has been established"
        ),
        evidence_ids=evidence_ids,
    )
