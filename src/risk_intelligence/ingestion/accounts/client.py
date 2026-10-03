"""Bounded Document API transport with explicit redirect credential separation."""

from base64 import b64encode
from collections.abc import Callable
from datetime import UTC, datetime
from http.client import HTTPSConnection, HTTPException
import re
from time import sleep
from urllib.parse import urlsplit

from pydantic import SecretStr

from risk_intelligence.ingestion.companies_house.client import Response, RetrievalError, ParseError

HOST = "document-api.company-information.service.gov.uk"
MEDIA_PRIORITY = ("application/xhtml+xml", "application/xml", "text/xml", "application/pdf")


def metadata_path(url: str) -> str:
    """Accept only credential-free provider document metadata URLs/paths."""
    parsed = urlsplit(url)
    if parsed.scheme and (parsed.scheme != "https" or parsed.hostname != HOST):
        raise ValueError("Unsupported document metadata host")
    if parsed.netloc and not parsed.scheme:
        raise ValueError("Scheme-relative document URL is forbidden")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ValueError("Document metadata URL contains unsupported components")
    if not re.fullmatch(r"/document/[A-Za-z0-9_-]{1,200}", parsed.path):
        raise ValueError("Invalid document metadata path")
    return parsed.path


def representations(metadata: dict[str, object]) -> tuple[str, ...]:
    """Order supported candidates; extraction still verifies their actual semantics."""
    resources = metadata.get("resources")
    if not isinstance(resources, dict) or not resources:
        raise ParseError("Document metadata lacks representations")
    if not all(isinstance(k, str) and isinstance(v, dict) for k, v in resources.items()):
        raise ParseError("Malformed representation metadata")
    return tuple(media for media in MEDIA_PRIORITY if media in resources)


class DocumentRetrievalError(RetrievalError):
    """Fixed diagnostic vocabulary; never retains remote strings or URLs."""

    def __init__(self, status: int | None = None, *, stage: str, code: str) -> None:
        stages = {'METADATA', 'CONTENT', 'DOWNLOAD'}
        codes = {'HTTP_STATUS', 'BODY_TOO_LARGE', 'TRANSPORT_TIMEOUT',
                 'TRANSPORT_OS_ERROR', 'TRANSPORT_HTTP_ERROR',
                 'REDIRECT_LOCATION_MISSING', 'REDIRECT_URL_INVALID',
                 'REDIRECT_HOST_REJECTED', 'REDIRECT_COMPONENT_REJECTED'}
        self.stage = stage if stage in stages else 'UNKNOWN'
        self.code = code if code in codes else 'UNKNOWN'
        super().__init__(status if type(status) is int and 100 <= status <= 599 else None)
        self.safe_reason = (f'Document retrieval failed; stage={self.stage}; '
                            f'code={self.code}; http={self.status if self.status is not None else "NONE"}')
        self.args = (self.safe_reason,)


