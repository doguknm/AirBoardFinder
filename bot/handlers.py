"""Telegram command handlers for AirBoardFinder."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from bot import db, scheduler
from bot.db import DB_PATH

WATCH_USAGE = (
    "Usage:\n"
    "  /watch <ORIG-DEST> <date> <max_price> [currency]\n"
    "  /watch <origin> <destination> <date_from> <date_to> <max_price> [currency]"
)
DELETE_USAGE = "Usage: /delete <watch_id>"
DEFAULT_CURRENCY = "TRY"


def _bot_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    application = getattr(context, "application", None)
    return getattr(application, "bot_data", {}) if application is not None else {}


def _db_path(context: ContextTypes.DEFAULT_TYPE) -> str:
    return _bot_data(context).get("db_path", DB_PATH)


def _user_id(update: Update) -> int:
    if update.effective_user is None:
        raise ValueError("Telegram update has no effective user.")
    return update.effective_user.id


async def _reply(update: Update, text: str) -> None:
    message = update.effective_message or update.message
    if message is None:
        return
    await message.reply_text(text)


def _valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


async def watch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /watch <origin> <destination> <date_from> <date_to> <max_price> [currency]."""
    args = list(getattr(context, "args", []) or [])
    if args and "-" in args[0] and args[0].count("-") == 1 and not args[0][0].isdigit():
        origin, destination = args[0].split("-", 1)
        remaining = args[1:]
    elif len(args) >= 4:
        origin, destination = args[0], args[1]
        remaining = args[2:]
    else:
        await _reply(update, WATCH_USAGE)
        return

    if len(remaining) == 2:
        date_from = date_to = remaining[0]
        max_price_raw = remaining[1]
        currency = DEFAULT_CURRENCY
    elif len(remaining) == 3:
        if _valid_iso_date(remaining[1]):
            date_from, date_to, max_price_raw = remaining
            currency = DEFAULT_CURRENCY
        else:
            date_from = date_to = remaining[0]
            max_price_raw = remaining[1]
            currency = remaining[2].upper()
    elif len(remaining) == 4:
        date_from, date_to, max_price_raw = remaining[0], remaining[1], remaining[2]
        currency = remaining[3].upper()
    else:
        await _reply(update, WATCH_USAGE)
        return
    try:
        max_price = float(max_price_raw)
    except ValueError:
        await _reply(update, "Max price must be a positive number.")
        return

    if max_price <= 0:
        await _reply(update, "Max price must be a positive number.")
        return

    if not _valid_iso_date(date_from) or not _valid_iso_date(date_to):
        await _reply(update, "Dates must be valid ISO-8601 dates in YYYY-MM-DD format.")
        return

    db_path = _db_path(context)
    user_id = _user_id(update)

    watch_id = db.create_watch(
        db_path,
        user_id,
        origin,
        destination,
        date_from,
        date_to,
        max_price,
        currency,
    )
    await _reply(
        update,
        (
            f"Watch created (ID: {watch_id}). I'll alert you when "
            f"{origin} → {destination} drops to {max_price} {currency} or below. "
            f"Checking current price now..."
        ),
    )

    bot_data = _bot_data(context)
    tp_token = bot_data.get("travelpayouts_token", "")
    duffel_key = bot_data.get("duffel_api_key", "")
    if tp_token:
        watch_dict = {
            "id": watch_id,
            "user_id": user_id,
            "origin": origin,
            "destination": destination,
            "date_from": date_from,
            "date_to": date_to,
            "max_price": max_price,
            "currency": currency,
        }
        asyncio.create_task(
            scheduler.poll_single_watch(
                context.application.bot,
                db_path,
                watch_dict,
                tp_token,
                duffel_key,
                notify_always=True,
            )
        )


def _format_watch_line(watch: dict[str, Any]) -> str:
    currency = watch.get("currency", DEFAULT_CURRENCY)
    return (
        f"[{watch['id']}] {watch['origin']}→{watch['destination']} "
        f"{watch['date_from']}–{watch['date_to']} max {watch['max_price']} {currency}"
    )


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list."""
    watches = db.get_watches_for_user(_db_path(context), _user_id(update))
    if not watches:
        await _reply(update, "You have no active watches.")
        return

    await _reply(update, "\n".join(_format_watch_line(watch) for watch in watches))


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete <watch_id>."""
    args = list(getattr(context, "args", []) or [])
    if len(args) != 1:
        await _reply(update, DELETE_USAGE)
        return

    try:
        watch_id = int(args[0])
    except ValueError:
        await _reply(update, DELETE_USAGE)
        return

    deleted = db.delete_watch(_db_path(context), watch_id, _user_id(update))
    if not deleted:
        await _reply(update, "Watch not found or does not belong to you.")
        return

    await _reply(update, f"Watch {watch_id} deleted.")
