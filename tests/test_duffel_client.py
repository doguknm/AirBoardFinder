from __future__ import annotations

import httpx
import pytest

from bot.duffel_client import DUFFEL_OFFER_REQUESTS_URL, verify_price


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self._json = json_body
        self.status_code = status_code
        self.text = str(json_body)
        self.request = httpx.Request("POST", DUFFEL_OFFER_REQUESTS_URL)

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

        async def post(self, url, headers=None, json=None, params=None):
            if capture is not None:
                capture["headers"] = headers or {}
                capture["json"] = json or {}
            return response

    return _Client


async def test_verify_price_success(monkeypatch):
    body = {
        "data": {
            "offers": [
                {
                    "total_amount": "135.00",
                    "total_currency": "EUR",
                    "slices": [{"fare_brand_name": "EcoFly"}],
                }
            ]
        }
    }
    resp = _FakeResponse(200, body)
    monkeypatch.setattr("bot.duffel_client.httpx.AsyncClient", _make_client_class(resp))

    result = await verify_price("IST", "ANK", "2026-06-01", "duffel-key")

    assert result is not None
    assert result["price"] == 135.0
    assert result["currency"] == "EUR"
    assert result["fare_family"] == "EcoFly"
    assert "aviasales.com" in result["booking_url"]


async def test_verify_price_picks_cheapest(monkeypatch):
    body = {
        "data": {
            "offers": [
                {
                    "total_amount": "200.00",
                    "total_currency": "EUR",
                    "slices": [{"fare_brand_name": "Business"}],
                },
                {
                    "total_amount": "110.00",
                    "total_currency": "EUR",
                    "slices": [{"fare_brand_name": "Basic"}],
                },
            ]
        }
    }
    resp = _FakeResponse(200, body)
    monkeypatch.setattr("bot.duffel_client.httpx.AsyncClient", _make_client_class(resp))

    result = await verify_price("IST", "ANK", "2026-06-01", "duffel-key")

    assert result["price"] == 110.0
    assert result["fare_family"] == "Basic"


async def test_verify_price_no_offers_returns_none(monkeypatch, caplog):
    resp = _FakeResponse(200, {"data": {"offers": []}})
    monkeypatch.setattr("bot.duffel_client.httpx.AsyncClient", _make_client_class(resp))

    with caplog.at_level("WARNING", logger="bot.duffel_client"):
        result = await verify_price("IST", "ANK", "2026-06-01", "duffel-key")

    assert result is None
    assert "no offers" in caplog.text


async def test_verify_price_http_error_returns_none(monkeypatch, caplog):
    resp = _FakeResponse(401, {})
    monkeypatch.setattr("bot.duffel_client.httpx.AsyncClient", _make_client_class(resp))

    with caplog.at_level("ERROR", logger="bot.duffel_client"):
        result = await verify_price("IST", "ANK", "2026-06-01", "duffel-key")

    assert result is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


async def test_api_key_in_auth_header(monkeypatch):
    capture: dict = {}
    body = {
        "data": {
            "offers": [
                {"total_amount": "99.00", "total_currency": "EUR", "slices": []}
            ]
        }
    }
    resp = _FakeResponse(200, body)
    monkeypatch.setattr(
        "bot.duffel_client.httpx.AsyncClient",
        _make_client_class(resp, capture=capture),
    )

    await verify_price("IST", "ANK", "2026-06-01", "MY_DUFFEL_KEY")

    assert capture["headers"].get("Authorization") == "Bearer MY_DUFFEL_KEY"


async def test_fare_family_none_when_no_slices(monkeypatch):
    body = {
        "data": {
            "offers": [
                {"total_amount": "99.00", "total_currency": "EUR", "slices": []}
            ]
        }
    }
    resp = _FakeResponse(200, body)
    monkeypatch.setattr("bot.duffel_client.httpx.AsyncClient", _make_client_class(resp))

    result = await verify_price("IST", "ANK", "2026-06-01", "key")

    assert result["fare_family"] is None
