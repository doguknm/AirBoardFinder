"""AirBoardFinder entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler

from bot import db, handlers
from bot.scheduler import poll_all_watches


DB_PATH = "data/airboard.db"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _configure_logging(log_level: str) -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def main() -> None:
    load_dotenv()

    telegram_token = _required_env("TELEGRAM_TOKEN")
    kiwi_api_key = _required_env("KIWI_API_KEY")
    amadeus_client_id = _required_env("AMADEUS_CLIENT_ID")
    amadeus_client_secret = _required_env("AMADEUS_CLIENT_SECRET")
    log_level = os.environ.get("LOG_LEVEL", "INFO")

    _configure_logging(log_level)
    Path("data").mkdir(parents=True, exist_ok=True)
    db.init_db(DB_PATH)

    application = ApplicationBuilder().token(telegram_token).build()
    application.bot_data["db_path"] = DB_PATH

    application.add_handler(CommandHandler("watch", handlers.watch_handler))
    application.add_handler(CommandHandler("list", handlers.list_handler))
    application.add_handler(CommandHandler("delete", handlers.delete_handler))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_all_watches,
        trigger="interval",
        minutes=60,
        args=[
            application.bot,
            DB_PATH,
            kiwi_api_key,
        ],
        id="poll_watches",
        replace_existing=True,
    )
    scheduler.start()

    try:
        application.run_polling()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
