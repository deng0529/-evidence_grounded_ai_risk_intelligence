"""Bounded accounts orchestration from M2 links to immutable financial observations."""

from datetime import UTC, date, datetime
from hashlib import sha256
import json

from risk_intelligence.domain.enums import ProcessingStatus, TriggerType, AvailabilityStatus
from risk_intelligence.domain.facts import FinancialFact
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
from .client import DocumentClient, representations
from .ixbrl import extract_ixbrl, PARSER_VERSION as IX_VERSION
from .mapping import FinancialMappingRegistry, default_registry
from .models import ExtractionResult, CONCEPTS, CandidateDecision, FallbackAudit
from .pdf import PageText, extract_pdf, pdf_pages, PARSER_VERSION as PDF_VERSION
from .processing import ProcessingCache
from .llm import OpenAIExtraction, CandidateResult, CandidateAdmissionError, PROMPT_VERSION, SCHEMA_VERSION
from .derivation import derive_debt, DERIVATION_VERSION
from .fallback import ADMISSION_VERSION, admit_candidate, select_evidence
from .asset_side import inspect_asset_side, debt_completeness_notes, PARSER_VERSION as ASSET_PARSER_VERSION
from .interpretation_workflow import interpret
from .interpretation import VERSION as INTERPRETATION_VERSION, canonical as interpretation_canonical, verify


