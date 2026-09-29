"""Evidence/context admission and deterministic execution of financial proposals."""

from decimal import Decimal, localcontext
from hashlib import sha256

from risk_intelligence.domain.enums import AvailabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import FinancialFact
from risk_intelligence.ingestion.companies_house.client import ParseError
from .mapping import FinancialMappingRegistry
from .models import (ExtractionResult, GroundedOperand, InterpretationDecision,
                     InterpretationProposal, SourceFinancialFact)

VERSION = 'financial-interpretation-v1'


def operand(fact: SourceFinancialFact) -> GroundedOperand:
    """Copy a supported source operand without inventing a label or amount."""
    if fact.value is None:
        raise ParseError('Unresolved operand')
    return GroundedOperand(source_fact_id=fact.source_fact_id,
        source_label=fact.source_label or fact.source_concept, value=fact.value,
        evidence_id=fact.evidence_id, page=fact.page)


def calculate(operands: tuple[GroundedOperand, ...]) -> Decimal:
    """Execute a bounded left-to-right expression using exact Decimal operations.

    Arithmetic is separate from accounting admission. No constants, names, code,
    functions or nested expressions are executable. Inexact division is rejected.
    """
    from decimal import Inexact
    if not 1 <= len(operands) <= 32 or operands[0].operation != 'ADD':
        raise ParseError('Invalid bounded expression')
    with localcontext() as context:
        context.prec = max(50, sum(len(o.value.as_tuple().digits) + abs(o.value.as_tuple().exponent)
                                  for o in operands) + 10)
        context.traps[Inexact] = True
        value = operands[0].value
        for item in operands[1:]:
            if item.operation == 'ADD':
                value += item.value
            elif item.operation == 'SUBTRACT':
                value -= item.value
            elif item.operation == 'MULTIPLY':
                value *= item.value
            elif item.operation == 'DIVIDE':
                if item.value == 0:
                    raise ParseError('Division by zero')
                try:
                    value /= item.value
                except Inexact:
                    raise ParseError('Inexact division is not admitted') from None
            else:
                raise ParseError('Unsupported arithmetic operation')
        return value


def verify(proposal: InterpretationProposal, result: ExtractionResult,
           registry: FinancialMappingRegistry) -> InterpretationDecision:
    """Recheck identity, values, context, relationship and independent completeness.

    Only trusted parser contexts/proofs can support model interpretations. The
    model cannot create a proof or turn a financially plausible sum into a total.
    """
    try:
        if proposal.version != VERSION or proposal.scope != 'COMPANY':
            raise ParseError('Unsupported version or Company/Group context')
        by_id = {fact.source_fact_id: fact for fact in result.facts}
        ids = tuple(item.source_fact_id for item in proposal.operands)
        if not ids or len(set(ids)) != len(ids):
            raise ParseError('Missing or duplicate operands')
        sources = []
        for item in proposal.operands:
            fact = by_id.get(item.source_fact_id)
            if fact is None or fact.value is None or fact.availability_status != AvailabilityStatus.AVAILABLE:
                raise ParseError('Operand is not an available source fact')
            if item.model_copy(update={'operation':'ADD'}) != operand(fact):
                raise ParseError('Operand value, label or evidence locator differs from source')
            if (fact.dimensions or fact.period.period_type != PeriodType.INSTANT
                    or fact.period.period_end != proposal.period_end
                    or fact.currency != proposal.currency or fact.unit != proposal.unit):
                raise ParseError('Operand scope, period or currency/unit mismatch')
            sources.append(fact)
        first = sources[0]
        if any(f.document_id != first.document_id or f.entity_identifier != first.entity_identifier
               or f.period != first.period for f in sources):
            raise ParseError('Mixed source context')
        if proposal.kind == 'NORMALIZATION':
            if len(sources) != 1 or proposal.operands[0].operation != 'ADD':
                raise ParseError('Normalization requires one unchanged value')
            mapped = registry.map(first, company_id='check', company_number=first.entity_identifier,
                                  source_id='check', processing_run_id='check')
            if mapped is not None:
                if mapped.canonical_concept != proposal.target:
                    raise ParseError('Contradictory approved mapping')
            else:
                contexts = [c for c in result.contexts if c.source_fact_id == first.source_fact_id]
                if len(contexts) != 1 or proposal.target not in contexts[0].compatible_concepts:
                    raise ParseError('Semantic equivalence lacks verified statement context')
            return InterpretationDecision(proposal=proposal, status='AVAILABLE',
                reason='Source identity, amount, scope, period, unit and semantic context verified',
                value=mapped.value_numeric if mapped is not None else first.value)
        proofs = [proof for proof in result.proofs if proof.proof_id == proposal.proof_id]
        if len(proofs) != 1:
            raise ParseError('Independent completeness evidence is absent')
        proof = proofs[0]
        expected_relationship = {'TOTAL_ASSETS':'ASSET_SIDE','INTEREST_BEARING_DEBT':'EXHAUSTIVE_INTEREST_BEARING'}
        if (proof.target != proposal.target or proof.document_id != first.document_id
                or proof.relationship != expected_relationship.get(proposal.target)
                or proof.source_fact_ids != ids or any(o.operation != 'ADD' for o in proposal.operands)
                or any(f.page != proof.page for f in sources)):
            raise ParseError('Unsupported relationship, incomplete population or subtotal double counting')
        value = calculate(proposal.operands)
        # A cross-check is mandatory when the statement exposes both operands.
        # It can reject a derivation; it can never substitute for completeness.
        if proof.cross_check_ids:
            if len(proof.cross_check_ids) != 2:
                raise ParseError('Invalid cross-check evidence')
            check = [by_id.get(identity) for identity in proof.cross_check_ids]
            if any(f is None or f.value is None or f.dimensions or f.document_id != first.document_id
                   or f.period != first.period or f.currency != first.currency or f.unit != first.unit
                   or f.availability_status != AvailabilityStatus.AVAILABLE for f in check):
                raise ParseError('Unresolved or mixed cross-check context')
            liability, reported = check
            computed = calculate((GroundedOperand(source_fact_id='result', source_label='derived total',
                value=value, evidence_id=proof.proof_id, page=proof.page),
                operand(liability).model_copy(update={'operation':'SUBTRACT'})))
            if computed != reported.value:
                raise ParseError('Contradictory reported cross-check')
        return InterpretationDecision(proposal=proposal, status='AVAILABLE',
            reason='Grounded operands, complete non-overlapping population and available cross-checks verified', value=value)
    except ParseError as error:
        return InterpretationDecision(proposal=proposal, status='VALIDATION_FAILED', reason=str(error))


