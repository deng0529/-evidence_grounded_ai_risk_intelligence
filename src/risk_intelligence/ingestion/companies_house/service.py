"""Resource-oriented ingestion: immutable bytes first, then typed facts and coverage."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from hashlib import sha256
import json

from pydantic import ValidationError

from risk_intelligence.domain.enums import AvailabilityStatus, ExtractionMethod, ProcessingStatus, RetrievalStatus, SourceType, TriggerType
from risk_intelligence.domain.evidence import Company, Source, RawEvidence, EvidenceReference, ApiLocator
from risk_intelligence.domain.facts import StructuredFact
from risk_intelligence.domain.runs import ProcessingRun
from risk_intelligence.interfaces import EvidenceStorage
from risk_intelligence.persistence.assessment_repository import SqlAssessmentRepository
from risk_intelligence.persistence.company_repository import SqlCompanyRepository
from risk_intelligence.persistence.connection import Database, PersistenceError
from risk_intelligence.persistence.evidence_repositories import SqlSourceRepository
from risk_intelligence.persistence.ingestion_repository import Snapshot, SqlIngestionRepository
from risk_intelligence.services.evidence_persistence import EvidencePersistence
from risk_intelligence.storage.objects import checksum, object_key, verify_checksum, EvidenceIntegrityError, StorageAccessError
from .client import CompaniesHouseClient, Response, RetrievalError, ParseError, company_number, json_object
from .parsing import Observation, observations, page_items, source_date, subject_identity, text
from .policy import FreshnessPolicy, Resource, horizon_start


def identity(*parts: str) -> str:
    """Deterministic operation identity; never uses mutable values or page contents."""
    return sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def utc_now() -> datetime:
    """Boundary clock; tests inject a fixed aware clock."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class IngestionResult:
    """Terminal run and explicit per-resource completeness/reuse outcomes."""

    run: ProcessingRun
    snapshots: tuple[Snapshot, ...]


