"""APScheduler polling job for active watches."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from bot import db, duffel_client, formatter, pegasus_scraper, sunexpress_scraper, travelpayouts_client


LOGGER = logging.getLogger(__name__)

_EUR_TRY_RATE = float(os.getenv("EUR_TRY_RATE", "54.0"))


def _normalize_price(price: float, src: str, dst: str) -> float:
    """Convert price between EUR and TRY using the configured exchange rate."""
    if src == dst:
        return price
    if src == "TRY" and dst == "EUR":
        return round(price / _EUR_TRY_RATE, 2)
    if src == "EUR" and dst == "TRY":
        return round(price * _EUR_TRY_RATE, 2)
    return price


async def poll_single_watch(
    bot: Any,
    db_path: str,
    watch: dict[str, Any],
    travelpayouts_token: str,
    duffel_api_key: str,
    notify_always: bool = False,
) -> None:
    """Poll one watch. When notify_always=True, always send a follow-up even if above threshold."""
    watch_id = watch["id"]
    watch_currency = watch.get("currency", "TRY")

    failed_sources: list[str] = []

    result = await travelpayouts_client.fetch_price(
        watch["origin"],
        watch["destination"],
        watch["date_from"],
        travelpayouts_token,
        currency=watch_currency,
    )

    if result is None:
        failed_sources.append(
            "Travelpayouts — no cached prices for this route "
            "(data is updated every 48h–7d; some routes have no coverage)"
        )
        LOGGER.warning(
            "Travelpayouts returned no result for watch %s, trying SunExpress.", watch_id
        )
        result = await sunexpress_scraper.fetch_price(
            watch["origin"],
            watch["destination"],
            watch["date_from"],
            watch["date_to"],
        )
        if result is None:
            failed_sources.append(
                "SunExpress scraper — no prices found "
                "(route may not be served by SunExpress, or the website blocked the scraper)"
            )
            result = await pegasus_scraper.fetch_price(
                watch["origin"],
                watch["destination"],
                watch["date_from"],
                watch["date_to"],
            )
            if result is None:
                failed_sources.append(
                    "Pegasus scraper — no prices found "
                    "(route may not be served by Pegasus, or the website blocked the scraper)"
                )

    if result is None:
        LOGGER.info("No price found for watch %s from any source, skipping.", watch_id)
        if notify_always:
            reasons = "\n• ".join(failed_sources)
            await bot.send_message(
                chat_id=watch["user_id"],
                text=(
                    f"No price data found for {watch['origin']} → {watch['destination']}.\n\n"
                    f"Sources tried:\n• {reasons}\n\n"
                    f"I'll keep checking every 2 minutes."  # TODO: change back to 60 after testing
                ),
            )
        return

    price = float(result["price"])
    currency = str(result["currency"])
    booking_url = str(result["booking_url"])

    if currency != watch_currency:
        price = _normalize_price(price, currency, watch_currency)
        currency = watch_currency

    db.insert_price_history(db_path, watch_id, price, currency, booking_url)

    below_threshold = price <= float(watch["max_price"])

    if below_threshold and db.should_send_alert(db_path, watch_id, price):
        fare_family: str | None = None
        duffel_result = await duffel_client.verify_price(
            watch["origin"],
            watch["destination"],
            watch["date_from"],
            duffel_api_key,
            currency=watch_currency,
        )
        if duffel_result is not None:
            if duffel_result["price"] > float(watch["max_price"]):
                LOGGER.info(
                    "Duffel verified price %.2f above threshold for watch %s, suppressing.",
                    duffel_result["price"],
                    watch_id,
                )
                if notify_always:
                    await bot.send_message(
                        chat_id=watch["user_id"],
                        text=(
                            f"Cached price {price:.2f} {currency} looked good, but "
                            f"real-time check shows {duffel_result['price']:.2f} {currency} "
                            f"— above your threshold. I'll keep monitoring."
                        ),
                    )
                return
            price = duffel_result["price"]
            currency = duffel_result["currency"]
            booking_url = duffel_result["booking_url"]
            fare_family = duffel_result.get("fare_family")

        message = formatter.format_alert(watch, price, currency, booking_url, fare_family)
        db.record_alert_sent(db_path, watch_id, price)
        await bot.send_message(chat_id=watch["user_id"], text=message)
        LOGGER.info("Alert sent for watch %s at %s %s", watch_id, price, currency)

    elif notify_always:
        if below_threshold:
            text = (
                f"Current price: {price:.2f} {currency} — within your threshold of "
                f"{watch['max_price']} {currency}. Already alerted at this price level."
            )
        else:
            text = (
                f"Current price for {watch['origin']} → {watch['destination']}: "
                f"{price:.2f} {currency}\n"
                f"Above your {watch['max_price']} {currency} threshold. "
                f"I'll alert you when it drops."
            )
        await bot.send_message(chat_id=watch["user_id"], text=text)


async def poll_all_watches(
    bot: Any,
    db_path: str,
    travelpayouts_token: str,
    duffel_api_key: str,
) -> None:
    """Poll every active watch and send Telegram alerts when criteria pass."""
    watches = db.get_all_active_watches(db_path)
    for watch in watches:
        await poll_single_watch(bot, db_path, watch, travelpayouts_token, duffel_api_key)
        await asyncio.sleep(0.5)
