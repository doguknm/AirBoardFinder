"""Travelpayouts Aviasales cached price client — primary polling source."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.formatter import aviasales_url


LOGGER = logging.getLogger(__name__)
TRAVELPAYOUTS_URL = "https://api.travelpayouts.com/v1/prices/cheap"


async def fetch_price(
    origin: str,
    destination: str,
    date_from: str,
    token: str,
    currency: str = "EUR",
) -> dict[str, Any] | None:
    """Fetch cheapest cached price from Travelpayouts Data API.

    TRY currency support is undocumented by Travelpayouts; the API may reject
    it with a non-2xx response, causing this function to return None so the
    scheduler falls through to the next source.
    """
    params = {
        "origin": origin,
        "destination": destination,
        "currency": currency,
        "depart_date": date_from,
        "one_way": True,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                TRAVELPAYOUTS_URL,
                headers={"X-Access-Token": token},
                params=params,
            )
            LOGGER.debug("Travelpayouts raw response: %s", response.text)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        LOGGER.error(
            "Travelpayouts HTTP error for %s-%s: %s",
            origin,
            destination,
            exc.response.status_code,
        )
        return None
    except httpx.HTTPError as exc:
        LOGGER.error("Travelpayouts request failed for %s-%s: %s", origin, destination, exc)
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not data or destination not in data:
        LOGGER.warning("Travelpayouts returned no data for %s-%s", origin, destination)
        return None

    dest_data = data[destination]
    entries = list(dest_data.values()) if isinstance(dest_data, dict) else []
    if not entries:
        return None

    cheapest = min(entries, key=lambda e: float(e.get("price", float("inf"))))
    price = cheapest.get("price")
    if price is None:
        return None

    return {
        "price": float(price),
        "currency": currency,
        "booking_url": aviasales_url(origin, destination, date_from),
        "airline": cheapest.get("airline"),
    }
