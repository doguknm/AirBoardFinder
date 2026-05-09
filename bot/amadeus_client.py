"""Amadeus Flight Offers Search fallback client."""

from __future__ import annotations

import logging
import os
from typing import Any

from bot.formatter import aviasales_url

try:
    from amadeus import Client, ResponseError
except ImportError:  # pragma: no cover - only hit when dependency is absent.
    Client = None

    class ResponseError(Exception):
        """Fallback exception type when the Amadeus SDK is unavailable."""


LOGGER = logging.getLogger(__name__)


def _amadeus_client() -> Any | None:
    client_id = os.environ.get("AMADEUS_CLIENT_ID")
    client_secret = os.environ.get("AMADEUS_CLIENT_SECRET")
    if not client_id or not client_secret:
        LOGGER.error("Amadeus credentials are not configured.")
        return None
    if Client is None:
        LOGGER.error("Amadeus SDK is not installed.")
        return None

    return Client(client_id=client_id, client_secret=client_secret)


def fetch_price(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
) -> dict[str, Any] | None:
    """Return the cheapest one-way Amadeus flight offer, if available."""
    client = _amadeus_client()
    if client is None:
        return None

    try:
        response = client.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=destination,
            departureDate=date_from,
            adults=1,
            currencyCode="EUR",
            max=1,
        )
    except ResponseError as exc:
        LOGGER.error("Amadeus API error for %s-%s: %s", origin, destination, exc)
        return None
    except Exception as exc:
        LOGGER.error("Amadeus request failed for %s-%s: %s", origin, destination, exc)
        return None

    LOGGER.debug("Amadeus raw response: %s", getattr(response, "body", response))
    offers = getattr(response, "data", None) or []
    if not offers:
        return None

    offer = offers[0]
    total = offer.get("price", {}).get("total")
    currency = offer.get("price", {}).get("currency", "EUR")
    if total is None:
        return None

    return {
        "price": float(total),
        "currency": currency,
        "booking_url": aviasales_url(origin, destination, date_from),
    }
