"""Telegram command handlers for AirBoardFinder."""

from __future__ import annotations

from datetime import date
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from bot import db


DB_PATH = "data/airboard.db"
WATCH_USAGE = "Usage: /watch <origin> <destination> <date_from> <date_to> <max_price>"
DELETE_USAGE = "Usage: /delete <watch_id>"


def _db_path(context: ContextTypes.DEFAULT_TYPE) -> str:
    application = getattr(context, "application", None)
    bot_data = getattr(application, "bot_data", {}) if application is not None else {}
    return bot_data.get("db_path", DB_PATH)


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
    """Handle /watch <origin> <destination> <date_from> <date_to> <max_price>."""
    args = list(getattr(context, "args", []) or [])
    if len(args) != 5:
        await _reply(update, WATCH_USAGE)
        return

    origin, destination, date_from, date_to, max_price_raw = args
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

    watch_id = db.create_watch(
        _db_path(context),
        _user_id(update),
        origin,
        destination,
        date_from,
        date_to,
        max_price,
    )
    await _reply(
        update,
        (
            f"Watch created (ID: {watch_id}). I'll alert you when "
            f"{origin} → {destination} drops to {max_price} EUR or below."
        ),
    )


def _format_watch_line(watch: dict[str, Any]) -> str:
    return (
        f"[{watch['id']}] {watch['origin']}→{watch['destination']} "
        f"{watch['date_from']}–{watch['date_to']} max {watch['max_price']} EUR"
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
