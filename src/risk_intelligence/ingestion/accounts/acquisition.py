"""Document publication through the existing M1 cross-store coordinator."""

from uuid import uuid4

from risk_intelligence.domain.enums import RetrievalStatus, SourceType
from risk_intelligence.domain.evidence import Company, Document, RawEvidence, Source
from risk_intelligence.ingestion.companies_house.client import Response
from risk_intelligence.persistence.connection import Database, IntegrityError
from risk_intelligence.persistence.records import insert_immutable
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.objects import checksum, object_key
from .client import HOST, MEDIA_PRIORITY, metadata_path
from .models import FilingInput


class AccountsPublication:
    """Publish exact metadata/document bytes before interpreting financial content."""

    def __init__(self, database: Database, evidence: EvidencePersistence) -> None:
        self.database, self.evidence = database, evidence

    def verify_handoff(self, company: Company, filing: FilingInput) -> None:
        """Require the exact existing M2 link and account category for this company."""
        rows = self.database.query(
            "SELECT f.value_text, f.subject_identifier FROM fact f WHERE fact_id=? "
            "AND company_id=? AND canonical_concept='FILINGS_LINKS_DOCUMENT_METADATA' "
            "AND availability_status='AVAILABLE'", (filing.filing_fact_id, company.company_id))
        if len(rows) != 1 or rows[0]['value_text'] != filing.metadata_url or rows[0]['subject_identifier'] != filing.filing_id:
            raise IntegrityError('M3 requires an existing M2 document link')
        categories = self.database.query(
            "SELECT value_text FROM fact WHERE company_id=? AND subject_identifier=? "
            "AND canonical_concept='FILINGS_CATEGORY' AND availability_status='AVAILABLE'",
            (company.company_id, filing.filing_id))
        if not categories or any(row['value_text'] != 'accounts' for row in categories):
            raise IntegrityError('M3 handoff is not an accounts filing')
        metadata_path(filing.metadata_url)

    def publish(self, company: Company, run_id: str, filing: FilingInput, response: Response,
                *, metadata_source_id: str | None = None) -> tuple[Source, RawEvidence, Document | None]:
        """Return published lineage; never parse bytes or create financial facts."""
        self.verify_handoff(company, filing)
        path = metadata_path(filing.metadata_url)
        document_response = metadata_source_id is not None
        if response.status != 200:
            raise IntegrityError('Only successful responses can publish raw evidence')
        if document_response:
            rows = self.database.query(
                'SELECT s.company_id,s.source_url FROM source s JOIN raw_evidence r USING(source_id) WHERE s.source_id=?',
                (metadata_source_id,))
            if rows != [{'company_id': company.company_id, 'source_url': 'https://' + HOST + path}]:
                raise IntegrityError('Metadata evidence must be published for the same company')
        identity = uuid4().hex
        media = response.content_type
        if media not in (MEDIA_PRIORITY if document_response else ('application/json',)):
            raise IntegrityError('Response media type does not match supported document role')
        source_type = (SourceType.COMPANIES_HOUSE_PDF if media == 'application/pdf' else
                       SourceType.COMPANIES_HOUSE_IXBRL if document_response else SourceType.COMPANIES_HOUSE_API)
        source = Source(source_id='s-' + identity, company_id=company.company_id,
            company_number=company.company_number, source_type=source_type,
            source_name='Companies House accounts document' if document_response else 'Companies House document metadata',
            source_url='https://' + HOST + path + ('/content' if document_response else ''),
            retrieved_at=response.retrieved_at, retrieval_status=RetrievalStatus.SUCCESS,
            processing_run_id=run_id, http_status=200, checksum=checksum(response.body))
        key = object_key(source, source.checksum, media)
        document = Document(document_id='d-' + identity, company_id=company.company_id,
            company_number=company.company_number, source_id=source.source_id, document_type='ACCOUNTS',
            representation_type=media, filing_id=filing.filing_id, filing_date=filing.filing_date,
            object_path=key, checksum=source.checksum) if document_response else None
        raw = RawEvidence(raw_evidence_id='r-' + identity, source_id=source.source_id,
            document_id=document.document_id if document else None, object_path=key,
            checksum=source.checksum, retrieved_at=source.retrieved_at, processing_run_id=run_id, media_type=media)
        self.evidence.save(source, raw, response.body, document)
        if document:
            with self.database.transaction():
                insert_immutable(self.database, 'accounts_document', 'document_id', {
                    'document_id': document.document_id, 'filing_fact_id': filing.filing_fact_id,
                    'metadata_source_id': metadata_source_id, 'remote_document_id': path.rsplit('/', 1)[1],
                    'media_type': media, 'selection_reason': 'Supported candidate; semantic verification follows publication'})
        return source, raw, document
