"""Duffel API client — pre-alert price verification only, never used for booking."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.formatter import aviasales_url


LOGGER = logging.getLogger(__name__)
DUFFEL_OFFER_REQUESTS_URL = "https://api.duffel.com/air/offer_requests"


async def verify_price(
    origin: str,
    destination: str,
    date_from: str,
    api_key: str,
    currency: str = "EUR",
) -> dict[str, Any] | None:
    """Verify real-time price with Duffel before sending an alert.

    Returns the cheapest offer or None on any error. Callers must treat None
    as a non-fatal failure and proceed with the originally polled price.
    """
    body = {
        "data": {
            "slices": [
                {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": date_from,
                }
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                DUFFEL_OFFER_REQUESTS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Duffel-Version": "v2",
                    "Content-Type": "application/json",
                },
                json=body,
                params={"return_offers": "true"},
            )
            LOGGER.debug("Duffel raw response: %s", response.text)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        LOGGER.error(
            "Duffel HTTP error for %s-%s: %s",
            origin,
            destination,
            exc.response.status_code,
        )
        return None
    except httpx.HTTPError as exc:
        LOGGER.error("Duffel request failed for %s-%s: %s", origin, destination, exc)
        return None

    offers = (
        payload.get("data", {}).get("offers", []) if isinstance(payload, dict) else []
    )
    if not offers:
        LOGGER.warning("Duffel returned no offers for %s-%s", origin, destination)
        return None

    cheapest = min(offers, key=lambda o: float(o.get("total_amount", float("inf"))))
    price_str = cheapest.get("total_amount")
    if price_str is None:
        return None

    slices = cheapest.get("slices", [])
    fare_family: str | None = slices[0].get("fare_brand_name") if slices else None

    return {
        "price": float(price_str),
        "currency": cheapest.get("total_currency", currency),
        "booking_url": aviasales_url(origin, destination, date_from),
        "fare_family": fare_family,
    }
