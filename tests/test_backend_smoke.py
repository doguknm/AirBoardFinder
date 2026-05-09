from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bot import amadeus_client, db, sunexpress_scraper
from bot.formatter import format_alert
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

    message = format_alert(watch, 189.0, "EUR", "https://www.aviasales.com/search/IST0106LHR1")

    assert "IST" in message
    assert "LHR" in message
    assert "2026-06-01" in message
    assert "2026-06-10" in message
    assert "189.0 EUR" in message
    assert "200.0 EUR" in message


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
            "bot.scheduler.travelpayouts_client.fetch_price",
            AsyncMock(
                return_value={
                    "price": 189.0,
                    "currency": "EUR",
                    "booking_url": "https://example.test",
                    "airline": "TK",
                }
            ),
        )
        monkeypatch.setattr(
            "bot.scheduler.duffel_client.verify_price",
            AsyncMock(
                return_value={
                    "price": 189.0,
                    "currency": "EUR",
                    "booking_url": "https://example.test",
                    "fare_family": "Basic",
                }
            ),
        )
        monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

        asyncio.run(
            poll_all_watches(
                bot,
                db_path,
                "tp-token",
                "duffel-key",
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

        monkeypatch.setattr(
            "bot.scheduler.travelpayouts_client.fetch_price", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            "bot.scheduler.asyncio.to_thread",
            lambda func, *args: amadeus_fetch(*args),
        )
        monkeypatch.setattr("bot.scheduler.sunexpress_scraper.fetch_price", AsyncMock())
        monkeypatch.setattr(
            "bot.scheduler.duffel_client.verify_price",
            AsyncMock(
                return_value={
                    "price": 188.0,
                    "currency": "EUR",
                    "booking_url": "https://amadeus.test",
                    "fare_family": None,
                }
            ),
        )
        monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

        asyncio.run(
            poll_all_watches(
                bot,
                db_path,
                "tp-token",
                "duffel-key",
            )
        )

        amadeus_fetch.assert_awaited_once()
        bot.send_message.assert_awaited_once()
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
