"""APScheduler polling job for active watches."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot import amadeus_client, db, formatter, kiwi_client, sunexpress_scraper


LOGGER = logging.getLogger(__name__)


async def poll_all_watches(
    bot: Any,
    db_path: str,
    kiwi_api_key: str,
    amadeus_client_id: str,
    amadeus_client_secret: str,
) -> None:
    """Poll every active watch and send Telegram alerts when criteria pass."""
    watches = db.get_all_active_watches(db_path)
    _ = (amadeus_client_id, amadeus_client_secret)

    for watch in watches:
        watch_id = watch["id"]
        result = await kiwi_client.fetch_price(
            watch["origin"],
            watch["destination"],
            watch["date_from"],
            watch["date_to"],
            kiwi_api_key,
        )

        if result is None:
            LOGGER.warning("Kiwi returned no result for watch %s, trying Amadeus.", watch_id)
            result = await asyncio.to_thread(
                amadeus_client.fetch_price,
                watch["origin"],
                watch["destination"],
                watch["date_from"],
                watch["date_to"],
            )

        if result is None:
            LOGGER.warning(
                "Amadeus returned no result for watch %s, trying SunExpress.",
                watch_id,
            )
            result = await sunexpress_scraper.fetch_price(
                watch["origin"],
                watch["destination"],
                watch["date_from"],
                watch["date_to"],
            )

        if result is None:
            LOGGER.info(
                "No price found for watch %s from any source, skipping.",
                watch_id,
            )
            await asyncio.sleep(0.5)
            continue

        price = float(result["price"])
        currency = str(result["currency"])
        booking_url = str(result["booking_url"])

        db.insert_price_history(db_path, watch_id, price, currency, booking_url)

        if price <= float(watch["max_price"]) and db.should_send_alert(
            db_path,
            watch_id,
            price,
        ):
            message = formatter.format_alert(watch, price, currency, booking_url)
            await bot.send_message(chat_id=watch["user_id"], text=message)
            db.record_alert_sent(db_path, watch_id, price)
            LOGGER.info("Alert sent for watch %s at %s %s", watch_id, price, currency)

        await asyncio.sleep(0.5)
