"""Shared utilities for Playwright-based flight price scrapers."""

from __future__ import annotations

from datetime import date, timedelta
import re


def date_range(date_from: str, date_to: str):
    current = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def extract_price(text: str) -> float | None:
    matches = re.findall(
        r"(?:€|EUR|₺|TRY)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:€|EUR|₺|TRY)",
        text,
    )
    min_price: float | None = None
    for left, right in matches:
        price = float((left or right).replace(",", "."))
        if min_price is None or price < min_price:
            min_price = price
    return min_price
