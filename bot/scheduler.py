"""APScheduler polling job for active watches."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot import db, duffel_client, formatter, sunexpress_scraper, travelpayouts_client


LOGGER = logging.getLogger(__name__)


async def poll_all_watches(
    bot: Any,
    db_path: str,
    travelpayouts_token: str,
    duffel_api_key: str,
) -> None:
    """Poll every active watch and send Telegram alerts when criteria pass."""
    watches = db.get_all_active_watches(db_path)

    for watch in watches:
        watch_id = watch["id"]
        watch_currency = watch.get("currency", "EUR")

        result = await travelpayouts_client.fetch_price(
            watch["origin"],
            watch["destination"],
            watch["date_from"],
            travelpayouts_token,
            currency=watch_currency,
        )

        if result is None:
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
                    await asyncio.sleep(0.5)
                    continue
                price = duffel_result["price"]
                currency = duffel_result["currency"]
                booking_url = duffel_result["booking_url"]
                fare_family = duffel_result.get("fare_family")

            message = formatter.format_alert(watch, price, currency, booking_url, fare_family)
            db.record_alert_sent(db_path, watch_id, price)
            await bot.send_message(chat_id=watch["user_id"], text=message)
            LOGGER.info("Alert sent for watch %s at %s %s", watch_id, price, currency)

        await asyncio.sleep(0.5)
