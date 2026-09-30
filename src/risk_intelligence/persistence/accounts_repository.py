"""Relational M3 source and canonical lineage persistence; no object-storage access."""

import json

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact, CompletenessProof
from risk_intelligence.ingestion.accounts.models import FilingInput, InterpretationDecision, FinancialContext, SemanticSupport
from .connection import Database, IntegrityError, Row
from .fact_repositories import SqlFinancialFactRepository
from .mapping import date_value, decimal_value, encode, text
from .records import insert_immutable, restore


def _source_row(fact: SourceFinancialFact) -> Row:
    row = {name: encode(getattr(fact, name)) for name in type(fact).model_fields
           if name not in ('period', 'dimensions', 'statement_context')}
    row['dimensions_json'] = json.dumps(fact.dimensions, separators=(',', ':'))
    row.update({name: encode(getattr(fact.period, name)) for name in type(fact.period).model_fields})
    return row


def _source_fact(row: Row) -> SourceFinancialFact:
    fields = dict(row)
    period = ReportingPeriod(period_type=PeriodType(text(fields.pop('period_type'))),
        period_start=date_value(fields.pop('period_start')), period_end=date_value(fields.pop('period_end')),
        period_length_days=fields.pop('period_length_days'),
        comparability_status=ComparabilityStatus(text(fields.pop('comparability_status'))))
    dimensions = json.loads(text(fields.pop('dimensions_json')))
    fields['dimensions'] = tuple(tuple(pair) for pair in dimensions)
    fields['value'] = decimal_value(fields['value'])
    fields['availability_status'] = AvailabilityStatus(text(fields['availability_status']))
    fields['extraction_method'] = ExtractionMethod(text(fields['extraction_method']))
    return SourceFinancialFact(period=period, **fields)


