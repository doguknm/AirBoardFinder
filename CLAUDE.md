# CLAUDE.md

Guidance for Claude Code when working in the AirBoardFinder repository.

## Project Overview

A single-process Python Telegram bot that periodically queries flight prices for user-defined watches (origin, destination, dates, max price, currency) and sends Telegram alerts when prices drop to or below threshold. Users manage watches via Telegram commands (`/watch`, `/list`, `/delete`). Deduplication prevents alert spam when prices oscillate.

| Layer | Technology |
|---|---|
| Bot framework | python-telegram-bot v20 |
| Scheduler | APScheduler |
| Primary flight data | Travelpayouts Aviasales Data API (cached, free) |
| Pre-alert verification | Duffel API (real-time, pay-per-verify) |
| Fallback flight data | SunExpress Playwright scraper (TRY), then Pegasus Airlines Playwright scraper (EUR) |
| Storage | SQLite (3 tables: `watches`, `price_history`, `alerts_sent`) |
| Runtime | Python 3.12 |

## Read First

**`ARCHITECTURE.md`** in the repo root is the authoritative reference. Read it before touching the bot logic, scheduler, or database layer — it documents the polling flow, SQLite schema, deduplication rules, alert formatting, and known gotchas.

## Critical Technical Patterns

### Travelpayouts token goes in the header, not the URL
Authentication uses an `X-Access-Token` HTTP header, not a query parameter. Never put the token in the URL string — the endpoint is `GET https://api.travelpayouts.com/v1/prices/cheap` and the token is passed as `headers={"X-Access-Token": TRAVELPAYOUTS_TOKEN}`.

### Scraper currencies are fixed — normalize before comparing
SunExpress always requests and returns TRY; Pegasus always requests and returns EUR. Neither honours the watch's currency. `_normalize_price()` in `bot/scheduler.py` converts the scraper result to the watch's currency using `EUR_TRY_RATE` (default `54.0`) **before** the threshold comparison. Never compare a raw scraper price against `max_price`.

### Deduplication is two-layered and non-negotiable
An alert is only sent when: (1) no row exists in `alerts_sent` for this watch + price bucket, AND (2) the new price is at least 5% lower than the last alerted price. Removing either layer causes spam when prices oscillate around the threshold.

### SQLite connections must not be shared across threads
APScheduler jobs run in a thread pool separate from the Telegram handler threads. Each thread must open its own `sqlite3.connect()` — never store a single connection as a module-level global.

### Handlers have no user authorization
Any Telegram user who discovers the bot can create watches. This is intentional for personal use. If the bot is ever exposed publicly, add an `AUTHORIZED_USER_IDS` check in `handlers.py` before any DB write.

### DB_PATH is defined once in bot/db.py
`bot/db.py` exports `DB_PATH = "data/airboard.db"`. Both `main.py` and `handlers.py` import it from there. Do not redeclare it elsewhere.

## Debugging

Check `logs/bot.log` before inspecting code; then query the SQLite DB directly to verify watch/alert state.

| What | Where |
|---|---|
| Bot runtime logs | `logs/bot.log` |
| Inspect watches | `sqlite3 data/airboard.db "SELECT * FROM watches;"` |
| Inspect sent alerts | `sqlite3 data/airboard.db "SELECT * FROM alerts_sent ORDER BY sent_at DESC LIMIT 20;"` |
| API raw responses | Temporarily set `LOG_LEVEL=DEBUG` in `.env` |

## Development Workflow

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in credentials
cp .env.example .env

# Run the bot (blocking, Ctrl+C to stop)
python main.py

# Run tests
pytest

# Run tests with coverage
pytest --cov=bot --cov-report=term-missing
```

## Key File Locations

| What | Where |
|---|---|
| Entry point | `main.py` |
| Telegram command handlers | `bot/handlers.py` |
| APScheduler polling job | `bot/scheduler.py` |
| Travelpayouts API client | `bot/travelpayouts_client.py` |
| Duffel API client | `bot/duffel_client.py` |
| SunExpress scraper (fallback 1, TRY) | `bot/sunexpress_scraper.py` |
| Pegasus Airlines scraper (fallback 2, EUR) | `bot/pegasus_scraper.py` |
| Shared scraper helpers (`date_range`, `extract_price`) | `bot/scraper_utils.py` |
| SQLite DB operations + DB_PATH | `bot/db.py` |
| Alert formatter + aviasales_url | `bot/formatter.py` |
| Environment variable template | `.env.example` |
| SQLite database file | `data/airboard.db` |

## Recurring Problems

A living record of problems that have recurred or are likely to recur. Check this list when diagnosing unexpected behaviour before diving into code.

<!-- Entries are added here by the AI during tasks, not during setup. -->

## AI Tools

NOTEBOOKLM_NOTEBOOK_ID: 3b171a7a-55a1-4283-89a6-1a5ebc3098cc
