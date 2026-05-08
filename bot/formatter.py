"""Telegram alert message formatting."""

from __future__ import annotations


def format_alert(watch: dict, price: float, currency: str, booking_url: str) -> str:
    """Return the user-facing Telegram alert text."""
    return (
        f"Flight alert: {watch['origin']} → {watch['destination']}\n"
        f"Dates: {watch['date_from']} – {watch['date_to']}\n"
        f"Price: {price} {currency}\n"
        f"Your alert threshold: {watch['max_price']} {currency}\n"
        f"Book: {booking_url}"
    )
