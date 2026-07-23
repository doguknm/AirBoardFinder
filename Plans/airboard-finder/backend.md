# Backend — AirBoardFinder

**Lane**: backend
**Tool**: Codex CLI
**Status**: not started
**Brief**: ./2026-05-08-summary.md
**Depends on**: ./database.md (must be implemented and reviewed first)

## Goal

Implement the complete Python 3.12 Telegram bot: project scaffold, SQLite data layer, Kiwi Tequila API client with fast-flights fallback, alert formatter, Telegram command handlers, APScheduler polling job, and entry point. Also produce the required project documentation files before any bot logic is written.

---

## Implementation Order

Implement in this strict order to respect dependencies:

1. Project scaffold (required files)
2. `bot/db.py` — schema init + CRUD + deduplication
3. `bot/kiwi_client.py` — Kiwi HTTP client + fast-flights fallback
4. `bot/amadeus_client.py` — Amadeus Flight Offers Search API client
5. `bot/sunexpress_scraper.py` — Playwright scraper for SunExpress
6. `bot/formatter.py` — alert message formatter
7. `bot/handlers.py` — Telegram command handlers
8. `bot/scheduler.py` — APScheduler polling job
9. `main.py` — entry point
10. `docs/adr/001-apscheduler-integration.md` — ADR

---

## 1. Project Scaffold

The following files must be created before any bot logic is written (required by global CLAUDE.md):

| File | Purpose |
|---|---|
| `ARCHITECTURE.md` | Authoritative architecture reference — **pre-created, do not overwrite** |
| `CONTRIBUTING.md` | Dev workflow, test commands, setup steps |
| `CHANGELOG.md` | Unreleased changelog with initial entry |
| `docs/adr/001-apscheduler-integration.md` | ADR for AsyncIOScheduler choice |
| `.env.example` | Template for required environment variables |
| `requirements.txt` | Pinned Python dependencies |
| `README.md` | Project overview and quickstart |
| `logs/` | Directory (empty, gitignored) |
| `data/` | Directory (empty, gitignored) |
| `bot/__init__.py` | Empty package init |

### `.env.example` contents

```
TELEGRAM_TOKEN=your_telegram_bot_token_here
KIWI_API_KEY=your_kiwi_tequila_api_key_here
AMADEUS_CLIENT_ID=your_amadeus_client_id_here
AMADEUS_CLIENT_SECRET=your_amadeus_client_secret_here
LOG_LEVEL=INFO
```

### `requirements.txt` packages (minimum set, pin exact versions)

```
python-telegram-bot==20.*
APScheduler==3.*
fast-flights
python-dotenv
httpx
amadeus
playwright
playwright-stealth
pytest
pytest-cov
pytest-asyncio
```

TODO: Pin exact versions once the implementer confirms compatible release numbers for python-telegram-bot 20.x and APScheduler 3.x.

**Post-install step required:** `python -m playwright install chromium` — pip does not install the browser binary automatically.

---

## 2. `bot/db.py`

### `init_db(db_path: str) -> None`

Runs all `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements from `database.md`. Called once from `main.py` at startup. Must open and close its own connection.

### `create_watch(db_path, user_id, origin, destination, date_from, date_to, max_price) -> int`

Inserts a row into `watches` (is_active=1). Returns the new row `id`.

### `get_watches_for_user(db_path, user_id) -> list[dict]`

Returns all active watches (`is_active=1`) for the given `user_id`. Returns an empty list if none exist.

### `get_all_active_watches(db_path) -> list[dict]`

Returns all rows in `watches` where `is_active=1`. Used by the scheduler job.

### `delete_watch(db_path, watch_id, user_id) -> bool`

Sets `is_active=0` for the row matching `watch_id` AND `user_id`. Returns `True` if a row was updated, `False` if no matching row found (ownership check fails silently — the handler layer reports the error to the user).

### `insert_price_history(db_path, watch_id, price, currency, booking_url) -> None`

Inserts one row into `price_history`. Called for every poll result regardless of whether an alert fires.

### `should_send_alert(db_path, watch_id, price) -> bool`

Two-layered deduplication — the single testable function that encapsulates both rules:

1. **Layer 1 (exact price):** Query `alerts_sent` for any row matching `(watch_id, price)`. If a row exists, return `False`.
2. **Layer 2 (5% drop):** Query `alerts_sent` for the most recent row for `watch_id`. If one exists and `price > last_alerted_price * 0.95`, return `False`. (New price must be at least 5% lower than the last alerted price to fire again.)
3. If both layers pass, return `True`.

Note: `should_send_alert` does not insert into `alerts_sent` itself. The caller (`scheduler.py`) inserts the row after a successful Telegram send.

### `record_alert_sent(db_path, watch_id, price) -> None`

Inserts one row into `alerts_sent`. Called by the scheduler only after a Telegram message is confirmed sent.

---

## 3. `bot/kiwi_client.py`

### `fetch_price(origin, destination, date_from, date_to, api_key) -> dict | None`

- Makes `GET https://api.tequila.kiwi.com/v2/search` with:
  - Header: `{"apiKey": api_key}` — never a query parameter.
  - Query params: `fly_from`, `fly_to`, `date_from`, `date_to`, `curr=EUR`, `limit=1`, `sort=price`.