class AccountsRepository:
    """Append-only source occurrences and component links behind typed operations."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.canonical = SqlFinancialFactRepository(database)

    def save_source(self, fact: SourceFinancialFact) -> None:
        """Persist a typed occurrence only against its same-document evidence."""
        fact = SourceFinancialFact.model_validate(fact)
        rows = self.database.query(
            'SELECT d.company_number FROM document d JOIN evidence_reference e '
            'ON e.document_id=d.document_id WHERE d.document_id=? AND e.evidence_id=?',
            (fact.document_id, fact.evidence_id))
        if rows != [{'company_number': fact.entity_identifier}]:
            raise IntegrityError('Financial source evidence/document/company mismatch')
        # Scope context is stored once, in the existing immutable PDF locator.
        # Reject a caller dropping or replacing it before persisting the source edge.
        context = self.database.query('SELECT page,section FROM evidence_reference WHERE evidence_id=?',
                                      (fact.evidence_id,))[0]
        if context['section'] != fact.statement_context or context['page'] != fact.page:
            raise IntegrityError('Financial source statement context/locator mismatch')
        with self.database.transaction():
            insert_immutable(self.database, 'financial_source_fact', 'source_fact_id', _source_row(fact))

    def get_source(self, source_fact_id: str) -> SourceFinancialFact | None:
        """Restore values and heading provenance from SQL only; old context stays absent."""
        rows = self.database.query('SELECT f.*,e.section AS statement_context FROM financial_source_fact f '
            'JOIN evidence_reference e ON e.evidence_id=f.evidence_id WHERE f.source_fact_id=?', (source_fact_id,))
        return restore(_source_fact, rows[0]) if rows else None

    def filings(self, company_id: str) -> tuple[FilingInput, ...]:
        """Resolve latest M2 filing snapshot reuse and return its accounts links."""
        snapshots = self.database.query("SELECT * FROM resource_snapshot WHERE company_id=? "
            "AND resource='filing-history' ORDER BY checked_at DESC, rowid DESC LIMIT 1", (company_id,))
        if not snapshots or not snapshots[0]['complete']:
            raise IntegrityError('M3 requires a complete M2 filing-history snapshot')
        seen: set[str] = set()
        snapshot = snapshots[0]
        while snapshot['reused_snapshot_id']:
            identity = text(snapshot['reused_snapshot_id'])
            if identity in seen:
                raise IntegrityError('Cyclic M2 snapshot lineage')
            seen.add(identity)
            snapshot = self.database.query('SELECT * FROM resource_snapshot WHERE snapshot_id=?', (identity,))[0]
        rows = self.database.query("SELECT l.fact_id,l.subject_identifier,l.value_text,d.value_date "
            "FROM fact l JOIN fact c ON c.subject_identifier=l.subject_identifier AND c.processing_run_id=l.processing_run_id "
            "JOIN fact d ON d.subject_identifier=l.subject_identifier AND d.processing_run_id=l.processing_run_id "
            "WHERE l.company_id=? AND l.processing_run_id=? AND l.canonical_concept='FILINGS_LINKS_DOCUMENT_METADATA' "
            "AND l.availability_status='AVAILABLE' AND c.canonical_concept='FILINGS_CATEGORY' AND c.value_text='accounts' "
            "AND d.canonical_concept='FILINGS_DATE' AND d.value_date IS NOT NULL ORDER BY d.value_date DESC,l.fact_id",
            (company_id, snapshot['processing_run_id']))
        return tuple(FilingInput(filing_fact_id=row['fact_id'], filing_id=row['subject_identifier'],
            metadata_url=row['value_text'], filing_date=date_value(row['value_date'])) for row in rows)

    def reusable_document(self, filing: FilingInput) -> str | None:
        """Return an existing linked raw identity; caller must verify its bytes."""
        rows = self.database.query('SELECT r.raw_evidence_id FROM accounts_document a '
            'JOIN raw_evidence r ON r.document_id=a.document_id WHERE a.filing_fact_id=? '
            'ORDER BY a.rowid DESC LIMIT 1', (filing.filing_fact_id,))
        return text(rows[0]['raw_evidence_id']) if rows else None

    def save_interpretation(self, document_id: str, artifact_id: str,
                            decision: 'InterpretationDecision', canonical_id: str | None,
                            context: FinancialContext | None = None) -> None:
        """Atomically retain admission and required accepted semantic support.

        Rejected unknown source IDs stay in the artifact, not fabricated SQL edges.
        The existing processing ledger must link that artifact to this document.
        Accepted semantic normalization requires its uniquely selected context;
        other interpretation methods retain their existing publication behavior.
        """
        from hashlib import sha256
        proposal = decision.proposal
        lineage = self.database.query('SELECT r.document_id FROM accounts_processing p '
            'JOIN raw_evidence r ON r.raw_evidence_id=p.input_raw_id WHERE p.output_raw_id=?', (artifact_id,))
        if lineage != [{'document_id':document_id}]:
            raise IntegrityError('Interpretation artifact/document lineage mismatch')
        source_id = proposal.operands[0].source_fact_id if proposal.kind == 'NORMALIZATION' and proposal.operands else None
        if source_id and self.get_source(source_id) is None:
            source_id = None
        identity = sha256((artifact_id+decision.model_dump_json()).encode()).hexdigest()
        row = {
            'interpretation_id':identity, 'document_id':document_id, 'source_fact_id':source_id,
            'canonical_fact_id':canonical_id,'artifact_raw_id':artifact_id,
            'llm_artifact_raw_id':decision.llm_artifact_id,'target_concept':proposal.target,
            'period_end':proposal.period_end.isoformat(),'method':proposal.method,'status':decision.status,
            'rule_version':proposal.version,'reason':decision.reason}
        with self.database.transaction():
            insert_immutable(self.database, 'financial_interpretation', 'interpretation_id', row)
            if decision.status == 'AVAILABLE' and proposal.method == 'LLM_SEMANTIC':
                if context is None:
                    raise IntegrityError('Accepted semantic normalization requires source context')
                self.save_semantic_support(SemanticSupport(interpretation_id=identity,
                    rationale=proposal.rationale, context=context))

    def get_semantic_support(self, interpretation_id: str) -> SemanticSupport | None:
        """Read validated contextual support from SQL only; None means not published."""
        rows = self.database.query('SELECT * FROM financial_semantic_support WHERE interpretation_id=?',
                                   (interpretation_id,))
        def decode(row: Row) -> SemanticSupport:
            return SemanticSupport(interpretation_id=row['interpretation_id'],
                schema_version=row['schema_version'], rationale=row['rationale'],
                context=FinancialContext.model_validate_json(row['context_json']))
        return restore(decode, rows[0]) if rows else None

    def save_semantic_support(self, support: SemanticSupport) -> bool:
        """Append matching accepted support, accepting exact retries and rejecting conflicts."""
        support = SemanticSupport.model_validate(support.model_dump())
        with self.database.transaction():
            rows = self.database.query('SELECT * FROM financial_interpretation WHERE interpretation_id=?',
                                       (support.interpretation_id,))
            if (not rows or rows[0]['status'] != 'AVAILABLE' or rows[0]['method'] != 'LLM_SEMANTIC'
                    or rows[0]['source_fact_id'] != support.context.source_fact_id
                    or rows[0]['target_concept'] not in support.context.compatible_concepts):
                raise IntegrityError('Semantic context does not match accepted interpretation')
            source = self.get_source(support.context.source_fact_id)
            if source is None or source.document_id != rows[0]['document_id']:
                raise IntegrityError('Semantic support source/document mismatch')
            return insert_immutable(self.database, 'financial_semantic_support', 'interpretation_id', {
                'interpretation_id':support.interpretation_id, 'schema_version':support.schema_version,
                'rationale':support.rationale, 'context_json':support.context.model_dump_json()})

    def save_direct(self, fact: FinancialFact, source_fact_id: str, mapping_version: str) -> None:
        """Publish direct canonical observation and immutable source edge atomically."""
        source = self.get_source(source_fact_id)
        if (source is None or source.document_id != fact.document_id
                or source.entity_identifier != fact.company_number
                or fact.evidence_ids != (source.evidence_id,) or source.period != fact.period
                or source.currency != fact.currency or source.unit != fact.unit):
            raise IntegrityError('Canonical/source financial context mismatch')
        with self.database.transaction():
            self.canonical.save(fact.financial_fact_id, fact)
            inserted = insert_immutable(self.database, 'financial_observation_lineage', 'fact_id', {
                'fact_id': fact.financial_fact_id, 'origin': 'DIRECT', 'mapping_version': mapping_version,
                'derivation_version': None, 'derivation_rule': None})
            if inserted:
                self.database.execute('INSERT INTO financial_observation_component VALUES (?,?,?)',
                                      (fact.financial_fact_id, source_fact_id, 0))
            elif self.database.query('SELECT source_fact_id FROM financial_observation_component WHERE fact_id=?',
                                     (fact.financial_fact_id,)) != [{'source_fact_id': source_fact_id}]:
                raise IntegrityError('Immutable canonical source link differs')

    def save_derived(self, fact: FinancialFact, component_ids: tuple[str, ...],
                     mapping_version: str, derivation_version: str, rule: str,
                     supporting_evidence_ids: tuple[str, ...] = ()) -> None:
        """Atomically retain an exact derived fact, formula and ordered source edges."""
        components = [self.get_source(identity) for identity in component_ids]
        if not components or any(source is None or source.document_id != fact.document_id
                or source.entity_identifier != fact.company_number or source.period != fact.period
                for source in components):
            raise IntegrityError('Invalid derived component lineage')
        if fact.evidence_ids != tuple(source.evidence_id for source in components) + supporting_evidence_ids:
            raise IntegrityError('Derived evidence differs from component evidence')
        for evidence_id in supporting_evidence_ids:
            rows = self.database.query('SELECT document_id,source_id FROM evidence_reference WHERE evidence_id=?', (evidence_id,))
            if rows != [{'document_id':fact.document_id,'source_id':fact.source_id}]:
                raise IntegrityError('Derived completeness evidence differs from source document')
        with self.database.transaction():
            self.canonical.save(fact.financial_fact_id, fact)
            inserted = insert_immutable(self.database, 'financial_observation_lineage', 'fact_id', {
                'fact_id': fact.financial_fact_id, 'origin': 'DERIVED', 'mapping_version': mapping_version,
                'derivation_version': derivation_version, 'derivation_rule': rule})
            if inserted:
                for position, identity in enumerate(component_ids):
                    self.database.execute('INSERT INTO financial_observation_component VALUES (?,?,?)',
                                          (fact.financial_fact_id, identity, position))
            elif self.database.query('SELECT source_fact_id FROM financial_observation_component '
                    'WHERE fact_id=? ORDER BY position', (fact.financial_fact_id,)) != [
                        {'source_fact_id': identity} for identity in component_ids]:
                raise IntegrityError('Immutable derived component links differ')

    def get_observation_lineage(
            self, fact_id: str
    ) -> tuple[dict[str, object], tuple[SourceFinancialFact, ...]] | None:
        """Restore canonical lineage and ordered source components from SQL only."""
        rows = self.database.query(
            'SELECT origin,mapping_version,derivation_version,derivation_rule '
            'FROM financial_observation_lineage WHERE fact_id=?',
            (fact_id,))
        if not rows:
            return None
        if len(rows) != 1:
            raise IntegrityError('Multiple lineage rows for canonical fact')

        component_rows = self.database.query(
            'SELECT source_fact_id FROM financial_observation_component '
            'WHERE fact_id=? ORDER BY position',
            (fact_id,))
        components = tuple(
            self.get_source(text(row['source_fact_id']))
            for row in component_rows)
        if any(component is None for component in components):
            raise IntegrityError('Canonical lineage references missing source fact')

        return rows[0], components

    def get_derivation_proof(self, fact_id: str) -> CompletenessProof | None:
        """Restore completeness proof and ordered cross-check edges from SQL only."""
        rows = self.database.query(
            'SELECT * FROM financial_derivation_proof WHERE fact_id=?',
            (fact_id,))
        if not rows:
            return None
        if len(rows) != 1:
            raise IntegrityError('Multiple derivation proofs for canonical fact')

        row = rows[0]
        components = self.database.query(
            'SELECT source_fact_id FROM financial_observation_component '
            'WHERE fact_id=? ORDER BY position',
            (fact_id,))
        checks = self.database.query(
            'SELECT source_fact_id FROM financial_derivation_cross_check '
            'WHERE fact_id=? ORDER BY position',
            (fact_id,))

        return CompletenessProof(
            proof_id=text(row['proof_id']),
            target=text(row['target_concept']),
            source_fact_ids=tuple(
                text(item['source_fact_id']) for item in components),
            document_id=text(row['document_id']),
            page=row['page'],
            row_start=row['row_start'],
            row_end=row['row_end'],
            evidence_text=text(row['evidence_text']),
            relationship=text(row['relationship']),
            cross_check_ids=tuple(
                text(item['source_fact_id']) for item in checks),
        )

    def save_derivation_proof(self, fact: FinancialFact, proof: CompletenessProof) -> None:
        """Publish completeness semantics and independent cross-check edges to SQL."""
        proof = CompletenessProof.model_validate(proof)

        lineage = self.database.query(
            'SELECT origin FROM financial_observation_lineage WHERE fact_id=?',
            (fact.financial_fact_id,))
        if lineage != [{'origin': 'DERIVED'}] or proof.document_id != fact.document_id:
            raise IntegrityError('Derivation proof does not match derived fact')

        expected = {
            'TOTAL_ASSETS': 'ASSET_SIDE',
            'INTEREST_BEARING_DEBT': 'EXHAUSTIVE_INTEREST_BEARING',
        }.get(fact.canonical_concept)

        if (expected is None
                or proof.target != fact.canonical_concept
                or proof.relationship != expected):
            raise IntegrityError('Derivation proof target/relationship mismatch')

        components = self.database.query(
            'SELECT source_fact_id FROM financial_observation_component '
            'WHERE fact_id=? ORDER BY position',
            (fact.financial_fact_id,))
        if components != [
                {'source_fact_id': identity}
                for identity in proof.source_fact_ids]:
            raise IntegrityError(
                'Derivation proof population differs from persisted components')

        evidence = self.database.query(
            'SELECT document_id,source_id FROM evidence_reference '
            'WHERE evidence_id=?',
            (proof.proof_id,))
        if evidence != [{
                'document_id': fact.document_id,
                'source_id': fact.source_id,
        }]:
            raise IntegrityError(
                'Derivation proof evidence differs from source document')

        checks = [
            self.get_source(identity)
            for identity in proof.cross_check_ids
        ]
        if any(
                source is None
                or source.document_id != fact.document_id
                or source.entity_identifier != fact.company_number
                for source in checks):
            raise IntegrityError(
                'Derivation cross-check source/document/company mismatch')

        with self.database.transaction():
            inserted = insert_immutable(
                self.database,
                'financial_derivation_proof',
                'fact_id',
                {
                    'fact_id': fact.financial_fact_id,
                    'proof_id': proof.proof_id,
                    'document_id': proof.document_id,
                    'target_concept': proof.target,
                    'relationship': proof.relationship,
                    'page': proof.page,
                    'row_start': proof.row_start,
                    'row_end': proof.row_end,
                    'evidence_text': proof.evidence_text,
                })

            expected_rows = [
                {'source_fact_id': identity}
                for identity in proof.cross_check_ids
            ]

            if inserted:
                for position, identity in enumerate(proof.cross_check_ids):
                    self.database.execute(
                        'INSERT INTO financial_derivation_cross_check '
                        'VALUES (?,?,?)',
                        (fact.financial_fact_id, identity, position))
            elif self.database.query(
                    'SELECT source_fact_id '
                    'FROM financial_derivation_cross_check '
                    'WHERE fact_id=? ORDER BY position',
                    (fact.financial_fact_id,)) != expected_rows:
                raise IntegrityError(
                    'Immutable derivation cross-check links differ')
