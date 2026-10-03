"""Count distinct financial concepts by extraction route, never candidate rows."""
import json
from collections.abc import Iterable

from risk_intelligence.domain.enums import AvailabilityStatus
from .derivation import derive_balance_sheet_subtotals
from .mapping import FinancialMappingRegistry
from .models import ExtractionResult, SourceFinancialFact

TARGETS = ('NET_ASSETS', 'TOTAL_ASSETS', 'CURRENT_ASSETS', 'CURRENT_LIABILITIES', 'INVENTORY')
PREFIX = 'FINANCIAL_COVERAGE_V1:'


def resolved_concepts(facts: tuple[SourceFinancialFact, ...], registry: FinancialMappingRegistry,
                      number: str, source_id: str, run_id: str) -> frozenset[str]:
    """Count uniquely valued company concepts, including supported Python derivations."""
    values = {}
    for fact in facts:
        mapped = registry.map(fact, company_id='coverage', company_number=number,
                              source_id=source_id, processing_run_id=run_id)
        if mapped and mapped.availability_status == AvailabilityStatus.AVAILABLE:
            values.setdefault(mapped.canonical_concept, set()).add(mapped.value_numeric)
    for derived, _, _ in derive_balance_sheet_subtotals(facts, company_id='coverage',
            source_id=source_id, run_id=run_id, mapping_version=registry.version):
        values.setdefault(derived.canonical_concept, set()).add(derived.value_numeric)
    return frozenset(c for c in TARGETS if len(values.get(c, ())) == 1)


def with_coverage(result: ExtractionResult, *, route: str, before: Iterable[str],
                  requested: Iterable[str], after: Iterable[str]) -> ExtractionResult:
    """Retain counts/names in immutable artifacts and structured document read-back."""
    before, requested, after = set(before), set(requested), set(after)
    data = {'route': route, 'deterministic': sorted(before), 'openai_requested': sorted(requested),
            'openai_recovered': sorted((after - before) & requested),
            'final_identified': sorted(after), 'unknown': sorted(set(TARGETS) - after)}
    notes = tuple(n for n in result.completeness_notes if not n.startswith(PREFIX))
    return result.model_copy(update={'completeness_notes': (*notes, PREFIX + json.dumps(data, sort_keys=True))})


def coverage_note(result: ExtractionResult) -> str | None:
    """Return the single audit note for durable per-document storage."""
    return next((n for n in result.completeness_notes if n.startswith(PREFIX)), None)


def read_coverage(reason: str) -> dict[str, object] | None:
    """Read versioned counts from persisted run detail; older runs return no guess."""
    if PREFIX not in reason:
        return None
    try:
        value = json.loads(reason.split(PREFIX, 1)[1])
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get('route') not in ('iXBRL/XHTML', 'PDF/OpenAI'):
        return None
    for key in ('deterministic', 'openai_requested', 'openai_recovered', 'final_identified', 'unknown'):
        items = value.get(key)
        if not isinstance(items, list) or any(not isinstance(c, str) or c not in TARGETS for c in items):
            return None
    return value


def coverage_text(data: dict[str, object]) -> str:
    """Explain target counts separately from recovered counts and API call counts."""
    before = len(data['deterministic'])
    requested = len(data['openai_requested'])
    recovered = len(data['openai_recovered'])
    final = len(data['final_identified'])
    unknown = len(data['unknown'])
    first = (f'iXBRL resolved {before}/5 before OpenAI (including Python derivations)'
             if data['route'] == 'iXBRL/XHTML' else 'No iXBRL: complete PDF sent to OpenAI')
    return (f'{first}; OpenAI targets {requested}/5; OpenAI recovered {recovered}/{requested}; '
            f'final identified {final}/5; Unknown {unknown}/5')


def coverage_rows(documents: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Build display rows only from durable audit notes, never inferred method counts."""
    rows = []
    for document in documents:
        data = read_coverage(str(document.get('reason') or ''))
        if data is None:
            continue
        rows.append({'Route': data['route'],
            'Resolved before OpenAI': f"{len(data['deterministic'])}/5" if data['route']=='iXBRL/XHTML' else 'Not used (no iXBRL)',
            'Before OpenAI concepts': ', '.join(data['deterministic']) or '—',
            'OpenAI asked to examine': f"{len(data['openai_requested'])}/5",
            'OpenAI requested concepts': ', '.join(data['openai_requested']) or 'None',
            'OpenAI recovered': f"{len(data['openai_recovered'])}/{len(data['openai_requested'])}",
            'Recovered concepts': ', '.join(data['openai_recovered']) or 'None',
            'Final identified': f"{len(data['final_identified'])}/5",
            'Unknown concepts': ', '.join(data['unknown']) or 'None'})
    return rows
