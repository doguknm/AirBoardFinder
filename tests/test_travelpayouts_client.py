from __future__ import annotations

import httpx
import pytest

from bot.travelpayouts_client import TRAVELPAYOUTS_URL, fetch_price


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self._json = json_body
        self.status_code = status_code
        self.text = str(json_body)
        self.request = httpx.Request("GET", TRAVELPAYOUTS_URL)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


def _make_client_class(response, capture=None):
    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None, params=None):
            if capture is not None:
                capture["headers"] = headers or {}
                capture["params"] = params or {}
            return response

    return _Client


async def test_fetch_price_success(monkeypatch):
    body = {"data": {"ANK": {"0": {"price": 120.0, "airline": "TK"}}}}
    resp = _FakeResponse(200, body)
    monkeypatch.setattr("bot.travelpayouts_client.httpx.AsyncClient", _make_client_class(resp))

    result = await fetch_price("IST", "ANK", "2026-06-01", "token123")

    assert result is not None
    assert result["price"] == 120.0
    assert result["currency"] == "EUR"
    assert result["airline"] == "TK"
    assert "aviasales.com" in result["booking_url"]


async def test_fetch_price_picks_cheapest(monkeypatch):
    body = {
        "data": {
            "ANK": {
                "0": {"price": 200.0, "airline": "PC"},
                "1": {"price": 150.0, "airline": "TK"},
            }
        }
    }
    resp = _FakeResponse(200, body)
    monkeypatch.setattr("bot.travelpayouts_client.httpx.AsyncClient", _make_client_class(resp))

    result = await fetch_price("IST", "ANK", "2026-06-01", "token123")

    assert result["price"] == 150.0
    assert result["airline"] == "TK"


async def test_fetch_price_no_data_returns_none(monkeypatch, caplog):
    resp = _FakeResponse(200, {"data": {}})
    monkeypatch.setattr("bot.travelpayouts_client.httpx.AsyncClient", _make_client_class(resp))

    with caplog.at_level("WARNING", logger="bot.travelpayouts_client"):
        result = await fetch_price("IST", "ANK", "2026-06-01", "token123")

    assert result is None
    assert "no data" in caplog.text


async def test_fetch_price_http_error_returns_none(monkeypatch, caplog):
    resp = _FakeResponse(500, {})
    monkeypatch.setattr("bot.travelpayouts_client.httpx.AsyncClient", _make_client_class(resp))

    with caplog.at_level("ERROR", logger="bot.travelpayouts_client"):
        result = await fetch_price("IST", "ANK", "2026-06-01", "token123")

    assert result is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


async def test_token_in_header_not_url(monkeypatch):
    capture: dict = {}
    body = {"data": {"ANK": {"0": {"price": 100.0, "airline": "TK"}}}}
    resp = _FakeResponse(200, body)
    monkeypatch.setattr(
        "bot.travelpayouts_client.httpx.AsyncClient",
        _make_client_class(resp, capture=capture),
    )

    await fetch_price("IST", "ANK", "2026-06-01", "MY_SECRET_TOKEN")

    assert capture["headers"].get("X-Access-Token") == "MY_SECRET_TOKEN"


async def test_booking_url_format(monkeypatch):
    body = {"data": {"ANK": {"0": {"price": 90.0, "airline": "TK"}}}}
    resp = _FakeResponse(200, body)
    monkeypatch.setattr("bot.travelpayouts_client.httpx.AsyncClient", _make_client_class(resp))

    result = await fetch_price("IST", "ANK", "2026-08-15", "token")

    # DDMM = 1508
    assert "IST1508ANK" in result["booking_url"]


async def test_currency_passed_in_params(monkeypatch):
    capture: dict = {}
    body = {"data": {"ANK": {"0": {"price": 90.0, "airline": "TK"}}}}
    resp = _FakeResponse(200, body)
    monkeypatch.setattr(
        "bot.travelpayouts_client.httpx.AsyncClient",
        _make_client_class(resp, capture=capture),
    )

    result = await fetch_price("IST", "ANK", "2026-06-01", "token", currency="TRY")

    assert capture["params"].get("currency") == "TRY"
    assert result["currency"] == "TRY"