class CompaniesHouseIngestion:
    """Coordinate five independent resources; preserve successful pages on later failure."""

    def __init__(self, database: Database, storage: EvidenceStorage, client: CompaniesHouseClient,
                 policy: FreshnessPolicy | None = None, clock: Callable[[], datetime] = utc_now) -> None:
        self.database, self.storage, self.client = database, storage, client
        self.policy, self.clock = policy or FreshnessPolicy(), clock
        self.metadata = SqlIngestionRepository(database)
        self.evidence = EvidencePersistence(database, storage)
        self.companies = SqlCompanyRepository(database)
        self.runs = SqlAssessmentRepository(database)

    def _records(self, company: Company, run_id: str, resource: Resource,
                 index: int, response: Response) -> tuple[Source, RawEvidence]:
        source_id = identity(run_id, resource.value, str(index))
        digest = checksum(response.body)
        source = Source(source_id=source_id, company_id=company.company_id, company_number=company.company_number,
                        source_type=SourceType.COMPANIES_HOUSE_API, source_name="Companies House " + resource.value,
                        source_identifier=response.path, source_url="https://api.company-information.service.gov.uk" + response.path,
                        retrieved_at=response.retrieved_at, retrieval_status=RetrievalStatus.SUCCESS,
                        processing_run_id=run_id, http_status=response.status, checksum=digest)
        raw = RawEvidence(raw_evidence_id=source_id, source_id=source_id,
                          object_path=object_key(source, digest, "application/json"), checksum=digest,
                          retrieved_at=response.retrieved_at, processing_run_id=run_id, media_type="application/json")
        return source, raw

    def _bootstrap(self, number: str, run_id: str) -> tuple[Company, Response]:
        response = self.client.get("/company/" + number)
        # Company.name is not known before parsing. Publish the exact bytes under
        # the final event key first; SQL metadata follows only after identity parses.
        source = Source(source_id=identity(run_id, Resource.PROFILE.value, "0"), company_id="ch-" + number,
                        company_number=number, source_type=SourceType.COMPANIES_HOUSE_API,
                        source_name="Companies House profile", source_identifier=response.path,
                        retrieved_at=response.retrieved_at, retrieval_status=RetrievalStatus.SUCCESS,
                        processing_run_id=run_id, checksum=checksum(response.body))
        raw = RawEvidence(raw_evidence_id=source.source_id, source_id=source.source_id,
                          object_path=object_key(source, source.checksum, "application/json"), checksum=source.checksum,
                          retrieved_at=response.retrieved_at, processing_run_id=run_id, media_type="application/json")
        self.storage.put(raw, response.body)
        verify_checksum(self.storage.read(raw.object_path), raw.checksum)
        data = json_object(response)
        subject_identity(Resource.PROFILE, data, number)
        return Company(company_id="ch-" + number, company_number=number,
                       company_name=text(data.get("company_name"))), response

    def ingest(self, number: str, assessment_date: date, run_id: str) -> IngestionResult:
        """Freeze scope; reuse fresh complete snapshots or refresh independent endpoints.

        A new company requires a successful, byte-preserved profile before its
        identity can be created. A missing/nonexistent profile raises RetrievalError.
        Later resource failures are explicit partial/failed terminal results.
        """
        if self.database.in_transaction:
            raise PersistenceError("Ingestion must start outside SQL transactions")
        number = company_number(number)
        started = self.clock()
        if started.tzinfo is None or assessment_date > started.date():
            raise ValueError("Require an aware clock and a nonfuture assessment date")
        if self.runs.get_processing_run(run_id) is not None:
            raise ValueError("Use a distinct run identity; prior snapshot remains immutable")
        start = horizon_start(assessment_date)
        company = self.companies.get_by_company_number(number)
        bootstrap = None
        if company is None:
            company, bootstrap = self._bootstrap(number, run_id)
            self.companies.save(company)
        run = ProcessingRun(processing_run_id=run_id, company_id=company.company_id, company_number=number,
                            started_at=started, status=ProcessingStatus.RUNNING, current_stage="M2_INGESTION",
                            trigger_type=TriggerType.LIVE, app_version="0.1.0")
        self.runs.save_processing_run(run)
        self.metadata.save_context(run_id, assessment_date, start)
        snapshots: list[Snapshot] = []
        try:
            for resource in Resource:
                previous = self.metadata.reusable(company.company_id, resource, started, start,
                                                  assessment_date, self.policy.max_age[resource])
                if previous is not None:
                    snapshot = replace(previous, snapshot_id=identity(run_id, resource.value),
                                       processing_run_id=run_id, reused_snapshot_id=previous.snapshot_id)
                else:
                    snapshot = self._retrieve(company, run, resource, start, assessment_date,
                                              bootstrap if resource == Resource.PROFILE else None)
                self.metadata.save_snapshot(snapshot)
                snapshots.append(snapshot)
                if resource == Resource.PROFILE and not snapshot.complete:
                    break
            complete = len(snapshots) == len(Resource) and all(s.complete for s in snapshots)
            status = ProcessingStatus.COMPLETE if complete else (
                ProcessingStatus.PARTIAL if any(s.complete for s in snapshots) else ProcessingStatus.FAILED)
            run = ProcessingRun.model_validate(run.model_dump() | {
                "completed_at": self.clock(), "status": status, "current_stage": "M2_FINISHED",
                "error_code": None if complete else "INCOMPLETE_RESOURCE"})
            self.runs.save_processing_run(run)
            return IngestionResult(run, tuple(snapshots))
        except (PersistenceError, StorageAccessError, EvidenceIntegrityError, OSError):
            # Infrastructure failure may also prevent recording the terminal state.
            # Do not hide that failure, delete evidence or pretend the run completed.
            failed = ProcessingRun.model_validate(run.model_dump() | {
                "completed_at": self.clock(), "status": ProcessingStatus.FAILED,
                "current_stage": "M2_INFRASTRUCTURE_FAILURE", "error_code": "PERSISTENCE_FAILURE"})
            self.runs.save_processing_run(failed)
            raise

    def _retrieve(self, company: Company, run: ProcessingRun, resource: Resource,
                  start: date, end: date, first: Response | None) -> Snapshot:
        index, pages, count = 0, 0, 0
        total: int | None = None
        seen: set[str] = set()
        last_date: date | None = None
        path = "/company/" + company.company_number + ("" if resource == Resource.PROFILE else "/" + resource.value)
        checked = run.started_at
        try:
            while pages < self.policy.max_pages:
                parameters = None if resource == Resource.PROFILE else {"start_index": index, "items_per_page": self.policy.page_size}
                response = first if first is not None else self.client.get(path, parameters)
                first = None
                checked = response.retrieved_at
                source, raw = self._records(company, run.processing_run_id, resource, index, response)
                self.evidence.save(source, raw, response.body)
                self.metadata.save_response(source.source_id, resource, response.path, response.content_type,
                                            response.etag, index, self.policy.page_size)
                pages += 1
                data = json_object(response)
                if resource == Resource.PROFILE:
                    items, new_total = [data], 1
                else:
                    items, new_total = page_items(data, index)
                if total is not None and total != new_total:
                    raise ParseError("Population changed during pagination; refresh required")
                total = new_total
                parsed = []
                outside = False
                for offset, item in enumerate(items):
                    subject = subject_identity(resource, item, company.company_number)
                    if subject in seen:
                        raise ParseError("Duplicate resource identity across pages")
                    seen.add(subject)
                    if resource == Resource.FILINGS:
                        filed = source_date(item.get("date"))
                        if last_date is not None and filed > last_date:
                            raise ParseError("Filing order is not newest-first; completeness unproven")
                        last_date = filed
                        if filed < start:
                            outside = True
                            continue
                        if filed > end:
                            continue
                    prefix = "$" if resource == Resource.PROFILE else f"$.items[{offset}]"
                    parsed.extend(observations(resource, item, company.company_number, prefix))
                    count += 1
                self._save_observations(source, parsed)
                if resource == Resource.PROFILE:
                    self.companies.save(Company.model_validate(company.model_dump() | {
                        "company_name": text(data.get("company_name")),
                        "company_status": data.get("company_status"), "company_type": data.get("type")}))
                index += len(items)
                if outside or index >= total:
                    return Snapshot(identity(run.processing_run_id, resource.value), run.processing_run_id,
                                    company.company_id, resource, checked, start, end, True,
                                    AvailabilityStatus.AVAILABLE, pages, count)
            raise ParseError("Pagination bound reached; dataset incomplete")
        except RetrievalError as error:
            status = AvailabilityStatus.RETRIEVAL_FAILED
            code = "HTTP_" + str(error.status) if error.status else "TRANSPORT_FAILURE"
            failed_source = Source(source_id=identity(run.processing_run_id, resource.value, str(index), "failed"),
                company_id=company.company_id, company_number=company.company_number,
                source_type=SourceType.COMPANIES_HOUSE_API, source_name="Companies House " + resource.value,
                source_identifier=path + "?start_index=" + str(index), retrieved_at=self.clock(),
                retrieval_status=RetrievalStatus.FAILED, processing_run_id=run.processing_run_id, http_status=error.status)
            SqlSourceRepository(self.database).save(failed_source.source_id, failed_source)
        except (ParseError, ValidationError):
            status, code = AvailabilityStatus.EXTRACTION_FAILED, "STRUCTURAL_PARSE_FAILURE"
        return Snapshot(identity(run.processing_run_id, resource.value), run.processing_run_id, company.company_id,
                        resource, self.clock(), start, end, False, status, pages, count, error_code=code)

    def _save_observations(self, source: Source, parsed: list[Observation]) -> None:
        references: list[EvidenceReference] = []
        facts: list[StructuredFact] = []
        for observation in parsed:
            evidence_id = identity(source.source_id, observation.path)
            references.append(EvidenceReference(evidence_id=evidence_id, source_id=source.source_id,
                location=ApiLocator(endpoint=source.source_identifier, json_path=observation.path)))
            fact_id = identity(source.source_id, observation.subject, observation.concept)
            facts.append(StructuredFact(fact_id=fact_id, company_id=source.company_id, company_number=source.company_number,
                canonical_concept=observation.concept, value=observation.value, availability_status=observation.status,
                source_id=source.source_id, evidence_ids=(evidence_id,), extraction_method=ExtractionMethod.API_DIRECT,
                processing_run_id=source.processing_run_id, subject_identifier=observation.subject))
        self.metadata.save_page_facts(source.source_id, references, facts)
