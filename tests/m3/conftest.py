"""M3 uses synthetic accounts and prohibits network in normal tests."""

import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError('M3 unit tests must not access network')
    monkeypatch.setattr(socket.socket, 'connect', reject)
    monkeypatch.setattr(socket, 'create_connection', reject)


@pytest.fixture
def ixbrl() -> bytes:
    return b'''<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:x="http://www.xbrl.org/2003/instance"
      xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:test="urn:synthetic:accounts:v1">
      <x:context id="current"><x:entity><x:identifier scheme="urn:synthetic:company">ZZ000003</x:identifier></x:entity>
        <x:period><x:instant>2025-12-31</x:instant></x:period></x:context>
      <x:context id="comparative"><x:entity><x:identifier scheme="urn:synthetic:company">ZZ000003</x:identifier></x:entity>
        <x:period><x:instant>2024-12-31</x:instant></x:period></x:context>
      <x:unit id="gbp"><x:measure>iso:GBP</x:measure></x:unit>
      <ix:nonFraction name="test:NetAssets" contextRef="current" unitRef="gbp" decimals="0" sign="-" scale="3">123.40</ix:nonFraction>
      <ix:nonFraction name="test:NetAssets" contextRef="comparative" unitRef="gbp" decimals="0">200000</ix:nonFraction>
      <ix:nonFraction name="test:Stocks" contextRef="current" unitRef="gbp">0</ix:nonFraction>
      <ix:nonFraction name="test:TotalAssetsLessCurrentLiabilities" contextRef="current" unitRef="gbp">99</ix:nonFraction>
    </html>'''