- Returns the cheapest result as a dict with keys: `price` (float), `currency` (str), `booking_url` (str). Returns `None` if the response contains no results.
- Logs the raw response body at `DEBUG` level.
- On HTTP error (non-2xx), logs at `ERROR` level and returns `None`.

### Fast-flights fallback (inline in `fetch_price` or a private helper)

- Called only when Kiwi returns no results (empty `data` array or `None` response).
- Logs `WARNING: Kiwi returned no results for {origin}-{destination}, falling back to fast-flights`.
- Uses `fast-flights` to query the same route and date range.
- Returns the same dict shape as the Kiwi path, or `None` if fast-flights also fails.
- If fast-flights raises any exception (protobuf schema breakage), catches it, logs `WARNING: fast-flights fallback failed: {exc}`, and returns `None`.

---

## 4. `bot/amadeus_client.py`

### `fetch_price(origin, destination, date_from, date_to) -> dict | None`

- Uses the official `amadeus` Python SDK (OAuth2 client credentials — `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` from env).
- Calls Amadeus Flight Offers Search v2 for the cheapest one-way fare.
- Returns the same dict shape as `kiwi_client.py`: `{"price": float, "currency": str, "booking_url": str}`.
- Returns `None` if no offers returned or on any API error.
- Logs at `ERROR` level on API errors; `DEBUG` level for raw response.
- The SDK handles OAuth2 token renewal automatically — do not manage tokens manually.

---

## 5. `bot/sunexpress_scraper.py`

### `fetch_price(origin, destination, date_from, date_to) -> dict | None` (async)

- Uses `async_playwright()` with `playwright-stealth`'s `stealth_async(page)` applied immediately after page creation to hide `navigator.webdriver` and other CDP artifacts.
- Navigates to the SunExpress flight search URL, fills in route and date fields, extracts the cheapest displayed price.
- Returns the same dict shape: `{"price": float, "currency": str, "booking_url": str}`.
- On **any** exception (page structure change, timeout, bot block): log `WARNING: SunExpress scraper failed: {exc}`, return `None`. Never raise.
- Must close the browser via context manager before returning — do not leak browser processes.
- `booking_url` should be the direct sunexpress.com search result URL if a deep link is not available.

---

## 6. `bot/formatter.py`

### `format_alert(watch: dict, price: float, currency: str, booking_url: str) -> str`

Returns a Telegram-formatted plain-text (or MarkdownV2) message string. Must include:

- Route: `{origin} → {destination}`
- Travel dates: `{date_from} – {date_to}`
- Price: `{price} {currency}`
- Booking URL (full URL, no URL shortener)
- Watch threshold for context: `Your alert threshold: {max_price} {currency}`

Example output shape (exact formatting is implementation detail, but all fields must be present):

```
Flight alert: IST → LHR
Dates: 2026-06-01 – 2026-06-10
Price: 189.0 EUR  (your threshold: 200.0 EUR)
Book: https://www.kiwi.com/...
```

---

## 8. `bot/handlers.py`

All handlers use `python-telegram-bot` v20 async pattern (`async def`, `update: Update`, `context: ContextTypes.DEFAULT_TYPE`).

### `/watch` handler

Command signature: `/watch <origin> <destination> <date_from> <date_to> <max_price>`

- Parse 5 arguments from `context.args`. If count != 5, reply with usage string and return.
- Validate `max_price` is a positive float. On failure, reply with error and return.
- Validate `date_from` and `date_to` are valid ISO-8601 date strings (`YYYY-MM-DD`). On failure, reply with error and return.
- Call `db.create_watch(...)` with `user_id = update.effective_user.id`.
- Reply: `Watch created (ID: {id}). I'll alert you when {origin} → {destination} drops to {max_price} EUR or below.`

