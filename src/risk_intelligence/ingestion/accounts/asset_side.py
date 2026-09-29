"""Locate complete asset structures and contextual source rows in verified layout."""

from decimal import Decimal, localcontext
from hashlib import sha256
import re

from risk_intelligence.domain.enums import AvailabilityStatus
from risk_intelligence.ingestion.companies_house.client import ParseError
from .derivation import derive_debt
from .fallback import _columns, page_lines
from .models import CompletenessProof, ExtractionResult, FinancialContext, SourceFinancialFact
from .pdf import PageText, Word, amount, rows

PARSER_VERSION = 'financial-statement-structure-v3'
FIXED_LABELS = {'intangible assets', 'intangible fixed assets', 'tangible assets',
                'tangible fixed assets', 'investments', 'other fixed assets'}
CURRENT_CHILDREN = {'stocks', 'inventory', 'inventories', 'debtors',
    'debtors: amounts falling due within one year', 'cash at bank and in hand',
    'cash at bank', 'cash and cash equivalents'}


def _label(row: tuple[Word, ...], boundary: float) -> str:
    text = ' '.join(w.text for w in row if w.right <= boundary).strip()
    return re.sub(r'\s+[0-9]{1,2}$', '', text)


def _value(row: tuple[Word, ...], left: float, right: float, scale: int) -> tuple[str, Decimal]:
    tokens = [w.text for w in row if left < w.right <= right]
    if len(tokens) != 1:
        raise ParseError('Amount is not uniquely aligned')
    return tokens[0], amount(tokens[0], scale)


def _source(anchor: SourceFinancialFact, page: PageText, index: int, label: str,
            row: tuple[Word, ...], band: tuple[float, float], concept: str) -> SourceFinancialFact:
    raw, value = _value(row, *band, anchor.scale)
    identity = sha256(f'{anchor.document_id}:{PARSER_VERSION}:{page.page}:{index}:{anchor.period.period_end}:{concept}'.encode()).hexdigest()
    return SourceFinancialFact(**(anchor.model_dump() | {
        'source_fact_id':identity, 'evidence_id':'e-'+identity,
        'source_concept':'structure:'+concept, 'source_label':label,
        'raw_value':raw, 'value':value, 'sign':'-' if value < 0 else '+',
        'context_ref':f'page-{page.page}:row-{index+1}:{anchor.period.period_end}',
        'parser_version':PARSER_VERSION, 'extraction_method':page.method, 'page':page.page}))