class DocumentClient:
    """Fixed-host authenticated requests; one bounded unsigned object redirect.

    Download host allowlisting is explicit configuration, never inferred from an
    untrusted filing link. Signed redirect URLs are transient and never returned
    in response metadata, exceptions or persistence.
    """

    def __init__(self, api_key: SecretStr, *, download_hosts: tuple[str, ...] = (),
                 timeout: float = 20, max_bytes: int = 32 * 1024 * 1024,
                 attempts: int = 2, pause: Callable[[float], None] = sleep) -> None:
        if not api_key.get_secret_value() or not 0 < timeout <= 60 or not 1 <= attempts <= 3:
            raise ValueError("Invalid document client configuration")
        if not 1 <= max_bytes <= 64 * 1024 * 1024:
            raise ValueError("Invalid document size bound")
        if any(not re.fullmatch(r"[a-z0-9.-]+", host) for host in download_hosts):
            raise ValueError("Download allowlist must contain exact lowercase hostnames")
        self._key = api_key
        self.download_hosts = download_hosts
        self.timeout, self.max_bytes, self.attempts, self.pause = timeout, max_bytes, attempts, pause

    def _request(self, host: str, path: str, accept: str, authenticated: bool) -> tuple[Response, str | None]:
        stage = "DOWNLOAD" if not authenticated else ("METADATA" if accept == "application/json" else "CONTENT")
        connection = HTTPSConnection(host, timeout=self.timeout)
        try:
            headers = {"Accept": accept, "Accept-Encoding": "identity"}
            if authenticated:
                headers["Authorization"] = "Basic " + b64encode((self._key.get_secret_value() + ":").encode()).decode()
            connection.request("GET", path, headers=headers)
            reply = connection.getresponse()
            body = reply.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise DocumentRetrievalError(reply.status, stage=stage, code="BODY_TOO_LARGE")
            # Never return a signed path as durable metadata.
            return Response("/document", body, reply.status, datetime.now(UTC),
                            reply.getheader("Content-Type", accept).split(";")[0].strip(),
                            reply.getheader("ETag"), reply.getheader("Retry-After")), reply.getheader("Location")
        except TimeoutError:
            raise DocumentRetrievalError(stage=stage, code="TRANSPORT_TIMEOUT") from None
        except OSError:
            raise DocumentRetrievalError(stage=stage, code="TRANSPORT_OS_ERROR") from None
        except HTTPException:
            raise DocumentRetrievalError(stage=stage, code="TRANSPORT_HTTP_ERROR") from None
        finally:
            connection.close()

    def get(self, url: str, media_type: str = "application/json") -> Response:
        """Fetch metadata or content; errors omit URLs, response bodies and secrets."""
        path = metadata_path(url)
        if media_type != "application/json":
            if media_type not in MEDIA_PRIORITY:
                raise ValueError("Unsupported document representation")
            path += "/content"
        last_error = None
        stage = "METADATA" if media_type == "application/json" else "CONTENT"
        for attempt in range(self.attempts):
            stage = "METADATA" if media_type == "application/json" else "CONTENT"
            try:
                response, location = self._request(HOST, path, media_type, True)
                if response.status == 302 and media_type != "application/json":
                    if not location:
                        raise DocumentRetrievalError(302, stage="CONTENT", code="REDIRECT_LOCATION_MISSING")
                    try:
                        parsed = urlsplit(location)
                        port = parsed.port
                    except ValueError:
                        raise DocumentRetrievalError(302, stage="CONTENT", code="REDIRECT_URL_INVALID") from None
                    if parsed.scheme != "https":
                        raise DocumentRetrievalError(302, stage="CONTENT", code="REDIRECT_URL_INVALID")
                    if parsed.hostname not in self.download_hosts:
                        raise DocumentRetrievalError(302, stage="CONTENT", code="REDIRECT_HOST_REJECTED")
                    if parsed.username or parsed.password or port or parsed.fragment:
                        raise DocumentRetrievalError(302, stage="CONTENT", code="REDIRECT_COMPONENT_REJECTED")
                    target = parsed.path + ("?" + parsed.query if parsed.query else "")
                    response, _ = self._request(parsed.hostname, target, media_type, False)
                    stage = "DOWNLOAD"
                if response.status == 200:
                    return Response(path, response.body, response.status, response.retrieved_at,
                                    response.content_type, response.etag)
                # Retry-After cannot be ignored: leave retry to a deliberate later run.
                if response.retry_after or response.status not in (500, 502, 503, 504):
                    raise DocumentRetrievalError(response.status, stage=stage, code="HTTP_STATUS")
                status = response.status
                last_error = DocumentRetrievalError(status, stage=stage, code="HTTP_STATUS")
            except RetrievalError as error:
                last_error = error
                if error.status is not None:
                    raise
                status = None
            if attempt + 1 < self.attempts:
                self.pause(1)
        raise last_error if last_error is not None else DocumentRetrievalError(status, stage=stage, code="HTTP_STATUS")
