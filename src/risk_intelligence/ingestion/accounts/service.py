"""Bounded accounts orchestration from M2 links to immutable financial observations."""

from datetime import UTC, date, datetime
from collections.abc import Callable
from hashlib import sha256
import json

from risk_intelligence.domain.enums import ProcessingStatus, TriggerType, AvailabilityStatus, PeriodType, ComparabilityStatus, ExtractionMethod
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.domain.evidence import EvidenceReference, IxbrlLocator, PdfLocator
from risk_intelligence.domain.evidence import RawEvidence
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.interfaces import EvidenceStorage
from risk_intelligence.persistence.accounts_repository import AccountsRepository
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.evidence_repositories import SqlEvidenceReferenceRepository
from risk_intelligence.persistence.mapping import encode
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.ingestion.companies_house.client import ParseError, RetrievalError, json_object
from .acquisition import AccountsPublication
from .client import DocumentClient, DocumentRetrievalError, representations
from .ixbrl import extract_ixbrl, PARSER_VERSION as IX_VERSION
from .mapping import FinancialMappingRegistry, default_registry
from .models import ExtractionResult, CONCEPTS, CandidateDecision, FallbackAudit, FilingInput
from .pdf import PageText, extract_pdf, pdf_pages, pdf_document_kind, render_pdf_pages, PARSER_VERSION as PDF_VERSION
from .processing import ProcessingCache
from .llm import OpenAIExtraction, CandidateResult, CandidateAdmissionError, PROMPT_VERSION, SCHEMA_VERSION, PdfSemanticResult
from .derivation import (derive_debt, DERIVATION_VERSION, derive_balance_sheet_subtotals,
                         BALANCE_SHEET_DERIVATION_VERSION)
from .fallback import ADMISSION_VERSION, admit_candidate, select_evidence
from .pdf_semantic import admit_pdf_candidate, PARSER_VERSION as PDF_SEMANTIC_VERSION
from .asset_side import inspect_asset_side, debt_completeness_notes, PARSER_VERSION as ASSET_PARSER_VERSION
from .interpretation_workflow import interpret
from .interpretation import VERSION as INTERPRETATION_VERSION, canonical as interpretation_canonical, verify
from .ixbrl_semantic import complete as complete_ixbrl
from .period_selection import select_period, closest_year, VERSION as PERIOD_SELECTION_VERSION
from .semantic_values import semantic_period
from .coverage import resolved_concepts, with_coverage, coverage_note
from .normalization import normalize_source_fact, normalize_canonical_fact


