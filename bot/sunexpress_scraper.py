"""SunExpress Playwright scraper fallback."""

from __future__ import annotations

from datetime import date
import logging
import re
from typing import Any
from urllib.parse import urlencode

try:
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async
except ImportError:  # pragma: no cover - only hit when dependencies are absent.
    async_playwright = None
    stealth_async = None


LOGGER = logging.getLogger(__name__)
SUNEXPRESS_SEARCH_URL = "https://www.sunexpress.com/en/"


def _search_url(origin: str, destination: str, date_from: str, date_to: str) -> str:
    query = urlencode(
        {
            "origin": origin,
            "destination": destination,
            "departureDate": date_from,
            "returnDate": date_to,
        }
    )
    return f"{SUNEXPRESS_SEARCH_URL}?{query}"


async def _fill_first_available(page: Any, selectors: list[str], value: str) -> None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0:
                await locator.fill(value)
                return
        except Exception:
            continue


def _extract_price(text: str) -> float | None:
    matches = re.findall(r"(?:€|EUR)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:€|EUR)", text)
    prices: list[float] = []
    for left, right in matches:
        raw = left or right
        prices.append(float(raw.replace(",", ".")))

    if not prices:
        return None
    return min(prices)


async def fetch_price(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
) -> dict[str, Any] | None:
    """Scrape SunExpress for the cheapest visible price, never raising outward."""
    if async_playwright is None or stealth_async is None:
        LOGGER.warning("SunExpress scraper failed: Playwright dependencies are not installed")
        return None

    booking_url = _search_url(origin, destination, date_from, date_to)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await stealth_async(page)
                await page.goto(booking_url, wait_until="domcontentloaded", timeout=30000)

                await _fill_first_available(
                    page,
                    [
                        "input[name='origin']",
                        "input[name='from']",
                        "input[placeholder*='From']",
                        "input[aria-label*='From']",
                    ],
                    origin,
                )
                await _fill_first_available(
                    page,
                    [
                        "input[name='destination']",
                        "input[name='to']",
                        "input[placeholder*='To']",
                        "input[aria-label*='To']",
                    ],
                    destination,
                )
                await _fill_first_available(
                    page,
                    [
                        "input[name='departureDate']",
                        "input[name='date']",
                        "input[placeholder*='Departure']",
                        "input[aria-label*='Departure']",
                    ],
                    date.fromisoformat(date_from).strftime("%d.%m.%Y"),
                )

                for selector in [
                    "button[type='submit']",
                    "button:has-text('Search')",
                    "button:has-text('Find flights')",
                ]:
                    button = page.locator(selector).first
                    if await button.count() > 0:
                        await button.click()
                        break

                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                page_text = await page.locator("body").inner_text(timeout=10000)
                price = _extract_price(page_text)
                if price is None:
                    return None

                return {
                    "price": price,
                    "currency": "EUR",
                    "booking_url": page.url or booking_url,
                }
            finally:
                await browser.close()
    except Exception as exc:
        LOGGER.warning("SunExpress scraper failed: %s", exc)
        return None
