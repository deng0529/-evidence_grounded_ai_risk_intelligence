"""Synthetic M2 fixtures; every ordinary M2 test forbids outbound network."""

from collections.abc import Iterator
from datetime import UTC, datetime
import json
from pathlib import Path
import socket
from urllib.parse import urlsplit, parse_qs

import pytest

from risk_intelligence.ingestion.companies_house.client import Response
from risk_intelligence.persistence.connection import Database, open_sqlite
from risk_intelligence.persistence.migrations import migrate
from risk_intelligence.storage.local import LocalStorage

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
NUMBER = "ZZ000002"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("Normal M2 tests must not access network")
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with open_sqlite(tmp_path / "m2.sqlite3") as database:
        migrate(database, applied_at=NOW)
        yield database


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "raw")


class FakeAPI:
    """Pagination-aware provider with configurable resources and exact wire bytes."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[str, int] = {}
        self.payloads: dict[str, object] = {
            "profile": {"company_number": NUMBER, "company_name": "SYNTHETIC M2 COMPANY",
                        "company_status": "active", "type": "ltd", "date_of_creation": "2010-01-01",
                        "accounts": {"next_accounts": {"due_on": "2027-09-30", "overdue": False}}},
            "officers": [
                {"name": "SYNTHETIC A", "officer_role": "director", "appointed_on": "2015-01-01",
                 "links": {"self": "/synthetic/appointment-a"}},
                {"name": "SYNTHETIC A", "officer_role": "secretary", "appointed_on": "2024-01-01",
                 "resigned_on": "2025-02-01", "links": {"self": "/synthetic/appointment-b"}}],
            "persons-with-significant-control": [
                {"kind": "individual-person-with-significant-control", "name": "SYNTHETIC PSC",
                 "notified_on": "2016-04-06", "natures_of_control": ["ownership-of-shares-25-to-50-percent"],
                 "links": {"self": "/synthetic/psc-a"}}],
            "persons-with-significant-control-statements": [],
            "filing-history": [
                {"transaction_id": "filing-a", "date": "2026-09-29", "category": "accounts", "type": "AA",
                 "description": "accounts-with-accounts-type-small", "links": {"document_metadata": "https://example.invalid/doc"}},
                {"transaction_id": "filing-b", "date": "2023-09-29", "category": "capital", "type": "SH01"},
                {"transaction_id": "filing-c", "date": "2023-09-28", "category": "officers", "type": "AP01"},
                {"transaction_id": "filing-d", "date": "2010-01-01", "category": "incorporation", "type": "NEWINC"}],
        }
        self.now = NOW

    def __call__(self, path: str) -> Response:
        self.calls.append(path)
        parsed = urlsplit(path)
        name = parsed.path.split("/")[-1]
        name = "profile" if name == NUMBER else name
        params = parse_qs(parsed.query)
        index = int(params.get("start_index", ["0"])[0])
        size = int(params.get("items_per_page", ["100"])[0])
        status = self.failures.get(name + ":" + str(index), 200)
        payload = self.payloads[name]
        if name != "profile":
            payload = {"items": payload[index:index+size], "start_index": index,
                       "items_per_page": size, "total_results": len(payload)}
        body = (json.dumps(payload, indent=2) + "\n").encode()
        return Response(path, body, status, self.now, etag="synthetic-etag")


@pytest.fixture
def api() -> FakeAPI:
    return FakeAPI()
