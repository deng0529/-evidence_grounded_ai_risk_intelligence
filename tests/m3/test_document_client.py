"""Document transport host policy and semantic routing do not require live APIs."""

from datetime import UTC, datetime
from pydantic import SecretStr
import pytest

from risk_intelligence.ingestion.accounts.client import DocumentClient, metadata_path, representations
from risk_intelligence.ingestion.companies_house.client import Response, RetrievalError


@pytest.mark.parametrize('url', ['http://document-api.company-information.service.gov.uk/document/a',
    'https://evil.invalid/document/a', '//evil.invalid/document/a', '/document/a?key=secret',
    '/document/../a', '/document/a#fragment'])
def test_untrusted_metadata_urls_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        metadata_path(url)


def test_priority_ignores_unsupported_structured_formats() -> None:
    assert representations({'resources': {'application/pdf': {}, 'application/xhtml+xml': {},
                                          'application/json': {}, 'application/zip': {}}}) == (
                                              'application/xhtml+xml', 'application/pdf')


def test_redirect_is_unsigned_and_signed_url_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DocumentClient(SecretStr('synthetic'), download_hosts=('objects.example.invalid',))
    calls = []
    def request(host: str, path: str, accept: str, authenticated: bool):
        calls.append((host, authenticated))
        status = 302 if authenticated else 200
        return Response(path, b'pdf', status, datetime.now(UTC), 'application/pdf'), (
            'https://objects.example.invalid/file?signature=synthetic' if authenticated else None)
    monkeypatch.setattr(client, '_request', request)
    response = client.get('/document/example', 'application/pdf')
    assert calls == [('document-api.company-information.service.gov.uk', True), ('objects.example.invalid', False)]
    assert response.path == '/document/example/content'
    assert 'signature' not in repr(response)


def test_redirect_to_unapproved_host_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DocumentClient(SecretStr('synthetic'))
    monkeypatch.setattr(client, '_request', lambda *args: (
        Response('/document/a', b'', 302, datetime.now(UTC)), 'https://evil.invalid/x'))
    with pytest.raises(RetrievalError):
        client.get('/document/a', 'application/pdf')
