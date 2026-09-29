"""Explicit company-name candidate selection with preserved search evidence."""

from dataclasses import dataclass
from datetime import UTC

from risk_intelligence.domain.evidence import RawEvidence
from risk_intelligence.interfaces import EvidenceStorage
from risk_intelligence.persistence.connection import Database, PersistenceError
from risk_intelligence.persistence.ingestion_repository import SqlIngestionRepository
from risk_intelligence.storage.objects import checksum, verify_checksum
from .client import CompaniesHouseClient, ParseError, company_number, json_object
from .parsing import page_items, text
from .service import identity


@dataclass(frozen=True)
class Candidate:
    """Source-supplied identity; selection never matches by name alone."""

    company_number: str
    company_name: str


@dataclass(frozen=True)
class SearchResult:
    """One explicit search page, not an assertion of exhaustive candidate coverage."""

    search_id: str
    candidates: tuple[Candidate, ...]
    start_index: int
    total_results: int

    def select(self, number: str | None = None) -> Candidate:
        """Require selection for multiple candidates; reject an absent candidate."""
        if number is None and len(self.candidates) == 1:
            return self.candidates[0]
        selected = company_number(number) if number is not None else None
        matches = [candidate for candidate in self.candidates if candidate.company_number == selected]
        if len(matches) != 1:
            raise ValueError("Explicit selection of a returned company candidate is required")
        return matches[0]


def search_companies(database: Database, storage: EvidenceStorage, client: CompaniesHouseClient,
                     name: str, search_id: str, *, start_index: int = 0, page_size: int = 20) -> SearchResult:
    """Preserve a search page before parsing; caller can request subsequent candidate pages.

    Search cannot have a company FK before selection. A dedicated relational
    evidence record owns the verified immutable bytes, without invented companies.
    Selected numbers still require profile validation through ingest().
    """
    if database.in_transaction:
        raise PersistenceError("Search must start outside a SQL transaction")
    if not name.strip() or not 0 <= start_index or not 1 <= page_size <= 100:
        raise ValueError("Invalid search page")
    response = client.get("/search/companies", {"q": name, "start_index": start_index, "items_per_page": page_size})
    event = identity(search_id, str(start_index))
    digest = checksum(response.body)
    stamp = response.retrieved_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    stamp = stamp.replace("-", "").replace(":", "").replace(".", "")
    key = f"raw/v1/company-search/{stamp}/{event}/{digest}.json"
    raw = RawEvidence(raw_evidence_id=event, source_id=event, object_path=key, checksum=digest,
                      retrieved_at=response.retrieved_at, processing_run_id=search_id, media_type="application/json")
    storage.put(raw, response.body)
    verify_checksum(storage.read(key), digest)
    SqlIngestionRepository(database).save_search(event, response.path, response.retrieved_at,
                                               key, digest, response.content_type, response.etag)
    items, total = page_items(json_object(response), start_index)
    candidates = tuple(Candidate(company_number(text(item.get("company_number"))), text(item.get("title")))
                       for item in items)
    if len({candidate.company_number for candidate in candidates}) != len(candidates):
        raise ParseError("Search page contains duplicate companies")
    return SearchResult(event, candidates, start_index, total)
