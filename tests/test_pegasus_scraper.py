from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import pegasus_scraper


def _make_playwright_mock(raise_on_enter=None, raise_on_page_op=None):
    """Build a fake async_playwright context manager hierarchy."""
    browser = AsyncMock()
    page = AsyncMock()

    if raise_on_page_op:
        page.goto.side_effect = raise_on_page_op

    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = MagicMock()
    chromium.launch = AsyncMock(return_value=browser)

    playwright_ctx = MagicMock()
    playwright_ctx.chromium = chromium

    pw_cm = AsyncMock()
    if raise_on_enter:
        pw_cm.__aenter__.side_effect = raise_on_enter
    else:
        pw_cm.__aenter__.return_value = playwright_ctx
    pw_cm.__aexit__ = AsyncMock(return_value=False)

    return pw_cm, browser


async def test_fetch_price_exception_returns_none(monkeypatch, caplog):
    pw_cm, _ = _make_playwright_mock(raise_on_enter=RuntimeError("playwright broke"))
    monkeypatch.setattr(pegasus_scraper, "async_playwright", lambda: pw_cm)
    monkeypatch.setattr(pegasus_scraper, "stealth_async", AsyncMock())

    with caplog.at_level("WARNING", logger="bot.pegasus_scraper"):
        result = await pegasus_scraper.fetch_price("SAW", "HTY", "2026-06-01", "2026-06-06")

    assert result is None
    assert "Pegasus scraper failed" in caplog.text


async def test_fetch_price_never_raises(monkeypatch):
    pw_cm, _ = _make_playwright_mock(raise_on_enter=RuntimeError("any error"))
    monkeypatch.setattr(pegasus_scraper, "async_playwright", lambda: pw_cm)
    monkeypatch.setattr(pegasus_scraper, "stealth_async", AsyncMock())

    # Must not raise — any exception must be swallowed
    result = await pegasus_scraper.fetch_price("SAW", "HTY", "2026-06-01", "2026-06-06")
    assert result is None


async def test_browser_closed_on_exception(monkeypatch):
    pw_cm, browser = _make_playwright_mock(raise_on_page_op=RuntimeError("page broke"))
    monkeypatch.setattr(pegasus_scraper, "async_playwright", lambda: pw_cm)
    monkeypatch.setattr(pegasus_scraper, "stealth_async", AsyncMock())

    result = await pegasus_scraper.fetch_price("SAW", "HTY", "2026-06-01", "2026-06-06")

    assert result is None
    browser.close.assert_awaited_once()