def inspect_asset_side(pages: tuple[PageText, ...], result: ExtractionResult) -> ExtractionResult:
    """Retain source components and certify complete subtotal or component structures.

    A printed fixed subtotal need not contain a universal list of child categories.
    Without that subtotal every displayed fixed component must be resolved. The
    Company asset-side boundary and a supported current-assets total are required.
    A reported assets-less-current-liabilities amount is a cross-check, never assets.
    """
    facts = {fact.source_fact_id:fact for fact in result.facts}
    proofs: list[CompletenessProof] = []
    notes: list[str] = []
    contexts: list[FinancialContext] = []
    for fact in result.facts:
        page = next((p for p in pages if p.page == fact.page), None)
        if page is None:
            continue
        text = page_lines(page)
        statement = next((line for line in text if line.lower().strip() in
            ('company balance sheet', 'company statement of financial position',
             'consolidated balance sheet', 'group balance sheet')), 'Financial note')
        contexts.append(FinancialContext(source_fact_id=fact.source_fact_id,
            statement=statement, section=fact.source_label or fact.source_concept,
            supporting_text=f'Persisted page {page.page}; {fact.context_ref}; {fact.source_label or fact.source_concept}'))
    for page in pages:
        text = page_lines(page)
        if not any(line.lower().strip() in ('company balance sheet', 'company statement of financial position') for line in text):
            continue
        table = rows(page)
        fixed = [i for i,line in enumerate(text) if line.lower().strip() in ('fixed assets','non-current assets')]
        current = [i for i,line in enumerate(text) if line.lower().strip() == 'current assets']
        if len(fixed) != 1 or len(current) != 1 or fixed[0] >= current[0]:
            continue
        start, split = fixed[0], current[0]
        try:
            header, columns, scopes = _columns(table, start)
        except ParseError:
            continue
        if len(columns) != 2 or scopes != ['COMPANY','COMPANY']:
            continue
        spacing = columns[1].right - columns[0].right
        if spacing <= 72:
            continue
        bands = [(column.right-spacing*.75, column.right+18) for column in columns]
        labels = [_label(row, bands[0][0]) for row in table]
        normalized = [label.lower() for label in labels]
        end = next((i for i in range(split+1,len(table)) if normalized[i].startswith(
            ('creditors:', 'current liabilities'))), None)
        if end is None:
            continue
        component_rows = [i for i in range(start+1,split) if normalized[i] in FIXED_LABELS]
        subtotal_rows = [i for i in range(start+1,split) if not labels[i]]
        unknown = [i for i in range(start+1,split) if labels[i] and normalized[i] not in FIXED_LABELS]
        unknown += [i for i in range(split+1,end) if labels[i] and normalized[i] not in CURRENT_CHILDREN]
        # A section before Fixed assets may be another asset population. Do not
        # silently omit it while declaring the selected sections exhaustive.
        unknown_prefix = [i for i in range(header+1,start) if normalized[i] not in
                          ('', 'note', 'notes', 'gbp', '£')]
        unique_components = len({normalized[i] for i in component_rows}) == len(component_rows)
        subtotal_follows = not subtotal_rows or (component_rows and subtotal_rows[0] > max(component_rows))
        structure_complete = (not unknown and not unknown_prefix and bool(component_rows)
                              and unique_components and len(subtotal_rows) <= 1 and subtotal_follows)
        check_rows = []
        for i,label in enumerate(normalized):
            if label == 'total assets less current liabilities':
                check_rows.append((i,i))
            elif label == 'total assets less current' and i+1 < len(labels) and normalized[i+1] == 'liabilities':
                check_rows.append((i,i+1))
        for column,band in zip(columns,bands,strict=True):
            anchors = [fact for fact in result.facts if fact.page == page.page and not fact.dimensions
                and fact.period.period_end.year == int(column.text) and fact.source_concept in
                ('pdf-label:current assets','pdf-label:total current assets')
                and fact.availability_status == AvailabilityStatus.AVAILABLE]
            if len(anchors) != 1:
                continue
            anchor = anchors[0]
            components = []
            for index in component_rows:
                try:
                    fact = _source(anchor,page,index,labels[index],table[index],band,'fixed-component')
                except ParseError:
                    continue
                facts[fact.source_fact_id] = fact
                components.append(fact)
            fixed_total = None
            if len(subtotal_rows) == 1:
                index = subtotal_rows[0]
                try:
                    fixed_total = _source(anchor,page,index,labels[start],table[index],band,'fixed-subtotal')
                    facts[fixed_total.source_fact_id] = fixed_total
                except ParseError:
                    pass
            selected = ([fixed_total] if fixed_total is not None else components)
            complete = structure_complete and (fixed_total is not None or
                (not subtotal_rows and len(components) == len(component_rows)))
            if fixed_total is not None and len(components) == len(component_rows):
                with localcontext() as context:
                    context.prec = max(50,sum(len(f.value.as_tuple().digits)+abs(f.value.as_tuple().exponent) for f in components)+10)
                    if sum((f.value for f in components),Decimal(0)) != fixed_total.value:
                        complete = False
            cross_ids = ()
            if check_rows:
                liabilities = [fact for fact in result.facts if fact.page == page.page and not fact.dimensions
                    and fact.period == anchor.period and fact.source_concept in
                    ('pdf-label:current liabilities','pdf-label:creditors: amounts falling due within one year',
                     'pdf-label:creditors: amounts falling due within 1 year')
                    and fact.availability_status == AvailabilityStatus.AVAILABLE]
                reported = None
                if len(check_rows) == 1:
                    first,last = check_rows[0]
                    for index in range(first,last+1):
                        try:
                            reported = _source(anchor,page,index,' '.join(labels[first:last+1]),table[index],band,'assets-less-current-liabilities')
                        except ParseError:
                            continue
                        facts[reported.source_fact_id] = reported
                if reported is None or len(liabilities) != 1:
                    complete = False
                else:
                    cross_ids = (liabilities[0].source_fact_id,reported.source_fact_id)
            if not complete:
                notes.append(f'Asset side page {page.page}, period {anchor.period.period_end}: FAIL; incomplete structure, unresolved subtotal/component or cross-check')
                continue
            ids = tuple(f.source_fact_id for f in selected) + (anchor.source_fact_id,)
            proof_id = 'proof-'+sha256((PARSER_VERSION+':'.join(ids+cross_ids)).encode()).hexdigest()
            proofs.append(CompletenessProof(proof_id=proof_id,target='TOTAL_ASSETS',source_fact_ids=ids,
                document_id=anchor.document_id,page=page.page,row_start=start+1,row_end=end+1,
                evidence_text='\n'.join(text[start:end+1]),relationship='ASSET_SIDE',cross_check_ids=cross_ids))
            notes.append(f'Asset side page {page.page}, period {anchor.period.period_end}: complete supported structure; arithmetic/cross-check admission pending')
    # Existing exhaustive schedules supply a second, separate accounting proof.
    for schedule in result.debt_schedules:
        try:
            derive_debt(schedule,result.facts,company_id='check',source_id='check',run_id='check',mapping_version='check')
        except ParseError:
            continue
        first = facts[schedule.source_fact_ids[0]]
        page = next((p for p in pages if p.page == schedule.page),None)
        if page is None or schedule.completeness_quote not in '\n'.join(page_lines(page)):
            continue
        proof_id = 'proof-'+sha256((PARSER_VERSION+':'.join(schedule.source_fact_ids)).encode()).hexdigest()
        proofs.append(CompletenessProof(proof_id=proof_id,target='INTEREST_BEARING_DEBT',
            source_fact_ids=schedule.source_fact_ids,document_id=first.document_id,page=page.page,
            row_start=1,row_end=len(page_lines(page)),evidence_text='\n'.join(page_lines(page)),
            relationship='EXHAUSTIVE_INTEREST_BEARING'))
    inspected = result.model_copy(update={'facts':tuple(facts.values()),'asset_schedules':(),
        'proofs':tuple(proofs),'contexts':tuple(contexts),'completeness_notes':tuple(notes)})
    return inspect_debt_population(pages, inspect_context_rows(pages,inspected))