class AccountsIngestion:
    """Acquire only M2-linked accounts; failed documents do not erase valid results."""

    def __init__(self, database: Database, storage: EvidenceStorage, client: DocumentClient | None,
                 *, registry: FinancialMappingRegistry | None = None,
                 tessdata: str | None = None, ocr_version: str = 'disabled',
                 llm: OpenAIExtraction | None = None) -> None:
        self.database, self.client = database, client
        self.repository = AccountsRepository(database)
        self.evidence = EvidencePersistence(database, storage)
        self.publication = AccountsPublication(database, self.evidence)
        self.cache = ProcessingCache(database, self.evidence)
        self.registry = registry or default_registry()
        self.tessdata, self.ocr_version = tessdata, ocr_version
        self.llm = llm
        self._progress: Callable[[str, str], None] | None = None

    def _extract(self, raw: RawEvidence, run_id: str, number: str, *, reporting_year: int | None = None,
                 authoritative_period_end: date | None = None) -> tuple[ExtractionResult, bool]:
        if raw.media_type != 'application/pdf':
            try:
                output, reused = self.cache.run(raw, run_id, 'PARSE', IX_VERSION, {},
                    lambda content: extract_ixbrl(content, raw.document_id, number).model_dump_json().encode())
                result = ExtractionResult.model_validate_json(output)
            except ParseError as error:
                # Unsupported taxonomy/context parsing is exactly why the original
                # XHTML is handed to AI. It must not trigger PDF or skip semantic reading.
                result = ExtractionResult(facts=(), periods=(), complete=False,
                    reason=f'Deterministic iXBRL parsing was incomplete: {error}')
                reused = False
            result = complete_ixbrl(self, raw, run_id, number, result, reporting_year, authoritative_period_end)
            return select_period(result, int(reporting_year or 1900), authoritative_period_end), reused

        # PDF Foundation route: the filed PDF itself is the evidence supplied to OpenAI.
        # OCR/deterministic PDF table parsing is deliberately not an extraction/admission
        # dependency. iXBRL remains preferred and this route is reached only for a PDF
        # representation selected by the orchestration.
        content = self.evidence.read(raw.raw_evidence_id)
        if self.llm is None or not self.llm.enabled:
            raise ParseError('PDF financial extraction requires configured OpenAI semantic extraction')
        import pymupdf
        try:
            with pymupdf.open(stream=content, filetype='pdf') as document:
                if document.is_encrypted or not 1 <= len(document) <= 200:
                    raise ParseError('Encrypted PDF or page bound exceeded')
                page_numbers = tuple(range(1, len(document) + 1))
        except ParseError:
            raise
        except Exception:
            raise ParseError('Filed PDF could not be opened for semantic extraction') from None
        targets = ('NET_ASSETS', 'TOTAL_ASSETS', 'CURRENT_ASSETS', 'CURRENT_LIABILITIES', 'INVENTORY')
        evidence = json.dumps({
            'unresolved_concepts': targets,
            'preferred_reporting_year': reporting_year,
            'selected_filing_period': authoritative_period_end.isoformat() if authoritative_period_end else None,
            'instruction': (
                'Read the filed PDF pages semantically. Extract one selected COMPANY statement column. '
                'Use accounting meaning rather than exact labels (for example Stocks/Inventories -> INVENTORY; '
                'Creditors: amounts falling due within one year -> CURRENT_LIABILITIES). '
                'This is the selected filing. The search year is only a preference: select the displayed '
                'column closest to it, report the actual year, and do not discard a value because its year differs. '
                'If no year is shown, use this filing current column. Read all pages and relevant notes. '
                'Do not calculate ratios or risk.'
            )}, sort_keys=True)
        if self._progress:
            self._progress('multimodal_llm',
                f'PDF semantic route: sending complete original PDF ({len(page_numbers)} pages) directly to OpenAI; OCR is not used')
        pdf_sha = sha256(content).hexdigest()
        try:
            output, reused = self.cache.run(raw, run_id, 'LLM', 'financial-pdf-semantic-v32-expert',
                {'schema': SCHEMA_VERSION, 'model': self.llm.model, 'config': self.llm.config_version,
                 'evidence_sha': sha256(evidence.encode()).hexdigest(), 'pdf_sha': pdf_sha,
                 'max_output_tokens': 8000}, lambda _: self.llm.extract_pdf_file(evidence, content))
        except ParseError as error:
            # Provider/transport/schema failure is not evidence that the company omitted
            # the values. Return an explicit unresolved result so all five canonical
            # inputs are persisted as EXTRACTION_FAILED with a durable reason.
            marker = ReportingPeriod(period_type=PeriodType.INSTANT,
                period_end=authoritative_period_end or date(int(reporting_year or 1900), 12, 31),
                comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
            return ExtractionResult(facts=(), periods=(marker,), complete=False,
                reason=f'OpenAI PDF semantic extraction failed: {error}').model_copy(update={
                    'completeness_notes': (f'TECHNICAL_EXTRACTION_FAILURE: {error}',)
                }), False
        if self._progress:
            self._progress('openai_response', 'OpenAI filed-PDF semantic artifact returned; validating structured candidates')

        def admit(_: bytes) -> bytes:
            artifact = json.loads(output)
            if artifact.get('status') != 'completed':
                raise ParseError('OpenAI PDF semantic response was incomplete')
            try:
                candidates = PdfSemanticResult.model_validate_json(artifact['output']).candidates
            except (ValueError, KeyError, TypeError):
                raise ParseError('OpenAI PDF semantic output was malformed') from None
            supported = [c for c in candidates if c.scope == 'COMPANY' and c.support == 'SUPPORTED'
                         and c.concept in targets and c.raw_value is not None]
            if supported:
                returned_years = {semantic_period(c.period_end, int(reporting_year or 1900),
                                                 authoritative_period_end).year for c in supported}
                chosen_year = closest_year(returned_years, int(reporting_year or 1900))
                candidates = [c for c in candidates if semantic_period(c.period_end,
                    int(reporting_year or 1900), authoritative_period_end).year == chosen_year]
            facts = []
            decisions = []
            rendered = frozenset(page_numbers)
            requested = frozenset(targets)
            # Reporting-year semantics are intentionally year-level.  The selected filing
            # already represents the user's requested reporting year.  Day/month metadata
            # may be retained internally for persistence/provenance, but it is never an
            # OpenAI admission requirement and is never used to reject a correct target-year
            # value.
            semantic_period_end = authoritative_period_end
            if self._progress:
                self._progress('semantic_candidates', f'Validating {len(candidates)} OpenAI candidate(s) against filed PDF evidence')
            for index, candidate in enumerate(candidates):
                identity = None
                try:
                    fact = admit_pdf_candidate(candidate, document_id=raw.document_id,
                        company_number=number, rendered_pages=rendered, requested=requested,
                        requested_reporting_year=int(reporting_year or 0),
                        authoritative_period_end=semantic_period_end)
                    facts.append(fact)
                    identity = fact.source_fact_id
                    status, reason = 'AVAILABLE', 'Filed PDF semantics, COMPANY scope, current period and value accepted'
                except ParseError as error:
                    status, reason = ('EXTRACTION_FAILED' if candidate.support == 'UNRESOLVED' else 'VALIDATION_FAILED'), str(error)
                decisions.append(CandidateDecision(candidate_index=index, concept=candidate.concept,
                    kind=candidate.kind, period_end=candidate.period_end, status=status, reason=reason,
                    source_fact_id=identity))
                if self._progress:
                    display_concept = f'{candidate.concept}_BRIDGE' if candidate.kind == 'COMPONENT' else candidate.concept
                    display_status = 'ACCEPTED' if candidate.kind == 'COMPONENT' and status == 'AVAILABLE' else status
                    self._progress('semantic_decision',
                        f'{display_concept}: {display_status}; label={candidate.label!r}; value={candidate.raw_value or "--"}; page={candidate.page}; reason={reason}')
            if not facts:
                # A successful semantic read that finds none of the requested concepts is
                # a valid evidence outcome, not a processing failure.  Persist explicit
                # NOT_DISCLOSED facts below so downstream risk variables can explain
                # exactly which inputs the selected filing did not disclose.
                if self._progress:
                    self._progress('semantic_validation',
                        'OpenAI completed semantic review; no requested financial values were identified')
            if self._progress:
                accepted = sum(1 for d in decisions if d.status == 'AVAILABLE')
                self._progress('semantic_validation',
                    f'Evidence admission completed: {accepted} accepted, {len(decisions) - accepted} unresolved/rejected candidate(s)')
            periods = {fact.period.model_dump_json(): fact.period for fact in facts}
            if not periods and reporting_year is not None:
                # Schema compatibility marker only.  The requested year selected the filing;
                # day/month are not evidence and never participate in semantic admission.
                marker = ReportingPeriod(period_type=PeriodType.INSTANT,
                    period_end=authoritative_period_end or date(int(reporting_year), 12, 31),
                    comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
                periods[marker.model_dump_json()] = marker
            return ExtractionResult(facts=tuple(facts), periods=tuple(periods.values()), complete=True,
                reason='Filed PDF extracted by direct OpenAI semantic route; OCR not used',
                fallback=FallbackAudit(targets=targets, pages=tuple(page_numbers), status='COMPLETE',
                                       decisions=tuple(decisions))).model_dump_json().encode()

        try:
            admitted, _ = self.cache.run(raw, run_id, 'PARSE', PDF_SEMANTIC_VERSION,
                {'llm_output_sha': sha256(output).hexdigest(), 'admission': PDF_SEMANTIC_VERSION,
                 'schema': 'financial-pdf-semantic-v32-expert'}, admit)
            selected = select_period(ExtractionResult.model_validate_json(admitted),
                                     int(reporting_year or 1900), authoritative_period_end)
            found = resolved_concepts(selected.facts, self.registry, number, raw.source_id, run_id)
            selected = with_coverage(selected, route='PDF/OpenAI', before=(), requested=targets, after=found)
            if self._progress:
                self._progress('financial_route_summary', coverage_note(selected))
            return selected, reused
        except (ParseError, ValueError, KeyError, TypeError) as error:
            marker = ReportingPeriod(period_type=PeriodType.INSTANT,
                period_end=authoritative_period_end or date(int(reporting_year or 1900), 12, 31),
                comparability_status=ComparabilityStatus.REVIEW_REQUIRED)
            return ExtractionResult(facts=(), periods=(marker,), complete=False,
                reason='OpenAI PDF response could not be interpreted',
                completeness_notes=(f'TECHNICAL_EXTRACTION_FAILURE: {error}',)), reused

    def _foundation_coverage(self, result: ExtractionResult, number: str, run_id: str, raw: RawEvidence) -> int:
        """Count distinct directly supported A-D financial inputs in one representation.

        This score is used only to decide whether a lower-priority representation
        should be attempted. It never changes a fact value or treats absence as zero.
        """
        required = {'NET_ASSETS', 'TOTAL_ASSETS', 'CURRENT_ASSETS', 'CURRENT_LIABILITIES', 'INVENTORY'}
        found = set()
        for fact in result.facts:
            mapped = self.registry.map(fact, company_id='coverage', company_number=number,
                                       source_id=raw.source_id, processing_run_id=run_id)
            if mapped is not None and mapped.availability_status == AvailabilityStatus.AVAILABLE:
                found.add(mapped.canonical_concept)
        for derived, _, _ in derive_balance_sheet_subtotals(result.facts,
                company_id='coverage', source_id=raw.source_id, run_id=run_id,
                mapping_version=self.registry.version):
            found.add(derived.canonical_concept)
        return len(required & found)

    def _fallback(self, raw: RawEvidence, run_id: str, number: str,
                  pages: tuple[PageText, ...], deterministic: ExtractionResult, *,
                  multimodal: bool = False, pdf_content: bytes | None = None) -> ExtractionResult:
        # Check concept x period, not merely whether the parser returned any facts.
        available = set()
        for fact in deterministic.facts:
            canonical = self.registry.map(fact, company_id='coverage', company_number=number,
                                          source_id=raw.source_id, processing_run_id=run_id)
            if canonical is not None and canonical.availability_status == AvailabilityStatus.AVAILABLE:
                available.add((canonical.canonical_concept, fact.period.period_end))
        required_foundation = ('NET_ASSETS', 'TOTAL_ASSETS', 'CURRENT_ASSETS', 'CURRENT_LIABILITIES', 'INVENTORY')
        targets = tuple(concept for concept in required_foundation if not deterministic.periods or
                        any((concept, period.period_end) not in available for period in deterministic.periods))
        if not targets:
            return deterministic
        evidence, selected = select_evidence(pages, targets)
        page_ids = tuple(page.page for page in selected)
        if not selected or self.llm is None or not self.llm.enabled:
            audit = FallbackAudit(targets=targets, pages=page_ids,
                status='UNAVAILABLE' if selected else 'NO_RELEVANT_EVIDENCE')
            return deterministic.model_copy(update={'fallback': audit,
                'reason': (deterministic.reason or 'Required inputs unresolved') + '; fallback ' + audit.status})
        try:
            if multimodal and pdf_content is not None:
                page_numbers = page_ids or tuple(page.page for page in pages[:12])
                images = render_pdf_pages(pdf_content, page_numbers)
                if self._progress:
                    self._progress('multimodal_llm', f'Scanned/mixed PDF: sending {len(images)} filed page image(s) plus OCR locators to OpenAI')
                pdf_sha = sha256(content).hexdigest()
                output, _ = self.cache.run(raw, run_id, 'LLM', 'financial-multimodal-located-v1',
                    {'schema': SCHEMA_VERSION, 'model': self.llm.model, 'config': self.llm.config_version,
                     'evidence_sha': sha256(evidence.encode()).hexdigest(), 'pdf_sha': pdf_sha,
                     'max_output_tokens': 5000}, lambda _: self.llm.extract_images(evidence, images))
            else:
                if self._progress:
                    self._progress('semantic_llm', 'Native PDF unresolved accounting semantics sent to OpenAI with located text evidence')
                output, _ = self.cache.run(raw, run_id, 'LLM', PROMPT_VERSION,
                    {'schema': SCHEMA_VERSION, 'model': self.llm.model, 'config': self.llm.config_version,
                     'evidence_sha': sha256(evidence.encode()).hexdigest(), 'max_output_tokens': 5000},
                    lambda _: self.llm.extract(evidence))
        except ParseError:
            # Failed optional work must not discard supported deterministic facts.
            return deterministic.model_copy(update={'fallback': FallbackAudit(
                targets=targets, pages=page_ids, status='EXTRACTION_FAILED'),
                'reason': (deterministic.reason or 'Required inputs unresolved') + '; fallback unavailable or failed'})

        def verify(_: bytes) -> bytes:
            artifact = json.loads(output)
            decisions = []
            admitted = []
            try:
                if artifact.get('status') != 'completed':
                    raise ValueError('Incomplete response')
                candidates = CandidateResult.model_validate_json(artifact['output']).candidates
                if self._progress:
                    self._progress('llm_response', f'OpenAI response parsed successfully; {len(candidates)} candidate(s) returned')
                    self._progress('semantic_candidates', f'Validating {len(candidates)} OpenAI candidate(s) against filed evidence')
            except ValueError:
                if self._progress:
                    self._progress('llm_response_failed', 'OpenAI artifact was returned but its structured candidate payload was malformed/incomplete')
                return deterministic.model_copy(update={'fallback': FallbackAudit(
                    targets=targets, pages=page_ids, status='EXTRACTION_FAILED'),
                    'complete': False, 'reason': 'LLM output malformed/incomplete; deterministic facts retained'}).model_dump_json().encode()
            for index, candidate in enumerate(candidates):
                identity = None
                try:
                    if candidate.concept not in targets:
                        raise CandidateAdmissionError('Candidate concept was not requested')
                    if candidate.support == 'UNRESOLVED' or candidate.raw_value is None or candidate.value is None:
                        status, reason = 'EXTRACTION_FAILED', 'Model returned unresolved/no supported value'
                    else:
                        supported_units = frozenset((fact.currency, fact.unit) for fact in deterministic.facts
                            if fact.availability_status == AvailabilityStatus.AVAILABLE and fact.currency and fact.unit)
                        fact = admit_candidate(candidate, selected, raw.document_id, number,
                                               supported_units=supported_units)
                        admitted.append(fact)
                        identity = fact.source_fact_id
                        status, reason = 'AVAILABLE', 'Excerpt, label, amount, period, unit and company scope verified'
                except (CandidateAdmissionError, ParseError) as error:
                    status, reason = 'VALIDATION_FAILED', str(error)
                decisions.append(CandidateDecision(candidate_index=index, concept=candidate.concept,
                    kind=candidate.kind, period_end=candidate.period_end, status=status, reason=reason, source_fact_id=identity))
                if self._progress:
                    shown_value = candidate.raw_value if candidate.raw_value is not None else '--'
                    display_concept = (f'{candidate.concept}_BRIDGE' if candidate.kind == 'COMPONENT'
                                       else candidate.concept)
                    display_status = ('ACCEPTED' if candidate.kind == 'COMPONENT' and status == 'AVAILABLE'
                                      else status)
                    self._progress('semantic_decision',
                        f'{display_concept}: {display_status}; label={candidate.label!r}; value={shown_value}; page={candidate.page}; reason={reason}')
            if self._progress:
                accepted = sum(1 for d in decisions if d.status == 'AVAILABLE')
                rejected = len(decisions) - accepted
                self._progress('semantic_validation', f'Evidence admission completed: {accepted} accepted, {rejected} unresolved/rejected candidate(s)')
            facts = {fact.source_fact_id: fact for fact in (*deterministic.facts, *admitted)}
            periods = {period.model_dump_json(): period for period in deterministic.periods}
            periods.update({fact.period.model_dump_json(): fact.period for fact in admitted})
            result = deterministic.model_copy(update={'facts': tuple(facts.values()), 'periods': tuple(periods.values()),
                'complete': False, 'fallback': FallbackAudit(targets=targets, pages=page_ids,
                    status='COMPLETE', decisions=tuple(decisions)),
                'reason': 'Deterministic facts retained; fallback candidates individually checked; disclosure completeness unresolved'})
            return result.model_dump_json().encode()
        merged, _ = self.cache.run(raw, run_id, 'PARSE', ADMISSION_VERSION,
            {'llm_output_sha': sha256(output).hexdigest(),
             'deterministic_sha': sha256(deterministic.model_dump_json().encode()).hexdigest()}, verify)
        admitted_result = ExtractionResult.model_validate_json(merged)
        if self._progress:
            accepted = sum(1 for d in (admitted_result.fallback.decisions if admitted_result.fallback else ()) if d.status == 'AVAILABLE')
            self._progress('semantic_admission_complete', f'OpenAI candidate processing finished; {accepted} candidate fact(s) admitted to the extraction result')
        return admitted_result

    def _save_facts(self, raw: RawEvidence, result: ExtractionResult) -> tuple[str, ...]:
        # Source records and canonical mapping are separately identifiable; mapping
        # changes add observations without rewriting source evidence or values.
        source = self.evidence.sources.get(raw.source_id)
        references = SqlEvidenceReferenceRepository(self.database)
        present: set[tuple[str, str]] = set()
        unresolved = False
        output_ids: list[str] = []
        direct_by_source: dict[str, FinancialFact] = {}
        extraction_sha = sha256(result.model_dump_json().encode()).hexdigest()
        with self.database.transaction():
            for extracted_fact in result.facts:
                # One route-independent cleaning boundary: iXBRL and direct PDF/OpenAI
                # observations all pass here before structured persistence. Raw
                # labels/values/evidence remain immutable and traceable.
                fact = normalize_source_fact(extracted_fact)
                locator = (PdfLocator(page=fact.page, label=fact.source_label or fact.source_concept,
                                      section=fact.statement_context)
                           if fact.page else IxbrlLocator(concept=fact.source_concept, context_id=fact.context_ref))
                references.save(fact.evidence_id, EvidenceReference(evidence_id=fact.evidence_id,
                    source_id=source.source_id, document_id=fact.document_id,
                    location=locator, evidence_text=fact.raw_value))
                self.repository.save_source(fact)
                canonical = self.registry.map(fact, company_id=source.company_id,
                    company_number=source.company_number, source_id=source.source_id,
                    processing_run_id=source.processing_run_id)
                if canonical is not None:
                    canonical = normalize_canonical_fact(canonical, fact)
                    self.repository.save_direct(canonical, fact.source_fact_id, self.registry.version)
                    output_ids.append(canonical.financial_fact_id)
                    present.add((canonical.canonical_concept, fact.period.model_dump_json()))
                    direct_by_source[fact.source_fact_id] = canonical
                else:
                    unresolved = True
            # Exact balance-sheet subtotal identities can recover required v1.2
            # denominators when a filing does not tag TotalAssets/CurrentLiabilities
            # directly. Direct mapped facts always take precedence.
            for derived, component_ids, rule in derive_balance_sheet_subtotals(
                    result.facts, company_id=source.company_id, source_id=source.source_id,
                    run_id=source.processing_run_id, mapping_version=self.registry.version):
                key = (derived.canonical_concept, derived.period.model_dump_json())
                if key in present:
                    continue
                self.repository.save_derived(derived, component_ids, self.registry.version,
                    BALANCE_SHEET_DERIVATION_VERSION, rule)
                present.add(key)
                output_ids.append(derived.financial_fact_id)
            for schedule in (() if result.interpretations else result.debt_schedules):
                derived = derive_debt(schedule, result.facts, company_id=source.company_id,
                    source_id=source.source_id, run_id=source.processing_run_id, mapping_version=self.registry.version)
                self.repository.save_derived(derived, schedule.source_fact_ids, self.registry.version,
                    DERIVATION_VERSION, 'sum(complete non-overlapping components); ' + schedule.completeness_quote)
                present.add(('INTEREST_BEARING_DEBT', derived.period.model_dump_json()))
                output_ids.append(derived.financial_fact_id)
            for decision in result.interpretations:
                proposal = decision.proposal
                admitted = None
                if decision.status == 'AVAILABLE':
                    checked = verify(proposal, result, self.registry)
                    if checked.status != 'AVAILABLE' or checked.value != decision.value:
                        raise ParseError('Persisted interpretation failed admission recheck')
                    if proposal.kind == 'NORMALIZATION':
                        admitted = direct_by_source.get(proposal.operands[0].source_fact_id)
                    if admitted is None:
                        admitted = interpretation_canonical(decision, result, company_id=source.company_id,
                            source_id=source.source_id, run_id=source.processing_run_id)
                        if proposal.kind == 'NORMALIZATION':
                            self.repository.save_direct(admitted, proposal.operands[0].source_fact_id, INTERPRETATION_VERSION)
                        else:
                            proof = next(p for p in result.proofs if p.proof_id == proposal.proof_id)
                            references.save(proof.proof_id, EvidenceReference(evidence_id=proof.proof_id,
                                source_id=source.source_id, document_id=raw.document_id,
                                location=PdfLocator(page=proof.page,label=f'{proof.relationship}; rows {proof.row_start}-{proof.row_end}'),
                                evidence_text=proof.evidence_text))
                            components = tuple(o.source_fact_id for o in proposal.operands)
                            self.repository.save_derived(admitted,components,self.registry.version,INTERPRETATION_VERSION,
                                proposal.model_dump_json(),admitted.evidence_ids[len(components):])
                            self.repository.save_derivation_proof(admitted, proof)
                        output_ids.append(admitted.financial_fact_id)
                    present.add((admitted.canonical_concept,admitted.period.model_dump_json()))
                if result.interpretation_artifact_id:
                    contexts = [c for c in result.contexts if proposal.operands
                                and c.source_fact_id == proposal.operands[0].source_fact_id]
                    if self._progress:
                        self._progress('semantic_persist_start', f'Persisting {proposal.method} decision for {proposal.target}; status={decision.status}')
                    self.repository.save_interpretation(raw.document_id,result.interpretation_artifact_id,
                        decision,admitted.financial_fact_id if admitted else None,
                        contexts[0] if len(contexts) == 1 else None)
                    if self._progress:
                        self._progress('semantic_persist_done', f'Persisted {proposal.method} decision for {proposal.target}')
            technical_semantic_failure = any(
                ('TECHNICAL_EXTRACTION_FAILURE' in note or 'Optional semantic proposal unavailable' in note)
                for note in result.completeness_notes)
            for period in result.periods:
                for concept in CONCEPTS:
                    if (concept, period.model_dump_json()) in present:
                        continue
                    identity = sha256(f'{raw.document_id}:{extraction_sha}:{self.registry.version}:{concept}:{period.model_dump_json()}:missing'.encode()).hexdigest()
                    interpretation_failed = any(decision.status == 'VALIDATION_FAILED'
                        and decision.proposal.target == concept and decision.proposal.period_end == period.period_end
                        for decision in result.interpretations)
                    missing = FinancialFact(financial_fact_id=identity, company_id=source.company_id,
                        company_number=source.company_number, canonical_concept=concept, value_numeric=None,
                        period=period, source_id=source.source_id, document_id=raw.document_id,
                        extraction_method=(result.facts[0].extraction_method if result.facts else (ExtractionMethod.LLM_NATIVE_TEXT if raw.media_type == 'application/pdf' else ExtractionMethod.IXBRL_DIRECT)),
                        availability_status=(AvailabilityStatus.VALIDATION_FAILED if interpretation_failed or (result.fallback and any(
                            decision.concept == concept and decision.kind == 'DIRECT' and decision.status == 'VALIDATION_FAILED'
                            for decision in result.fallback.decisions))
                            # Successful deterministic/semantic examination with no admitted
                            # value means the selected company filing did not disclose a
                            # supported value for this concept.  Missingness is data, not a
                            # pipeline failure.
                            else AvailabilityStatus.EXTRACTION_FAILED if technical_semantic_failure or (result.fallback and any(
                                decision.concept == concept and decision.status == 'EXTRACTION_FAILED'
                                for decision in result.fallback.decisions))
                            else AvailabilityStatus.NOT_DISCLOSED),
                        processing_run_id=source.processing_run_id)
                    self.repository.canonical.save(identity, missing)
                    # Persist the explanation separately from the value/status contract so
                    # future drill-down can answer WHY a financial input is Unknown.
                    if missing.availability_status == AvailabilityStatus.NOT_DISCLOSED:
                        reason_code = 'NOT_FOUND_IN_SELECTED_ACCOUNTS'
                        reason_text = (f'No supported {concept} value was identified in the company selected accounts evidence. '
                                       'The selected filing was successfully examined; this is recorded as not disclosed, not as a technical failure.')
                    elif missing.availability_status == AvailabilityStatus.VALIDATION_FAILED:
                        reason_code = 'VALIDATION_FAILED'
                        reason_text = f'A candidate for {concept} was found but did not pass substantive evidence validation.'
                    else:
                        reason_code = 'EXTRACTION_FAILED'
                        reason_text = f'The selected accounts evidence could not be reliably interpreted for {concept}.'
                    candidate_reasons = tuple(decision.reason for decision in
                        (result.fallback.decisions if result.fallback else ())
                        if decision.concept == concept and decision.status != 'AVAILABLE')
                    failure_notes = tuple(note for note in result.completeness_notes
                                          if 'TECHNICAL_EXTRACTION_FAILURE' in note)
                    details = candidate_reasons or failure_notes
                    if details:
                        reason_text += ' Details: ' + '; '.join(details)
                    self.database.execute(
                        'INSERT OR IGNORE INTO financial_fact_missing_reason VALUES (?,?,?,?,?,?)',
                        (identity, reason_code, reason_text, raw.document_id, source.processing_run_id,
                         datetime.now(UTC).isoformat()))
                    output_ids.append(identity)
        return tuple(output_ids)

    def ingest(self, company_number: str, assessment_date: date, run_id: str,
               *, reporting_year: int, max_documents: int = 5, force_refresh: bool = False,
               progress: Callable[[str, str], None] | None = None) -> ProcessingRun:
        """Select one reporting year from evidence available by the assessment date.

        The requested year is preferred exactly. If it is unavailable within the
        explicit document bound, the closest successfully extracted CURRENT period
        is selected; equal distance prefers the earlier year. Only the selected
        filing's canonical facts become inputs to this M3 run. Other immutable raw
        evidence and parser outputs remain retained for audit/reuse.
        """
        if type(reporting_year) is not int or not 1900 <= reporting_year <= 9999:
            raise ValueError('reporting_year must be a four-digit year')
        if not 1 <= max_documents <= 10:
            raise ValueError('Document bound must be between 1 and 10')
        self.cache.force_fresh = force_refresh
        emit = progress or (lambda _event, _detail: None)
        self._progress = progress
        company = SqlCompanyRepository(self.database).get_by_company_number(company_number)
        if company is None:
            raise IntegrityError('Run M2 company ingestion before M3')
        # Evidence published after the assessment date is ineligible even if it is
        # present in the latest M2 snapshot.
        filings = tuple(f for f in self.repository.filings(company.company_id)
                        if f.filing_date <= assessment_date)
        runs = SqlAssessmentRepository(self.database)
        if runs.get_processing_run(run_id) is not None:
            raise IntegrityError('M3 orchestration requires a new run identity')
        run = ProcessingRun(processing_run_id=run_id, company_id=company.company_id,
            company_number=company_number, started_at=datetime.now(UTC), status=ProcessingStatus.RUNNING,
            current_stage='M3', trigger_type=TriggerType.LIVE, app_version='m3-v1')
        runs.save_processing_run(run)
        with self.database.transaction():
            self.database.execute('INSERT INTO accounts_run VALUES (?,?,?,?,?)',
                (run_id, encode(assessment_date), max_documents, self.registry.version, 'RUNNING'))

        # Select the filing using its own made-up metadata, never a company-wide
        # profile date belonging to a different statement in the same calendar year.
        def filing_period(filing: FilingInput) -> date | None:
            """Read only the selected filing made-up date; conflicting metadata gives no hint."""
            rows = self.database.query(
                "SELECT value_text FROM fact WHERE company_id=? AND subject_identifier=? "
                "AND canonical_concept='FILINGS_DESCRIPTION_VALUES_JSON' "
                "AND availability_status='AVAILABLE' AND value_text IS NOT NULL",
                (company.company_id, filing.filing_id))
            ends = set()
            for row in rows:
                try:
                    values = json.loads(str(row['value_text']))
                    made_up = values.get('made_up_date') if isinstance(values, dict) else None
                    if isinstance(made_up, str):
                        ends.add(date.fromisoformat(made_up))
                except (ValueError, TypeError):
                    continue
            return next(iter(ends)) if len(ends) == 1 else None

        filing_hints = {f.filing_fact_id: filing_period(f) for f in filings}
        filings = tuple(sorted(filings, key=lambda f: (
            abs(filing_hints[f.filing_fact_id].year - reporting_year)
                if filing_hints[f.filing_fact_id] else 10000,
            -f.filing_date.toordinal())))
        candidates = []
        for filing in filings[:max_documents]:
            raw = None
            reused_raw = reused_parse = False
            canonical_ids = ()
            evidence_year = None
            period_end = None
            filing_period_hint = filing_hints[filing.filing_fact_id]
            authoritative_period_hint = filing_period_hint
            if filing_period_hint:
                emit('reporting_period_anchor',
                     f'Selected filing made-up date: {filing_period_hint.isoformat()}; search preference {reporting_year}')
            try:
                existing = None if force_refresh else self.repository.reusable_document(filing)
                if existing:
                    raw = self.evidence.raw.get(existing)
                    self.evidence.read(existing)
                    reused_raw = True
                    result, reused_parse = self._extract(raw, run_id, company_number, reporting_year=reporting_year,
                        authoritative_period_end=authoritative_period_hint)
                else:
                    if self.client is None:
                        raise RetrievalError('No reusable raw accounts evidence; network retrieval is disabled')
                    emit('accounts_metadata_request', f'Requesting Companies House document metadata for filing {filing.filing_id}')
                    metadata = self.client.get(filing.metadata_url)
                    metadata_source, _, _ = self.publication.publish(company, run_id, filing, metadata)
                    emit('accounts_metadata_stored', 'Document metadata retrieved and immutable raw JSON persisted')
                    parsed_metadata = json_object(metadata)
                    expected_id = filing.metadata_url.rsplit('/', 1)[1]
                    if parsed_metadata.get('id', expected_id) != expected_id:
                        raise ParseError('Document metadata identity mismatch')
                    available = representations(parsed_metadata)
                    if not available:
                        raise ParseError('No supported document representation')
                    emit('representations', 'Available Companies House representations: ' + ', '.join(available))
                    # Evidence strategy: an iXBRL/XHTML representation delivered by
                    # Companies House is the primary filed accounts document.  It is
                    # both machine-readable and human-readable XHTML, so semantic
                    # interpretation may operate on its evidence when taxonomy labels
                    # alone do not resolve a canonical fact.  PDF is a fallback only
                    # when no supported iXBRL/XML representation is available.
                    ix = tuple(m for m in available if m != 'application/pdf')
                    # Final Foundation policy: if iXBRL/XHTML exists, it is the only
                    # accounts representation used.  Deterministic taxonomy mapping runs
                    # first; original XHTML is then supplied directly for missing concepts.
                    # PDF multimodal is used only when no iXBRL/XHTML representation exists.
                    selected_media = (ix[0],) if ix else (('application/pdf',) if 'application/pdf' in available else ())
                    emit('ixbrl_route_selected' if ix else 'pdf_route_selected',
                         'iXBRL/XHTML available: deterministic extraction then OpenAI semantic interpretation for unresolved concepts; PDF will not be used'
                         if ix else 'No iXBRL/XHTML available: direct PDF/OpenAI semantic extraction')
                    result = None
                    best = None
                    extracted_representations = []
                    authoritative_period_hint = filing_period_hint
                    for media in selected_media:
                        label = 'iXBRL/XHTML' if media != 'application/pdf' else 'PDF'
                        emit('representation_request', f'Requesting {label} from Companies House')
                        response = self.client.get(filing.metadata_url, media)
                        emit('representation_retrieved', f'{label} HTTP retrieval completed ({len(response.body)} bytes); publishing immutable evidence')
                        _, candidate_raw, _ = self.publication.publish(company, run_id, filing, response,
                                                            metadata_source_id=metadata_source.source_id)
                        # EvidencePersistence.save writes first, then reads back and verifies checksum.
                        emit('representation_stored', f'{label} persisted as immutable raw evidence ({len(response.body)} bytes)')
                        try:
                            candidate_result, candidate_reused = self._extract(candidate_raw, run_id, company_number,
                                reporting_year=reporting_year, authoritative_period_end=authoritative_period_hint)
                        except CandidateAdmissionError:
                            raise
                        except ParseError as error:
                            emit('representation_extract_failed', f'{label} deterministic/fallback extraction unresolved: {error}')
                            continue
                        score = self._foundation_coverage(candidate_result, company_number, run_id, candidate_raw)
                        emit('representation_extracted', f'{label} extraction completed; direct financial coverage {score}/5')
                        extracted_representations.append((media, candidate_raw, candidate_result, score))
                        if best is None or score > best[0]:
                            best = (score, candidate_raw, candidate_result, candidate_reused)
                        # Complete preferred evidence needs no lower-priority download.
                        if score == 5:
                            break
                    if best is None:
                        raise ParseError('Representations could not be adequately extracted')
                    emit('cross_validation', 'Selected filed representation processed under iXBRL-first / PDF-only-if-no-iXBRL policy')
                    _, raw, result, reused_parse = best
                    emit('representation_selected', f'Selected {"PDF" if raw.media_type == "application/pdf" else "iXBRL/XHTML"} as primary extraction evidence; verified coverage {best[0]}/5')

                def publish_canonical(_: bytes) -> bytes:
                    emit('canonical_persist_start', 'Normalizing and writing source/canonical financial facts and missingness reasons')
                    fact_ids = self._save_facts(raw, result)
                    emit('canonical_persist_done', 'Canonical financial facts and reasons persisted')
                    return json.dumps({'mapping_version': self.registry.version,
                        'derivation_version': DERIVATION_VERSION,
                        'balance_sheet_derivation_version': BALANCE_SHEET_DERIVATION_VERSION,
                        'asset_derivation_version': ASSET_PARSER_VERSION,
                        'canonical_fact_ids': fact_ids,
                        'source_fact_ids': [fact.source_fact_id for fact in result.facts]}, sort_keys=True).encode()
                canonical_output, _ = self.cache.run(raw, run_id, 'CANONICAL', self.registry.version,
                    {'derivation': DERIVATION_VERSION, 'balance_sheet': BALANCE_SHEET_DERIVATION_VERSION, 'assets': ASSET_PARSER_VERSION, 'interpretation':INTERPRETATION_VERSION, 'output_schema': 6,
                     'period_policy': PERIOD_SELECTION_VERSION,
                     'source_facts_sha': sha256(result.model_dump_json().encode()).hexdigest()}, publish_canonical)
                canonical_ids = tuple(json.loads(canonical_output)['canonical_fact_ids'])
                # The extraction contains exactly one source statement period. This
                # is provenance, not a requirement to match the search preference.
                period_end = result.periods[0].period_end
                evidence_year = period_end.year
                status = 'COMPLETE' if result.complete else 'PARTIAL'
                availability = 'AVAILABLE'
                reason = result.reason or 'Supported extraction completed; M4 review remains required'
                summary = coverage_note(result)
                if summary:
                    reason += '\n' + summary
                candidates.append((evidence_year, period_end, filing, canonical_ids, status))
            except RetrievalError as error:
                status, availability = 'FAILED', 'RETRIEVAL_FAILED'
                if isinstance(error, DocumentRetrievalError):
                    reason = error.safe_reason
                else:
                    http = error.status if type(error.status) is int and 100 <= error.status <= 599 else None
                    reason = f'Document retrieval failed; stage=UNKNOWN; code=UNKNOWN; http={http if http is not None else "NONE"}'
            except CandidateAdmissionError:
                status, availability, reason = 'FAILED', 'VALIDATION_FAILED', 'LLM artifact retained; numeric candidate failed evidence admission'
            except ParseError as error:
                status, availability = 'FAILED', 'EXTRACTION_FAILED'
                reason = str(error)[:500] or 'Document extraction failed or requires unsupported processing'
                emit('representation_extract_failed', reason)
            with self.database.transaction():
                self.database.execute('INSERT INTO accounts_run_document VALUES (?,?,?,?,?,?,?,?)',
                    (run_id, filing.filing_fact_id, raw.document_id if raw else None,
                     status, availability, reason, int(reused_raw), int(reused_parse)))
            # The upstream filing choice is already made. A displayed different year
            # is reported as provenance, never a reason to keep requesting older filings.
            if candidates:
                break

        selected = None
        if candidates:
            selected = min(candidates, key=lambda item: (
                abs(item[0] - reporting_year), 0 if item[0] <= reporting_year else 1, -item[0], item[1]))
            evidence_year, period_end, filing, canonical_ids, selected_status = selected
            with self.database.transaction():
                for fact_id in canonical_ids:
                    self.database.execute('INSERT OR IGNORE INTO accounts_run_fact VALUES (?,?)', (run_id, fact_id))
                self.database.execute(
                    'INSERT INTO accounts_run_selection VALUES (?,?,?,?,?,?)',
                    (run_id, reporting_year, evidence_year, encode(period_end), filing.filing_fact_id,
                     'EXACT' if evidence_year == reporting_year else 'NEAREST'))
            emit('selection_finalized', f'Reporting-year selection persisted: requested={reporting_year}; evidence={evidence_year}; period_end={period_end.isoformat()}')
            stop = 'EXACT_REPORTING_YEAR' if evidence_year == reporting_year else 'SELECTED_FILING_ACTUAL_YEAR'
            status = ProcessingStatus.COMPLETE if selected_status == 'COMPLETE' else ProcessingStatus.PARTIAL
        else:
            stop = 'DOCUMENT_BOUND' if len(filings) > max_documents else 'M2_INPUTS_EXHAUSTED'
            status = ProcessingStatus.FAILED

        final = ProcessingRun(**(run.model_dump() | {'completed_at': datetime.now(UTC), 'status': status}))
        with self.database.transaction():
            self.database.execute('UPDATE accounts_run SET stopping_reason=? WHERE processing_run_id=?', (stop, run_id))
            runs.save_processing_run(final)
        return final
