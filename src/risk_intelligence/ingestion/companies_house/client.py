"""One authenticated transport with bounded retries and no secret-bearing errors."""

from base64 import b64encode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPSConnection, HTTPException
import json
import math
import re
from time import sleep
from typing import Protocol
from urllib.parse import urlencode

from pydantic import SecretStr

HOST = "api.company-information.service.gov.uk"


class RetrievalError(RuntimeError):
    """Safe retrieval failure; status is HTTP status or None for transport failure."""

    def __init__(self, status: int | None = None) -> None:
        self.status = status
        super().__init__(f"Companies House retrieval failed (HTTP {status})" if status else
                         "Companies House transport failed")


class ParseError(RuntimeError):
    """Source shape/type or pagination is unusable, never a valid empty dataset."""


@dataclass(frozen=True)
class Response:
    """Exact response bytes and explicitly allowlisted, non-secret metadata."""

    path: str
    body: bytes
    status: int
    retrieved_at: datetime
    content_type: str = "application/json"
    etag: str | None = None
    retry_after: str | None = None


class Transport(Protocol):
    """Injectable single HTTP request for deterministic offline tests."""

    def __call__(self, path: str) -> Response:
        """Return received bytes, without interpreting their JSON content."""
        ...


class HttpTransport:
    """TLS-only fixed-host GET; no redirects, proxy credentials or arbitrary URLs."""

    def __init__(self, api_key: SecretStr, timeout: float = 20.0) -> None:
        if not api_key.get_secret_value() or not 0 < timeout <= 60:
            raise ValueError("API key and timeout in (0,60] are required")
        self._key = api_key
        self.timeout = timeout

    def __call__(self, path: str) -> Response:
        connection = HTTPSConnection(HOST, timeout=self.timeout)
        try:
            auth = b64encode((self._key.get_secret_value() + ":").encode()).decode()
            connection.request("GET", path, headers={"Authorization": "Basic " + auth,
                               "Accept": "application/json", "Accept-Encoding": "identity"})
            reply = connection.getresponse()
            body = reply.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                raise RetrievalError()
            return Response(path, body, reply.status, datetime.now(UTC),
                            reply.getheader("Content-Type", "application/json"),
                            reply.getheader("ETag"), reply.getheader("Retry-After"))
        except (OSError, HTTPException):
            raise RetrievalError() from None
        finally:
            connection.close()


def company_number(value: str) -> str:
    """Canonicalize numeric padding/case, without guessing a company name."""
    value = value.strip().upper()
    if value.isascii() and value.isdigit():
        value = value.zfill(8)
    if not re.fullmatch(r"[A-Z0-9]{8}", value):
        raise ValueError("Expected an eight-character company number")
    return value


def json_object(response: Response) -> dict[str, object]:
    """Decode only after preservation; reject duplicate keys and invalid JSON."""
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def invalid_constant(_: str) -> object:
        raise ValueError("Non-finite JSON number")
    try:
        result = json.loads(response.body, object_pairs_hook=unique,
                            parse_constant=invalid_constant)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise ParseError("Response is not an unambiguous JSON object") from None


class CompaniesHouseClient:
    """Common bounded request policy; page interpretation is shared by orchestration."""

    def __init__(self, transport: Transport, *, attempts: int = 3,
                 pause: Callable[[float], None] = sleep, max_backoff: float = 30.0) -> None:
        if not 1 <= attempts <= 5 or not 0 <= max_backoff <= 60:
            raise ValueError("Invalid bounded retry policy")
        self.transport, self.attempts = transport, attempts
        self.pause, self.max_backoff = pause, max_backoff

    def get(self, path: str, parameters: dict[str, str | int] | None = None) -> Response:
        """GET an allowed API resource; retry transient errors only, with bounded waits."""
        if not re.fullmatch(r"/company/[A-Z0-9]{8}(?:/(?:officers|persons-with-significant-control|"
                            r"persons-with-significant-control-statements|filing-history))?|/search/companies", path):
            raise ValueError("Unsupported Companies House resource")
        if parameters:
            path += "?" + urlencode(sorted(parameters.items()))
        for attempt in range(self.attempts):
            response = None
            try:
                response = self.transport(path)
            except (RetrievalError, OSError):
                pass
            if response is not None and response.status == 200:
                return response
            status = response.status if response else None
            if status is not None and status != 429 and not 500 <= status <= 599:
                raise RetrievalError(status)
            delay = min(2 ** attempt, self.max_backoff)
            if response and response.retry_after:
                try:
                    delay = float(response.retry_after)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(response.retry_after) - response.retrieved_at).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        delay = min(2 ** attempt, self.max_backoff)
                # Do not retry earlier than the provider asks; return controlled failure
                # if that wait would exceed this synchronous request's bounded budget.
                if not math.isfinite(delay) or delay > self.max_backoff:
                    raise RetrievalError(status)
            if attempt + 1 < self.attempts:
                self.pause(max(0, delay))
        raise RetrievalError(status)
