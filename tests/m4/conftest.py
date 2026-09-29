"""Framework tests are offline and use only explicit synthetic inputs."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any attempted network activity, including model or object-store calls."""
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError('M4 framework tests must not access the network')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
