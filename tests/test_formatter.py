from __future__ import annotations

import pytest

from bot.formatter import format_alert

WATCH = {
    "origin": "IST",
    "destination": "LHR",
    "date_from": "2026-06-01",
    "date_to": "2026-06-10",
    "max_price": 200.0,
}
BOOKING_URL = "https://www.aviasales.com/search/IST0106LHR1"


@pytest.fixture
def message():
    return format_alert(WATCH, 189.0, "EUR", BOOKING_URL)


def test_format_alert_contains_route(message):
    assert "IST" in message
    assert "LHR" in message


def test_format_alert_contains_price(message):
    assert "189.0" in message
    assert "EUR" in message


def test_format_alert_contains_booking_url(message):
    assert BOOKING_URL in message


def test_format_alert_contains_threshold(message):
    assert "200.0" in message


def test_format_alert_contains_dates(message):
    assert "2026-06-01" in message
    assert "2026-06-10" in message


def test_format_alert_shows_fare_family_when_provided():
    msg = format_alert(WATCH, 189.0, "EUR", BOOKING_URL, fare_family="EcoFly")
    assert "EcoFly" in msg


def test_format_alert_no_fare_family_line_when_none():
    msg = format_alert(WATCH, 189.0, "EUR", BOOKING_URL, fare_family=None)
    assert "Fare:" not in msg
