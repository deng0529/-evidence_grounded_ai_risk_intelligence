"""Bounded transport failures, authentication policy and strict source JSON."""

import traceback
from base64 import b64decode

from pydantic import SecretStr

import pytest

from risk_intelligence.ingestion.companies_house.client import CompaniesHouseClient, Response, RetrievalError, ParseError, company_number, json_object
from tests.m2.conftest import NOW, NUMBER


def test_real_transport_uses_basic_auth_and_allowlisted_response_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from risk_intelligence.ingestion.companies_house import client as module
    calls = []
    class Reply:
        status = 200
        def read(self, bound: int) -> bytes:
            assert bound > 0
            return b'{ "synthetic": true }\n'
        def getheader(self, name: str, default=None):
            return {'Content-Type':'application/json','ETag':'safe-etag'}.get(name,default)
    class Connection:
        def __init__(self, host: str, timeout: float) -> None:
            assert host == module.HOST and 0 < timeout <= 60
        def request(self, method: str, path: str, headers: dict[str,str]) -> None:
            assert method == 'GET'
            assert b64decode(headers['Authorization'].split()[1]) == b'SYNTHETIC_KEY:'
            calls.append(path)
        def getresponse(self) -> Reply:
            return Reply()
        def close(self) -> None:
            pass
    monkeypatch.setattr(module,'HTTPSConnection',Connection)
    response = module.HttpTransport(SecretStr('SYNTHETIC_KEY'))('/company/'+NUMBER)
    assert response.body == b'{ "synthetic": true }\n'
    assert response.retrieved_at.utcoffset().total_seconds() == 0
    assert 'Authorization' not in repr(response) and 'SYNTHETIC_KEY' not in repr(response)
    assert calls == ['/company/'+NUMBER]


def test_retry_after_http_date_is_honored() -> None:
    replies = [Response('/synthetic',b'',429,NOW,retry_after='Tue, 29 Sep 2026 12:00:07 GMT'),
               Response('/synthetic',b'{}',200,NOW)]
    waits = []
    CompaniesHouseClient(lambda _: replies.pop(0),pause=waits.append).get('/company/'+NUMBER)
    assert waits == [7]


@pytest.mark.parametrize("statuses", [[429, 200], [500, 503, 200], [None, 200]])
def test_transient_errors_retry_with_bounded_backoff(statuses: list[int | None]) -> None:
    calls, waits = [], []
    def request(path: str) -> Response:
        code = statuses[len(calls)]
        calls.append(path)
        if code is None:
            raise OSError("SYNTHETIC secret transport error")
        return Response(path, b"{}", code, NOW, retry_after="3" if code == 429 else None)
    assert CompaniesHouseClient(request, pause=waits.append).get("/company/" + NUMBER).body == b"{}"
    assert len(calls) == len(statuses)
    assert all(0 <= delay <= 30 for delay in waits)
    if statuses[0] == 429:
        assert waits[0] == 3


@pytest.mark.parametrize("status", [401, 403, 404, 302])
def test_permanent_errors_never_retry_or_echo_response(status: int) -> None:
    calls = []
    def request(path: str) -> Response:
        calls.append(path)
        return Response(path, b"SYNTHETIC_SECRET", status, NOW)
    with pytest.raises(RetrievalError) as error:
        CompaniesHouseClient(request).get("/company/" + NUMBER)
    assert len(calls) == 1 and error.value.status == status
    assert "SYNTHETIC_SECRET" not in "".join(traceback.format_exception(error.value))


def test_exhaustion_and_excessive_retry_after_are_bounded() -> None:
    waits = []
    with pytest.raises(RetrievalError):
        CompaniesHouseClient(lambda p: Response(p, b"", 429, NOW, retry_after="300"), pause=waits.append).get("/company/" + NUMBER)
    assert waits == []
    calls = []
    def fail(path: str) -> Response:
        calls.append(path)
        raise OSError("secret")
    with pytest.raises(RetrievalError):
        CompaniesHouseClient(fail, pause=waits.append).get("/company/" + NUMBER)
    assert len(calls) == 3 and waits == [1, 2]


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}'])
def test_invalid_json_is_not_an_empty_population(body: bytes) -> None:
    with pytest.raises(ParseError):
        json_object(Response("/synthetic", body, 200, NOW))


def test_canonical_numbers_and_fixed_host_paths() -> None:
    assert company_number("8624397") == "08624397"
    assert company_number("sc137690") == "SC137690"
    for invalid in ("company name", "123456789", "../test", "１２３４５６７８"):
        with pytest.raises(ValueError):
            company_number(invalid)
    with pytest.raises(ValueError):
        CompaniesHouseClient(lambda p: None).get("https://example.invalid/")
