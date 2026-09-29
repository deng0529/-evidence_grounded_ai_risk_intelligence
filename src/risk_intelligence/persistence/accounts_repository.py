"""Relational M3 source and canonical lineage persistence; no object-storage access."""

import json

from risk_intelligence.domain.enums import AvailabilityStatus, ComparabilityStatus, ExtractionMethod, PeriodType
from risk_intelligence.domain.facts import FinancialFact, ReportingPeriod
from risk_intelligence.ingestion.accounts.models import SourceFinancialFact
from risk_intelligence.ingestion.accounts.models import FilingInput, InterpretationDecision
from .connection import Database, IntegrityError, Row
from .fact_repositories import SqlFinancialFactRepository
from .mapping import date_value, decimal_value, encode, text
from .records import insert_immutable, restore


def _source_row(fact: SourceFinancialFact) -> Row:
    row = {name: encode(getattr(fact, name)) for name in type(fact).model_fields
           if name not in ('period', 'dimensions')}
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
        with self.database.transaction():
            insert_immutable(self.database, 'financial_source_fact', 'source_fact_id', _source_row(fact))

    def get_source(self, source_fact_id: str) -> SourceFinancialFact | None:
        """Restore exact source financial values and context, or return None."""
        rows = self.database.query('SELECT * FROM financial_source_fact WHERE source_fact_id=?', (source_fact_id,))
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
                            decision: 'InterpretationDecision', canonical_id: str | None) -> None:
        """Retain queryable immutable admission with the full R2 proposal artifact.

        Rejected unknown source IDs stay in the artifact, not fabricated SQL edges.
        The existing processing ledger must link that artifact to this document.
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
        insert_immutable(self.database, 'financial_interpretation', 'interpretation_id', {
            'interpretation_id':identity, 'document_id':document_id, 'source_fact_id':source_id,
            'canonical_fact_id':canonical_id,'artifact_raw_id':artifact_id,
            'llm_artifact_raw_id':decision.llm_artifact_id,'target_concept':proposal.target,
            'period_end':proposal.period_end.isoformat(),'method':proposal.method,'status':decision.status,
            'rule_version':proposal.version,'reason':decision.reason})

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
