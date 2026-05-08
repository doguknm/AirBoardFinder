from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from bot import amadeus_client, db, sunexpress_scraper
from bot.formatter import format_alert
from bot.kiwi_client import KIWI_SEARCH_URL, fetch_price
from bot.scheduler import poll_all_watches


def _db_path() -> str:
    Path("data").mkdir(exist_ok=True)
    return str(Path("data") / f"test-{uuid4().hex}.db")


def _cleanup(db_path: str) -> None:
    path = Path(db_path)
    if path.exists():
        path.unlink()


def test_db_deduplication_layers():
    db_path = _db_path()
    db.init_db(db_path)
    try:
        watch_id = db.create_watch(
            db_path,
            123,
            "IST",
            "LHR",
            "2026-06-01",
            "2026-06-10",
            200.0,
        )

        assert db.should_send_alert(db_path, watch_id, 190.0) is True
        db.record_alert_sent(db_path, watch_id, 190.0)
        assert db.should_send_alert(db_path, watch_id, 190.0) is False
        assert db.should_send_alert(db_path, watch_id, 181.0) is False
        assert db.should_send_alert(db_path, watch_id, 180.5) is True
    finally:
        _cleanup(db_path)


def test_format_alert_contains_required_fields():
    watch = {
        "origin": "IST",
        "destination": "LHR",
        "date_from": "2026-06-01",
        "date_to": "2026-06-10",
        "max_price": 200.0,
    }

    message = format_alert(watch, 189.0, "EUR", "https://www.kiwi.com/deep")

    assert "IST" in message
    assert "LHR" in message
    assert "2026-06-01" in message
    assert "2026-06-10" in message
    assert "189.0 EUR" in message
    assert "200.0 EUR" in message
    assert "https://www.kiwi.com/deep" in message


def test_scheduler_sends_alert_and_records_history(monkeypatch):
    db_path = _db_path()
    db.init_db(db_path)
    try:
        db.create_watch(
            db_path,
            123,
            "IST",
            "LHR",
            "2026-06-01",
            "2026-06-10",
            200.0,
        )
        bot = AsyncMock()

        monkeypatch.setattr(
            "bot.scheduler.kiwi_client.fetch_price",
            AsyncMock(
                return_value={
                    "price": 189.0,
                    "currency": "EUR",
                    "booking_url": "https://example.test",
                }
            ),
        )
        monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

        asyncio.run(
            poll_all_watches(
                bot,
                db_path,
                "secret-key",
                "amadeus-id",
                "amadeus-secret",
            )
        )

        bot.send_message.assert_awaited_once()
        assert db.should_send_alert(db_path, 1, 189.0) is False
    finally:
        _cleanup(db_path)


def test_scheduler_falls_back_to_amadeus(monkeypatch):
    db_path = _db_path()
    db.init_db(db_path)
    try:
        db.create_watch(
            db_path,
            123,
            "IST",
            "LHR",
            "2026-06-01",
            "2026-06-10",
            200.0,
        )
        bot = AsyncMock()
        amadeus_fetch = AsyncMock(
            return_value={
                "price": 188.0,
                "currency": "EUR",
                "booking_url": "https://amadeus.test",
            }
        )

        monkeypatch.setattr("bot.scheduler.kiwi_client.fetch_price", AsyncMock(return_value=None))
        monkeypatch.setattr(
            "bot.scheduler.asyncio.to_thread",
            lambda func, *args: amadeus_fetch(*args),
        )
        monkeypatch.setattr("bot.scheduler.sunexpress_scraper.fetch_price", AsyncMock())
        monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

        asyncio.run(
            poll_all_watches(
                bot,
                db_path,
                "secret-key",
                "amadeus-id",
                "amadeus-secret",
            )
        )

        amadeus_fetch.assert_awaited_once()
        bot.send_message.assert_awaited_once()
        sunexpress_scraper.fetch_price.assert_not_called()
    finally:
        _cleanup(db_path)


def test_amadeus_fetch_price_parses_sdk_response(monkeypatch):
    class FakeFlightOffersSearch:
        def get(self, **kwargs):
            return type(
                "Response",
                (),
                {
                    "body": '{"data":[]}',
                    "data": [
                        {
                            "price": {
                                "total": "177.42",
                                "currency": "EUR",
                            }
                        }
                    ],
                },
            )()

    class FakeShopping:
        flight_offers_search = FakeFlightOffersSearch()

    class FakeClient:
        def __init__(self, client_id, client_secret):
            self.shopping = FakeShopping()

    monkeypatch.setenv("AMADEUS_CLIENT_ID", "amadeus-id")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "amadeus-secret")
    monkeypatch.setattr(amadeus_client, "Client", FakeClient)

    result = amadeus_client.fetch_price(
        "IST",
        "LHR",
        "2026-06-01",
        "2026-06-10",
    )

    assert result["price"] == 177.42
    assert result["currency"] == "EUR"
    assert result["booking_url"].startswith("https://www.amadeus.com/")


@pytest.mark.asyncio
async def test_sunexpress_fetch_price_returns_none_when_dependencies_missing(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(sunexpress_scraper, "async_playwright", None)
    monkeypatch.setattr(sunexpress_scraper, "stealth_async", None)

    with caplog.at_level("WARNING"):
        result = await sunexpress_scraper.fetch_price(
            "IST",
            "LHR",
            "2026-06-01",
            "2026-06-10",
        )

    assert result is None
    assert "SunExpress scraper failed" in caplog.text


@pytest.mark.asyncio
async def test_fetch_price_uses_header_not_url(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers=None, params=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["params"] = params
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                json={"data": [{"price": 189.0, "deep_link": "https://kiwi.test"}]},
                request=request,
            )

    monkeypatch.setattr("bot.kiwi_client.httpx.AsyncClient", FakeAsyncClient)

    result = await fetch_price(
        "IST",
        "LHR",
        "2026-06-01",
        "2026-06-10",
        "secret-key",
    )

    assert result == {
        "price": 189.0,
        "currency": "EUR",
        "booking_url": "https://kiwi.test",
    }
    assert captured["url"] == KIWI_SEARCH_URL
    assert "secret-key" not in captured["url"]
    assert captured["headers"] == {"apiKey": "secret-key"}
    assert captured["params"]["date_from"] == "01/06/2026"


@pytest.mark.asyncio
async def test_fetch_price_empty_kiwi_triggers_fallback(monkeypatch, caplog):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers=None, params=None):
            request = httpx.Request("GET", url)
            return httpx.Response(200, json={"data": []}, request=request)

    fallback_result = {
        "price": 175.0,
        "currency": "EUR",
        "booking_url": "https://fallback.test",
    }
    monkeypatch.setattr("bot.kiwi_client.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        "bot.kiwi_client._fetch_fast_flights",
        lambda *args: fallback_result,
    )

    with caplog.at_level("WARNING"):
        result = await fetch_price(
            "IST",
            "LHR",
            "2026-06-01",
            "2026-06-10",
            "secret-key",
        )

    assert result == fallback_result
    assert "falling back to fast-flights" in caplog.text
