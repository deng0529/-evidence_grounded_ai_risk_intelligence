"""Synthetic M8 fixtures; outbound network remains prohibited."""

import socket

import pytest

from tests.m2.conftest import api, database, storage  # noqa: F401
from tests.m3.conftest import ixbrl  # noqa: F401
from tests.m7.test_explanation import assessed  # noqa: F401

_SOCKET_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Permit Windows asyncio's loopback socketpair used by AppTest, not external IO."""
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return _SOCKET_CONNECT(sock, address)
        raise AssertionError('M8 tests must not access external services')
    def reject(*args, **kwargs):
        raise AssertionError('M8 tests must not access external services')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket, 'create_connection', reject)