### `/list` handler

- Call `db.get_watches_for_user(...)` with `user_id = update.effective_user.id`.
- If empty list, reply: `You have no active watches.`
- Otherwise reply with a formatted list: one watch per line, showing ID, route, dates, threshold.

### `/delete` handler

Command signature: `/delete <watch_id>`

- Parse 1 argument. If missing or not an integer, reply with usage string and return.
- Call `db.delete_watch(...)` with `watch_id` and `user_id = update.effective_user.id`.
- If `False` returned: reply `Watch not found or does not belong to you.`
- If `True` returned: reply `Watch {watch_id} deleted.`

---

## 9. `bot/scheduler.py`

### `poll_all_watches(bot, db_path, kiwi_api_key, amadeus_client_id, amadeus_client_secret) -> None` (async)

This is the APScheduler job function. It is an `async def` because it posts Telegram messages via `await bot.send_message(...)`.

Steps:

1. Call `db.get_all_active_watches(db_path)`.
2. For each watch:
   a. **Fetch price via fallback chain:**
      - Try `kiwi_client.fetch_price(origin, destination, date_from, date_to, kiwi_api_key)`.
      - If `None`, try `amadeus_client.fetch_price(origin, destination, date_from, date_to)`.
      - If still `None`, try `await sunexpress_scraper.fetch_price(origin, destination, date_from, date_to)`.
      - If all return `None`, log `INFO: No price found for watch {id} from any source, skipping.` and continue.
   b. Call `db.insert_price_history(db_path, watch_id, price, currency, booking_url)`.
   c. If `price <= watch['max_price']` AND `db.should_send_alert(db_path, watch_id, price)`:
      - Call `formatter.format_alert(watch, price, currency, booking_url)`.
      - `await bot.send_message(chat_id=watch['user_id'], text=message)`.
      - Call `db.record_alert_sent(db_path, watch_id, price)`.
      - Log `INFO: Alert sent for watch {id} at {price} {currency}`.
3. Add `await asyncio.sleep(0.5)` between watch iterations to respect Kiwi rate limits.

### Scheduler wiring (called from `main.py`)

```python
# Pseudocode — not final code
scheduler = AsyncIOScheduler()
scheduler.add_job(
    poll_all_watches,
    trigger='interval',
    minutes=60,
    args=[application.bot, DB_PATH, KIWI_API_KEY, AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET],
    id='poll_watches',
    replace_existing=True,
)
scheduler.start()
```

The scheduler uses `AsyncIOScheduler` (see ADR below and `docs/adr/001-apscheduler-integration.md`).

---

## 10. `main.py`

Responsibilities in order:

1. `load_dotenv()` — load `.env` into environment.
2. Read `TELEGRAM_TOKEN`, `KIWI_API_KEY`, `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET`, `LOG_LEVEL` from `os.environ`. Raise `ValueError` with a clear message if any required key is missing.
3. Configure `logging`: root logger at `LOG_LEVEL`; file handler to `logs/bot.log`; stream handler to stdout.
4. Call `db.init_db(DB_PATH)`.
5. Build `Application` via `ApplicationBuilder().token(TELEGRAM_TOKEN).build()`.
6. Register handlers: `CommandHandler("watch", handlers.watch_handler)`, etc.
7. Create `AsyncIOScheduler`, add the `poll_all_watches` job, call `scheduler.start()`.
8. Call `application.run_polling()` (blocking).
9. On `KeyboardInterrupt` / shutdown: `scheduler.shutdown()`.

Constants at module top:

```
DB_PATH = "data/airboard.db"
```

---

## 11. ADR: `docs/adr/001-apscheduler-integration.md`

**Decision: Use `AsyncIOScheduler` (not `BackgroundScheduler`).**

The ADR document must cover:

