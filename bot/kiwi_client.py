"""Kiwi Tequila flight price client with fast-flights fallback."""

from __future__ import annotations

import asyncio
from datetime import date
import logging
import re
from typing import Any
from urllib.parse import urlencode

import httpx

try:
    from fast_flights import FlightData, Passengers, get_flights
except ImportError:  # pragma: no cover - exercised only when optional package is absent.
    FlightData = None
    Passengers = None
    get_flights = None


LOGGER = logging.getLogger(__name__)
KIWI_SEARCH_URL = "https://api.tequila.kiwi.com/v2/search"


def _kiwi_date(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d/%m/%Y")


def _fallback_url(origin: str, destination: str, date_from: str, date_to: str) -> str:
    query = urlencode(
        {
            "q": f"{origin} to {destination} {date_from} {date_to}",
            "curr": "EUR",
        }
    )
    return f"https://www.google.com/travel/flights?{query}"


def _parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)

    match = re.search(r"\d+(?:[.,]\d+)?", str(value).replace(",", ""))
    if match is None:
        return None
    return float(match.group(0))


def _extract_fast_flights_price(result: Any) -> float | None:
    flights = getattr(result, "flights", None) or []
    for flight in flights:
        price = _parse_price(getattr(flight, "price", None))
        if price is not None:
            return price

    return _parse_price(getattr(result, "current_price", None))


def _fetch_fast_flights(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
) -> dict[str, Any] | None:
    if FlightData is None or Passengers is None or get_flights is None:
        LOGGER.warning("fast-flights fallback failed: package is not installed")
        return None

    flight_data = [
        FlightData(date=date_from, from_airport=origin, to_airport=destination)
    ]
    trip = "one-way"

    if date_to != date_from:
        flight_data.append(
            FlightData(date=date_to, from_airport=destination, to_airport=origin)
        )
        trip = "round-trip"

    result = get_flights(
        flight_data=flight_data,
        trip=trip,
        seat="economy",
        passengers=Passengers(adults=1),
        fetch_mode="fallback",
    )
    price = _extract_fast_flights_price(result)
    if price is None:
        return None

    return {
        "price": price,
        "currency": "EUR",
        "booking_url": _fallback_url(origin, destination, date_from, date_to),
    }


async def _fallback_price(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
) -> dict[str, Any] | None:
    LOGGER.warning(
        "Kiwi returned no results for %s-%s, falling back to fast-flights",
        origin,
        destination,
    )
    try:
        return await asyncio.to_thread(
            _fetch_fast_flights,
            origin,
            destination,
            date_from,
            date_to,
        )
    except Exception as exc:
        LOGGER.warning("fast-flights fallback failed: %s", exc)
        return None


async def fetch_price(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
    api_key: str,
) -> dict[str, Any] | None:
    """Fetch the cheapest route price from Kiwi, falling back on empty results."""
    params = {
        "fly_from": origin,
        "fly_to": destination,
        "date_from": _kiwi_date(date_from),
        "date_to": _kiwi_date(date_to),
        "curr": "EUR",
        "limit": 1,
        "sort": "price",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                KIWI_SEARCH_URL,
                headers={"apiKey": api_key},
                params=params,
            )
            LOGGER.debug("Kiwi raw response body: %s", response.text)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        LOGGER.error(
            "Kiwi HTTP error for %s-%s: %s",
            origin,
            destination,
            exc.response.status_code,
        )
        return None
    except httpx.HTTPError as exc:
        LOGGER.error("Kiwi request failed for %s-%s: %s", origin, destination, exc)
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return await _fallback_price(origin, destination, date_from, date_to)

    cheapest = data[0]
    return {
        "price": float(cheapest["price"]),
        "currency": "EUR",
        "booking_url": cheapest.get("deep_link") or cheapest.get("booking_url") or "",
    }
