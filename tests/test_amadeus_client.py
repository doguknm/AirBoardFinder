from __future__ import annotations

import pytest

from bot import amadeus_client


def _patch_client(monkeypatch, data=None, raise_exc=None):
    """Replace amadeus_client.Client with a fake that returns controlled data."""
    class _FakeSearch:
        def get(self, **kwargs):
            if raise_exc is not None:
                raise raise_exc
            resp = type("Resp", (), {"data": data or [], "body": "{}"})()
            return resp

    class _FakeShopping:
        flight_offers_search = _FakeSearch()

    class _FakeClient:
        def __init__(self, client_id, client_secret):
            self.shopping = _FakeShopping()

    monkeypatch.setenv("AMADEUS_CLIENT_ID", "test-id")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(amadeus_client, "Client", _FakeClient)


def test_fetch_price_success(monkeypatch):
    _patch_client(
        monkeypatch,
        data=[{"price": {"total": "177.42", "currency": "EUR"}}],
    )

    result = amadeus_client.fetch_price("IST", "LHR", "2026-06-01", "2026-06-10")

    assert result is not None
    assert result["price"] == 177.42
    assert result["currency"] == "EUR"
    assert "booking_url" in result


def test_fetch_price_no_offers_returns_none(monkeypatch):
    _patch_client(monkeypatch, data=[])

    result = amadeus_client.fetch_price("IST", "LHR", "2026-06-01", "2026-06-10")

    assert result is None


def test_fetch_price_sdk_error_returns_none(monkeypatch, caplog):
    _patch_client(monkeypatch, raise_exc=amadeus_client.ResponseError("API error"))

    with caplog.at_level("ERROR", logger="bot.amadeus_client"):
        result = amadeus_client.fetch_price("IST", "LHR", "2026-06-01", "2026-06-10")

    assert result is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_credentials_not_in_logged_output(monkeypatch, caplog):
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "SUPER_SECRET_ID")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "SUPER_SECRET_KEY")
    _patch_client(
        monkeypatch,
        data=[{"price": {"total": "100.0", "currency": "EUR"}}],
    )
    # override the env vars set by _patch_client so the secret values are the ones we care about
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "SUPER_SECRET_ID")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "SUPER_SECRET_KEY")

    with caplog.at_level("DEBUG", logger="bot.amadeus_client"):
        amadeus_client.fetch_price("IST", "LHR", "2026-06-01", "2026-06-10")

    assert "SUPER_SECRET_ID" not in caplog.text
    assert "SUPER_SECRET_KEY" not in caplog.text