| Section | Content |
|---|---|
| Status | Accepted |
| Context | python-telegram-bot v20 runs a single `asyncio` event loop. APScheduler offers two relevant schedulers. |
| Options considered | (1) `AsyncIOScheduler` — schedules coroutines on the existing event loop; `await bot.send_message()` works directly inside the job. (2) `BackgroundScheduler` — runs jobs in a `ThreadPoolExecutor`; sending Telegram messages requires `asyncio.run_coroutine_threadsafe(coro, loop)`, introducing cross-thread complexity and a need to capture the event loop reference at startup. |
| Decision | `AsyncIOScheduler` on the same event loop that `application.run_polling()` manages. |
| Rationale | Simpler: no `asyncio.run_coroutine_threadsafe` boilerplate, no stored event loop reference, no thread-safety concerns around the bot object. The job function is already `async def`, so there is no execution model mismatch. `BackgroundScheduler` would add complexity without benefit at this scale. |
| Consequences | The polling job shares the event loop with Telegram updates. A blocking HTTP call inside the job would stall the event loop. **Confirmed mitigation: use `httpx.AsyncClient()` with `await` inside `fetch_price` — never `requests.get`.** The ADR Consequences section must document this choice and explain why `requests` is banned from `bot/kiwi_client.py`. |
| Known risk | Kiwi Tequila free-tier rate limits are undocumented. If many watches are active, rapid successive requests may trigger throttling. A small `asyncio.sleep(0.5)` between per-watch requests is recommended as a precaution. |

---

## Endpoints

This is a Telegram bot — there are no HTTP endpoints exposed by the service itself. Outbound calls:

| Method | URL | Auth | Notes |
|---|---|---|---|
| GET | `https://api.tequila.kiwi.com/v2/search` | Header `apiKey: {KIWI_API_KEY}` | Primary source |
| POST | Amadeus OAuth2 token endpoint | Client credentials | SDK-managed |
| GET | Amadeus Flight Offers Search v2 | Bearer token (SDK-managed) | Secondary source |
| Browser | `https://www.sunexpress.com` | None | Playwright scraper, last resort |

---

## Schema Dependencies

All from `database.md`:

- `watches.id`, `watches.user_id`, `watches.origin`, `watches.destination`, `watches.date_from`, `watches.date_to`, `watches.max_price`, `watches.is_active`
- `price_history.watch_id`, `price_history.price`, `price_history.currency`, `price_history.booking_url`
- `alerts_sent.watch_id`, `alerts_sent.price`, `alerts_sent.sent_at`

---

## Auth and Permissions

- **Telegram user scoping:** Every handler reads `update.effective_user.id` as the user identifier. No separate login flow.
- **Watch ownership:** `/delete` must verify `user_id` matches the watch's stored `user_id`. The `db.delete_watch` function enforces this at the SQL level (`WHERE id = ? AND user_id = ?`).
- **API keys:** Loaded from `.env` at startup. Never logged. Never passed as URL query parameters.
- **Amadeus OAuth2:** `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET` loaded from `.env`. Token renewal handled by the SDK — do not manage tokens manually.

---

## Acceptance Criteria

- AC1: `/watch <origin> <destination> <date_from> <date_to> <max_price>` stores a watch row and replies with the watch ID.
- AC2: `/list` returns all active watches for the calling user; replies gracefully when none exist.
- AC3: `/delete <watch_id>` soft-deletes the watch and confirms; rejects IDs belonging to other users.
- AC4: APScheduler job fires every 60 minutes, queries Kiwi → Amadeus → SunExpress scraper (fallback chain) for each active watch, stores results in `price_history`.
- AC5: Alert is sent when price <= max_price AND both deduplication layers pass.
- AC6: No duplicate alert for the same watch+price unless new price is >= 5% lower than last alerted price.
- AC7: When Kiwi returns no results, Amadeus is tried next; if Amadeus also returns None, SunExpress Playwright scraper is tried; a WARNING is logged at each fallback step.
- AC8: `TELEGRAM_TOKEN`, `KIWI_API_KEY`, `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` are read from `.env`; `.env.example` documents all required keys; no key ever appears in a URL or log line.
- AC11: `amadeus_client.fetch_price` returns a valid dict on a live Amadeus sandbox call (or mocked equivalent in tests).
- AC12: `sunexpress_scraper.fetch_price` returns `None` gracefully (logged WARNING) on any exception — never raises.
- AC9: `pytest` suite passes (see `tests.md`).
- AC10: `logs/bot.log` receives INFO-level events at runtime; DEBUG-level Kiwi responses when `LOG_LEVEL=DEBUG`.
- AC-SCAFFOLD: `ARCHITECTURE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/adr/001-apscheduler-integration.md`, `.env.example`, `requirements.txt`, `README.md` all exist before any bot logic is committed.

---

## Out of Scope

- Multi-city or flexible-date searches
- Celery / Redis / PostgreSQL
- Web dashboard or any non-Telegram UI
- User authentication beyond Telegram user ID
- Flash-sale detection (sub-60-minute polling)
- Airline or cabin-class filtering
- Database migration toolchain
