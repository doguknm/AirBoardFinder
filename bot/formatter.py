"""Telegram alert message formatting."""

from __future__ import annotations


def aviasales_url(origin: str, destination: str, date_from: str) -> str:
    parts = date_from.split("-")
    ddmm = parts[2] + parts[1]
    return f"https://www.aviasales.com/search/{origin}{ddmm}{destination}1"


def format_alert(
    watch: dict,
    price: float,
    currency: str,
    booking_url: str,
    fare_family: str | None = None,
) -> str:
    """Return the user-facing Telegram alert text."""
    fare_line = f"Fare: {fare_family}\n" if fare_family else ""
    return (
        f"Flight alert: {watch['origin']} → {watch['destination']}\n"
        f"Dates: {watch['date_from']} – {watch['date_to']}\n"
        f"Price: {price} {currency}\n"
        f"Your alert threshold: {watch['max_price']} {currency}\n"
        f"{fare_line}"
        f"Book: {booking_url}"
    )
