"""Kiwi client is deprecated — verify the stub returns None."""

from __future__ import annotations

import pytest

from bot.kiwi_client import fetch_price


async def test_fetch_price_returns_none(caplog):
    with caplog.at_level("WARNING", logger="bot.kiwi_client"):
        result = await fetch_price("IST", "LHR", "2026-06-01", "2026-06-10", "any-key")

    assert result is None
    assert "B2B-only" in caplog.text
