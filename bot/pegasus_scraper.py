"""Pegasus Airlines Playwright scraper fallback."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

try:
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async
except ImportError:  # pragma: no cover - only hit when dependencies are absent.
    async_playwright = None
    stealth_async = None

from bot.scraper_utils import date_range, extract_price

LOGGER = logging.getLogger(__name__)


def _search_url(origin: str, destination: str, departure_date: str) -> str:
    query = urlencode({
        "language": "en",
        "adultCount": 1,
        "departurePort": origin,
        "arrivalPort": destination,
        "currency": "EUR",
        "dateOption": 1,
        "departureDate": departure_date,
    })
    return f"https://web.flypgs.com/booking?{query}"


async def fetch_price(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
) -> dict[str, Any] | None:
    """Scrape Pegasus Airlines for the cheapest one-way EUR price across the date range, never raising outward."""
    if async_playwright is None or stealth_async is None:
        LOGGER.warning("Pegasus scraper failed: Playwright dependencies are not installed")
        return None

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await stealth_async(page)

                min_price: float | None = None
                best_date: str | None = None

                for dep_date in date_range(date_from, date_to):
                    url = _search_url(origin, destination, dep_date)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass

                    page_text = await page.locator("body").inner_text(timeout=10000)
                    price = extract_price(page_text)

                    if price is not None:
                        if min_price is None or price < min_price:
                            min_price = price
                            best_date = dep_date

                if min_price is None:
                    return None

                return {
                    "price": min_price,
                    "currency": "EUR",
                    "booking_url": _search_url(origin, destination, best_date),
                }
            finally:
                await browser.close()
    except Exception as exc:
        LOGGER.warning("Pegasus scraper failed: %s", exc)
        return None