def inspect_context_rows(pages: tuple[PageText, ...], result: ExtractionResult) -> ExtractionResult:
    """Locate contextual alternative terminology without forcing a canonical mapping.

    A qualified maturity row beneath Creditors supports current liabilities. A
    terminal Total beneath an explicit canonical section can support semantic
    normalization. A generic Creditors row alone never qualifies.
    """
    facts = {f.source_fact_id:f for f in result.facts}
    contexts = list(result.contexts)
    sections = {'current assets':'CURRENT_ASSETS','current liabilities':'CURRENT_LIABILITIES',
                'inventories':'INVENTORY','net assets':'NET_ASSETS','total assets':'TOTAL_ASSETS',
                'total interest-bearing debt':'INTEREST_BEARING_DEBT'}
    for page in pages:
        table = rows(page)
        text = page_lines(page)
        if not any(t.lower() == 'company balance sheet' for t in text):
            continue
        anchors = [f for f in result.facts if f.page == page.page and not f.dimensions
                   and f.availability_status == AvailabilityStatus.AVAILABLE]
        for index in range(len(table)):
            try:
                _,columns,scopes = _columns(table,index)
            except ParseError:
                continue
            if len(columns) != 2 or scopes != ['COMPANY','COMPANY']:
                continue
            spacing = columns[1].right-columns[0].right
            if spacing <= 72:
                continue
            bands = [(c.right-spacing*.75,c.right+18) for c in columns]
            labels = [_label(row,bands[0][0]) for row in table]
            label = labels[index].lower()
            preceding = labels[index-1].lower() if index else ''
            target = None
            section = labels[index-1] if index else ''
            if label == 'amounts falling due within one year' and preceding == 'creditors':
                target = 'CURRENT_LIABILITIES'
            elif label in ('total','aggregate','carrying amount'):
                # Only a directly preceding explicit section is currently supported;
                # arbitrary neighboring numbers do not establish a subtotal.
                target = sections.get(preceding)
            if target is None:
                continue
            for column,band in zip(columns,bands,strict=True):
                matching = [a for a in anchors if a.period.period_end.year == int(column.text)]
                if not matching or len({a.period.model_dump_json() for a in matching}) != 1:
                    continue
                try:
                    fact = _source(matching[0],page,index,labels[index],table[index],band,'context-row')
                except ParseError:
                    continue
                facts[fact.source_fact_id] = fact
                contexts.append(FinancialContext(source_fact_id=fact.source_fact_id,statement='Company balance sheet',
                    section=section,supporting_text='\n'.join(text[max(0,index-1):index+1]),compatible_concepts=(target,)))
    return result.model_copy(update={'facts':tuple(facts.values()),'contexts':tuple(contexts)})