def deterministic_proposals(result: ExtractionResult, registry: FinancialMappingRegistry) -> tuple[InterpretationDecision, ...]:
    """Use approved direct mappings first, then supported complete relationships."""
    decisions = []
    for fact in result.facts:
        mapped = registry.map(fact, company_id='check', company_number=fact.entity_identifier,
                              source_id='check', processing_run_id='check')
        if mapped is None or fact.value is None or fact.dimensions:
            continue
        proposal = InterpretationProposal(target=mapped.canonical_concept, kind='NORMALIZATION',
            method='DETERMINISTIC_MAPPING', scope='COMPANY', period_end=fact.period.period_end,
            currency=fact.currency, unit=fact.unit, operands=(operand(fact),),
            rationale='Approved versioned source/context registry mapping', version=VERSION)
        decisions.append(verify(proposal, result, registry))
    direct = {(d.proposal.target, d.proposal.period_end) for d in decisions if d.status == 'AVAILABLE'}
    by_id = {fact.source_fact_id:fact for fact in result.facts}
    for proof in result.proofs:
        facts = [by_id[identity] for identity in proof.source_fact_ids]
        first = facts[0]
        proposal = InterpretationProposal(target=proof.target, kind='DERIVATION', method='DETERMINISTIC_DERIVATION',
            scope='COMPANY', period_end=first.period.period_end, currency=first.currency, unit=first.unit,
            operands=tuple(operand(f) for f in facts), proof_id=proof.proof_id,
            rationale='Complete source statement hierarchy; use disclosed subtotals or exhaustive components', version=VERSION)
        if (proof.target, first.period.period_end) in direct:
            decisions.append(InterpretationDecision(proposal=proposal, status='SUPERSEDED', reason='Supported direct disclosure takes priority'))
        else:
            decisions.append(verify(proposal, result, registry))
    return tuple(decisions)


def canonical(decision: InterpretationDecision, result: ExtractionResult, *, company_id: str,
              source_id: str, run_id: str) -> FinancialFact:
    """Build an admitted observation retaining every operand and supporting proof."""
    if decision.status != 'AVAILABLE' or decision.value is None:
        raise ParseError('Rejected interpretation cannot become canonical')
    proposal = decision.proposal
    by_id = {fact.source_fact_id:fact for fact in result.facts}
    first = by_id[proposal.operands[0].source_fact_id]
    evidence = tuple(item.evidence_id for item in proposal.operands)
    if proposal.proof_id:
        proof = next(p for p in result.proofs if p.proof_id == proposal.proof_id)
        evidence += (proof.proof_id,) + tuple(by_id[i].evidence_id for i in proof.cross_check_ids)
    identity = sha256(decision.model_dump_json().encode()).hexdigest()
    return FinancialFact(financial_fact_id=identity, company_id=company_id, company_number=first.entity_identifier,
        canonical_concept=proposal.target, source_concept=first.source_concept if proposal.kind == 'NORMALIZATION' else 'evidence-grounded-expression',
        value_numeric=decision.value, currency=proposal.currency, unit=proposal.unit, period=first.period,
        source_id=source_id, document_id=first.document_id, evidence_ids=evidence,
        extraction_method=ExtractionMethod.DERIVED if proposal.kind == 'DERIVATION' else first.extraction_method,
        availability_status=AvailabilityStatus.AVAILABLE, processing_run_id=run_id)
