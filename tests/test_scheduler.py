from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bot import db
from bot.scheduler import poll_all_watches


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "sched.db")
    db.init_db(path)
    return path


@pytest.fixture
def watch_id(db_path):
    return db.create_watch(db_path, 123, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0, "EUR")


_TP_RESULT = {"price": 189.0, "currency": "EUR", "booking_url": "https://av.test", "airline": "TK"}
_DUFFEL_RESULT = {"price": 189.0, "currency": "EUR", "booking_url": "https://av.test", "fare_family": "Basic"}


async def test_poll_inserts_price_history_and_sends_alert(db_path, watch_id, monkeypatch):
    bot = AsyncMock()
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price",
        AsyncMock(return_value=_TP_RESULT),
    )
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price",
        AsyncMock(return_value=_DUFFEL_RESULT),
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    bot.send_message.assert_awaited_once()
    assert db.should_send_alert(db_path, watch_id, 189.0) is False


async def test_poll_falls_back_to_sunexpress_when_travelpayouts_returns_none(
    db_path, watch_id, monkeypatch, caplog
):
    bot = AsyncMock()
    sunexpress_mock = AsyncMock(
        return_value={"price": 185.0, "currency": "EUR", "booking_url": "https://sx.test"}
    )
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("bot.scheduler.sunexpress_scraper.fetch_price", sunexpress_mock)
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price",
        AsyncMock(return_value={"price": 185.0, "currency": "EUR", "booking_url": "https://sx.test", "fare_family": None}),
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    with caplog.at_level("WARNING", logger="bot.scheduler"):
        await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    sunexpress_mock.assert_awaited_once()
    bot.send_message.assert_awaited_once()


async def test_poll_falls_back_to_pegasus_when_sunexpress_returns_none(
    db_path, watch_id, monkeypatch
):
    bot = AsyncMock()
    pegasus_mock = AsyncMock(
        return_value={"price": 750.0, "currency": "TRY", "booking_url": "https://flypgs.test"}
    )
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "bot.scheduler.sunexpress_scraper.fetch_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("bot.scheduler.pegasus_scraper.fetch_price", pegasus_mock)
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    pegasus_mock.assert_awaited_once()
    bot.send_message.assert_awaited_once()  # 750 TRY = ~13.89 EUR, below 200 EUR threshold


async def test_poll_does_not_send_alert_above_threshold(db_path, watch_id, monkeypatch):
    bot = AsyncMock()
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price",
        AsyncMock(return_value={"price": 250.0, "currency": "EUR", "booking_url": "https://av.test", "airline": "TK"}),
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    bot.send_message.assert_not_called()


async def test_poll_sends_alert_logs_info(db_path, watch_id, monkeypatch, caplog):
    bot = AsyncMock()
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price",
        AsyncMock(return_value=_TP_RESULT),
    )
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price",
        AsyncMock(return_value=_DUFFEL_RESULT),
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    with caplog.at_level("INFO", logger="bot.scheduler"):
        await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    assert any("Alert sent" in r.message for r in caplog.records)


async def test_poll_proceeds_when_duffel_returns_none(db_path, watch_id, monkeypatch):
    """Duffel failure must not suppress an alert that should fire."""
    bot = AsyncMock()
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price",
        AsyncMock(return_value=_TP_RESULT),
    )
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    bot.send_message.assert_awaited_once()


async def test_poll_suppresses_alert_when_duffel_price_above_threshold(
    db_path, watch_id, monkeypatch, caplog
):
    bot = AsyncMock()
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price",
        AsyncMock(return_value=_TP_RESULT),
    )
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price",
        AsyncMock(
            return_value={"price": 350.0, "currency": "EUR", "booking_url": "https://av.test", "fare_family": None}
        ),
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    with caplog.at_level("INFO", logger="bot.scheduler"):
        await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    bot.send_message.assert_not_called()
    assert any("suppressing" in r.message for r in caplog.records)