def inspect_debt_population(pages: tuple[PageText, ...], result: ExtractionResult) -> ExtractionResult:
    """Recognize explicit exhaustive Company borrowing schedules of varying size.

    The source heading establishes interest-bearing scope and completeness; a model
    cannot create that assertion. Every following row must have one amount per
    period. Subtotals, ordinary creditors and unknown intervening prose fail closed.
    """
    facts = {f.source_fact_id:f for f in result.facts}
    proofs = list(result.proofs)
    headings = ('interest-bearing debt comprises only:', 'total interest-bearing debt consists of:')
    for page in pages:
        table = rows(page)
        text = page_lines(page)
        starts = [i for i,line in enumerate(text) if line.lower() in headings]
        if len(starts) != 1:
            continue
        start = starts[0]
        try:
            header,columns,scopes = _columns(table,len(table))
        except ParseError:
            continue
        if len(columns) != 2 or scopes != ['COMPANY','COMPANY'] or start > header:
            continue
        spacing = columns[1].right-columns[0].right
        if spacing <= 72:
            continue
        bands = [(c.right-spacing*.75,c.right+18) for c in columns]
        indices = list(range(header+1,len(table)))
        labels = [_label(row,bands[0][0]) for row in table]
        forbidden = r'trade|tax|accrual|payable|creditors|security|charge|^total|^net |subtotal'
        if not indices or any(not labels[i] or re.search(forbidden,labels[i],re.I) for i in indices):
            continue
        if len({labels[i].lower() for i in indices}) != len(indices):
            continue
        for column,band in zip(columns,bands,strict=True):
            anchors = [f for f in result.facts if not f.dimensions and f.period.period_end.year == int(column.text)
                       and f.availability_status == AvailabilityStatus.AVAILABLE]
            if not anchors or len({(a.document_id,a.period.model_dump_json(),a.currency,a.unit,a.scale) for a in anchors}) != 1:
                continue
            anchor = anchors[0]
            # Scope and unit must be explicit on the schedule, not inferred from a
            # nearby note or the mere presence of the same year elsewhere.
            joined = ' '.join(text).lower()
            if not ('gbp' in joined or '£' in joined) or any(c in joined for c in ('usd','eur','$','€')):
                continue
            scaled = bool(re.search(r"(?:£|gbp)\s*(?:'|’)?000",joined))
            if anchor.scale != (3 if scaled else 0):
                continue
            components = []
            for index in indices:
                try:
                    fact = _source(anchor,page,index,labels[index],table[index],band,'interest-bearing-component')
                except ParseError:
                    continue
                facts[fact.source_fact_id] = fact
                components.append(fact)
            if len(components) != len(indices):
                continue
            ids = tuple(f.source_fact_id for f in components)
            # Prefer this population-aware proof over the historical fixed-label one.
            proofs = [p for p in proofs if not (p.target == 'INTEREST_BEARING_DEBT' and p.page == page.page
                and facts[p.source_fact_ids[0]].period == anchor.period)]
            proof_id = 'proof-'+sha256((PARSER_VERSION+':'.join(ids)).encode()).hexdigest()
            proofs.append(CompletenessProof(proof_id=proof_id,target='INTEREST_BEARING_DEBT',source_fact_ids=ids,
                document_id=anchor.document_id,page=page.page,row_start=start+1,row_end=len(table),
                evidence_text='\n'.join(text[start:]),relationship='EXHAUSTIVE_INTEREST_BEARING'))
    return result.model_copy(update={'facts':tuple(facts.values()),'proofs':tuple(proofs)})


def debt_completeness_notes(pages: tuple[PageText, ...], result: ExtractionResult) -> tuple[str, ...]:
    """Record examined categories; keyword absence never establishes absent debt.

    Only the existing source-supported exhaustive schedule gate can authorize a
    sum. A reconciliation heading or a collection of creditors is insufficient.
    """
    patterns = {
        'bank loans':r'bank loans', 'overdrafts':r'overdraft',
        'invoice financing/factoring':r'invoice discount|factoring', 'other loans':r'other loans',
        'lease liabilities/finance leases':r'lease liabilit|finance lease', 'hire purchase':r'hire purchase',
        'director/shareholder loans':r'(?:director|shareholder).{0,35}loan',
        'other borrowings/financing':r'borrowings|financing liabilit',
        'net-debt reconciliation':r'net debt|net funds', 'creditors notes':r'creditors:',
        'interest terms':r'interest.*(?:rate|charged)|(?:rate|charged).*interest',
    }
    admitted = any(proof.target == 'INTEREST_BEARING_DEBT' for proof in result.proofs)
    for schedule in result.debt_schedules:
        try:
            derive_debt(schedule, result.facts, company_id='coverage', source_id='coverage',
                        run_id='coverage', mapping_version='coverage')
        except ParseError:
            continue
        admitted = True
    notes = [f'Debt completeness evidence ({PARSER_VERSION}): '+('Exhaustive source schedule located; final plan admission recorded separately'
              if admitted else 'FAIL; no admitted exhaustive Company interest-bearing population')]
    for category,pattern in patterns.items():
        matched = [page.page for page in pages if re.search(pattern,' '.join(page_lines(page)),re.I)]
        notes.append(category+': '+('evidence pages '+','.join(map(str,matched)) if matched else
                     'not established in supported OCR; absence is not proven'))
    if not admitted:
        notes.append('Missing completeness evidence: explicit Company/period population coverage and supported inclusion or exclusion of all interest-bearing categories; isolated financing rows and a net-debt heading do not establish this.')
    return tuple(notes)