class AccountsIngestion:
    """Acquire only M2-linked accounts; failed documents do not erase valid results."""

    def __init__(self, database: Database, storage: EvidenceStorage, client: DocumentClient,
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

    def _extract(self, raw: RawEvidence, run_id: str, number: str) -> tuple[ExtractionResult, bool]:
        if raw.media_type != 'application/pdf':
            output, reused = self.cache.run(raw, run_id, 'PARSE', IX_VERSION, {},
                lambda content: extract_ixbrl(content, raw.document_id, number).model_dump_json().encode())
            result = ExtractionResult.model_validate_json(output)
            return interpret(self.cache, raw, run_id, result, self.registry, None), reused

        def layout(content: bytes) -> bytes:
            pages = pdf_pages(content, ocr=self.tessdata is not None, tessdata=self.tessdata)
            return json.dumps([page.model_dump(mode='json') for page in pages]).encode()
        layout_bytes, _ = self.cache.run(raw, run_id, 'OCR', self.ocr_version,
                                        {'dpi': 200, 'language': 'eng', 'pymupdf': '1.28.2'}, layout)
        pages = tuple(PageText.model_validate_json(json.dumps(page)) for page in json.loads(layout_bytes))
        try:
            output, reused = self.cache.run(raw, run_id, 'PARSE', PDF_VERSION,
                {'ocr_version': self.ocr_version},
                lambda _: extract_pdf(pages, raw.document_id, number).model_dump_json().encode())
            deterministic = ExtractionResult.model_validate_json(output)
        except ParseError:
            deterministic = ExtractionResult(facts=(), periods=(), complete=False,
                                             reason='Deterministic PDF extraction unresolved')
            reused = False
        result = self._fallback(raw, run_id, number, pages, deterministic)
        if not result.facts:
            raise ParseError('No supported facts after configured extraction routes')
        def inspect_completeness(_: bytes) -> bytes:
            inspected = inspect_asset_side(pages, result)
            inspected = inspected.model_copy(update={'completeness_notes':inspected.completeness_notes
                + debt_completeness_notes(pages, inspected)})
            return inspected.model_dump_json().encode()
        completed, _ = self.cache.run(raw, run_id, 'PARSE', ASSET_PARSER_VERSION,
            {'extraction_sha':sha256(result.model_dump_json().encode()).hexdigest(),
             'asset_rule':ASSET_PARSER_VERSION, 'debt_rule':DERIVATION_VERSION}, inspect_completeness)
        return interpret(self.cache, raw, run_id, ExtractionResult.model_validate_json(completed),
                         self.registry, self.llm), reused

    def _fallback(self, raw: RawEvidence, run_id: str, number: str,
                  pages: tuple[PageText, ...], deterministic: ExtractionResult) -> ExtractionResult:
        # Check concept x period, not merely whether the parser returned any facts.
        available = set()
        for fact in deterministic.facts:
            canonical = self.registry.map(fact, company_id='coverage', company_number=number,
                                          source_id=raw.source_id, processing_run_id=run_id)
            if canonical is not None and canonical.availability_status == AvailabilityStatus.AVAILABLE:
                available.add((canonical.canonical_concept, fact.period.period_end))
        targets = tuple(concept for concept in CONCEPTS if not deterministic.periods or
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
            except ValueError:
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
                        fact = admit_candidate(candidate, selected, raw.document_id, number)
                        admitted.append(fact)
                        identity = fact.source_fact_id
                        status, reason = 'AVAILABLE', 'Excerpt, label, amount, period, unit and company scope verified'
                except (CandidateAdmissionError, ParseError) as error:
                    status, reason = 'VALIDATION_FAILED', str(error)
                decisions.append(CandidateDecision(candidate_index=index, concept=candidate.concept,
                    kind=candidate.kind, period_end=candidate.period_end, status=status, reason=reason, source_fact_id=identity))
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
        return ExtractionResult.model_validate_json(merged)

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
            for fact in result.facts:
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
                    self.repository.save_direct(canonical, fact.source_fact_id, self.registry.version)
                    output_ids.append(canonical.financial_fact_id)
                    present.add((canonical.canonical_concept, fact.period.model_dump_json()))
                    direct_by_source[fact.source_fact_id] = canonical
                else:
                    unresolved = True
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
                        output_ids.append(admitted.financial_fact_id)
                    present.add((admitted.canonical_concept,admitted.period.model_dump_json()))
                if result.interpretation_artifact_id:
                    contexts = [c for c in result.contexts if proposal.operands
                                and c.source_fact_id == proposal.operands[0].source_fact_id]
                    self.repository.save_interpretation(raw.document_id,result.interpretation_artifact_id,
                        decision,admitted.financial_fact_id if admitted else None,
                        contexts[0] if len(contexts) == 1 else None)
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
                        extraction_method=result.facts[0].extraction_method,
                        availability_status=(AvailabilityStatus.VALIDATION_FAILED if interpretation_failed or (result.fallback and any(
                            decision.concept == concept and decision.period_end == period.period_end.isoformat()
                            and decision.kind == 'DIRECT' and decision.status == 'VALIDATION_FAILED'
                            for decision in result.fallback.decisions))
                            else AvailabilityStatus.NOT_DISCLOSED if result.complete and not unresolved
                            else AvailabilityStatus.EXTRACTION_FAILED),
                        processing_run_id=source.processing_run_id)
                    self.repository.canonical.save(identity, missing)
                    output_ids.append(identity)
        return tuple(output_ids)

    def ingest(self, company_number: str, assessment_date: date, run_id: str,
               *, max_documents: int = 5) -> ProcessingRun:
        """Process up to three candidate periods within an explicit document bound.

        This entry point never performs company discovery or runs risk analytics.
        OCR and provider failures remain explicit partial/failed results.
        """
        if not 1 <= max_documents <= 10:
            raise ValueError('Document bound must be between 1 and 10')
        company = SqlCompanyRepository(self.database).get_by_company_number(company_number)
        if company is None:
            raise IntegrityError('Run M2 company ingestion before M3')
        filings = self.repository.filings(company.company_id)
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
        periods: set[date] = set()
        statuses = []
        for filing in filings[:max_documents]:
            raw = None
            reused_raw = reused_parse = False
            try:
                existing = self.repository.reusable_document(filing)
                if existing:
                    raw = self.evidence.raw.get(existing)
                    self.evidence.read(existing)
                    reused_raw = True
                    result, reused_parse = self._extract(raw, run_id, company_number)
                else:
                    metadata = self.client.get(filing.metadata_url)
                    metadata_source, _, _ = self.publication.publish(company, run_id, filing, metadata)
                    parsed_metadata = json_object(metadata)
                    expected_id = filing.metadata_url.rsplit('/', 1)[1]
                    if parsed_metadata.get('id', expected_id) != expected_id:
                        raise ParseError('Document metadata identity mismatch')
                    available = representations(parsed_metadata)
                    if not available:
                        raise ParseError('No supported document representation')
                    result = None
                    for media in available:
                        response = self.client.get(filing.metadata_url, media)
                        _, raw, _ = self.publication.publish(company, run_id, filing, response,
                                                            metadata_source_id=metadata_source.source_id)
                        try:
                            result, reused_parse = self._extract(raw, run_id, company_number)
                            break
                        except CandidateAdmissionError:
                            raise
                        except ParseError:
                            continue
                    if result is None:
                        raise ParseError('Representations could not be adequately extracted')
                def publish_canonical(_: bytes) -> bytes:
                    fact_ids = self._save_facts(raw, result)
                    return json.dumps({'mapping_version': self.registry.version,
                        'derivation_version': DERIVATION_VERSION,
                        'asset_derivation_version': ASSET_PARSER_VERSION,
                        'canonical_fact_ids': fact_ids,
                        'source_fact_ids': [fact.source_fact_id for fact in result.facts]}, sort_keys=True).encode()
                canonical_output, _ = self.cache.run(raw, run_id, 'CANONICAL', self.registry.version,
                    {'derivation': DERIVATION_VERSION, 'assets': ASSET_PARSER_VERSION, 'interpretation':INTERPRETATION_VERSION, 'output_schema': 5,
                     'source_facts_sha': sha256(result.model_dump_json().encode()).hexdigest()}, publish_canonical)
                with self.database.transaction():
                    for fact_id in json.loads(canonical_output)['canonical_fact_ids']:
                        self.database.execute('INSERT OR IGNORE INTO accounts_run_fact VALUES (?,?)', (run_id, fact_id))
                periods.update(p.period_end for p in result.periods)
                status = 'COMPLETE' if result.complete else 'PARTIAL'
                availability = 'AVAILABLE'
                reason = result.reason or 'Supported extraction completed; M4 review remains required'
            except RetrievalError:
                status, availability, reason = 'FAILED', 'RETRIEVAL_FAILED', 'Document retrieval failed'
            except CandidateAdmissionError:
                status, availability, reason = 'FAILED', 'VALIDATION_FAILED', 'LLM artifact retained; numeric candidate failed evidence admission'
            except ParseError:
                status, availability, reason = 'FAILED', 'EXTRACTION_FAILED', 'Document extraction failed or requires unsupported processing'
            statuses.append(status)
            with self.database.transaction():
                self.database.execute('INSERT INTO accounts_run_document VALUES (?,?,?,?,?,?,?,?)',
                    (run_id, filing.filing_fact_id, raw.document_id if raw else None,
                     status, availability, reason, int(reused_raw), int(reused_parse)))
            if len(periods) >= 3:
                break
        stop = 'THREE_CANDIDATE_PERIODS' if len(periods) >= 3 else (
            'DOCUMENT_BOUND' if len(filings) > max_documents else 'M2_INPUTS_EXHAUSTED')
        status = (ProcessingStatus.COMPLETE if statuses and all(s == 'COMPLETE' for s in statuses)
                  else ProcessingStatus.PARTIAL if any(s != 'FAILED' for s in statuses) else ProcessingStatus.FAILED)
        final = ProcessingRun(**(run.model_dump() | {'completed_at': datetime.now(UTC), 'status': status}))
        with self.database.transaction():
            self.database.execute('UPDATE accounts_run SET stopping_reason=? WHERE processing_run_id=?', (stop, run_id))
            runs.save_processing_run(final)
        return final
