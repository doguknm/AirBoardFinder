# ARCHITECTURE.md — AirBoardFinder

Authoritative technical reference. Read this before touching any module.

---

## System Purpose

AirBoardFinder is a single-process Python 3.12 Telegram bot that monitors flight prices on behalf of registered users. Every 60 minutes APScheduler fires a polling job that queries the Travelpayouts Aviasales Data API (free, cached) for each active watch (origin, destination, date range, price threshold + currency stored in SQLite). When a cached price is at or below the user's threshold and passes a two-layer deduplication check, the bot makes a single real-time Duffel API call to verify the fare is still bookable before sending a Telegram alert. Users create and manage watches via three Telegram commands: `/watch`, `/list`, `/delete`. The default currency throughout the system is **TRY**; EUR is also supported and converted automatically via a configurable `EUR_TRY_RATE`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Bot framework | python-telegram-bot 20.x |
| Scheduler | APScheduler 3.x (AsyncIOScheduler) |
| Primary flight data | Travelpayouts Aviasales Data API (cached, free) |
| Pre-alert verification | Duffel API (real-time, pay-per-verify) |
| HTTP client | httpx (async) |
| Storage | SQLite 3 (stdlib `sqlite3`, no ORM) |
| Fallback 1 | SunExpress scraper (Playwright) |
| Fallback 2 | Pegasus Airlines scraper (Playwright) |
| Runtime | Python 3.12 |
| Config | python-dotenv |

---

## Directory Layout

```
AirBoardFinder/
├── main.py                          # Entry point: env, DB init, bot + scheduler, run_polling()
├── bot/
│   ├── __init__.py
│   ├── db.py                        # Schema init, watches CRUD, deduplication, price history
│   ├── travelpayouts_client.py      # Travelpayouts Aviasales Data API — primary polling source
│   ├── duffel_client.py             # Duffel API — pre-alert price verification
│   ├── sunexpress_scraper.py        # SunExpress Playwright scraper — fallback 1
│   ├── pegasus_scraper.py           # Pegasus Airlines Playwright scraper — fallback 2
│   ├── formatter.py                 # Alert message formatter + aviasales_url()
│   ├── handlers.py                  # Telegram command handlers (/watch, /list, /delete)
│   └── scheduler.py                 # APScheduler job: poll all active watches
├── data/
│   └── airboard.db                  # SQLite database file (auto-created on first run, gitignored)
├── logs/
│   └── bot.log                      # Runtime log file (gitignored)
├── docs/
│   └── adr/
│       └── 001-apscheduler-integration.md
├── .env                             # Credentials (gitignored)
├── .env.example                     # Credential template (committed)
├── requirements.txt
├── ARCHITECTURE.md                  # This file
├── AGENTS.md
├── CLAUDE.md
├── CONTRIBUTING.md
├── CHANGELOG.md
└── README.md
```

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `main.py` | Load `.env`, validate required env vars, configure logging (file + stdout), call `db.init_db()`, build Telegram `Application`, register command handlers, create `AsyncIOScheduler` with polling job, call `application.run_polling()` (blocking), shut down scheduler on exit |
| `bot/db.py` | `init_db()` — `CREATE TABLE IF NOT EXISTS` for all 3 tables + 5 indexes. Watches CRUD (`create_watch`, `get_watches_for_user`, `get_all_active_watches`, `delete_watch`). `should_send_alert()` — two-layer deduplication (read-only). `insert_price_history()`, `record_alert_sent()`. Connection-per-call — no shared global connection. |
| `bot/travelpayouts_client.py` | `fetch_price()` — async GET to Travelpayouts Aviasales Data API with `X-Access-Token` header. Returns cached price (48h–7d) as `{price, currency, booking_url, airline}` or `None`. |
| `bot/duffel_client.py` | `verify_price()` — async POST to Duffel offer-requests endpoint. Returns cheapest real-time offer with `{price, currency, booking_url, fare_family}` or `None`. Never used for booking — verification only. |
| `bot/formatter.py` | `format_alert()` — produces the Telegram message string from watch + price data. Optional `fare_family` parameter adds a "Fare:" line when provided. `aviasales_url()` — shared Aviasales deep-link builder used by all three API clients. |
| `bot/handlers.py` | Async handlers for `/watch` (create), `/list` (read), `/delete` (soft-delete). `/watch` accepts optional 6th arg for currency (default EUR). All operations scoped to `update.effective_user.id`. |
| `bot/sunexpress_scraper.py` | `fetch_price()` — Playwright headless Chromium scraper for SunExpress (`sunexpress.com/en-gb/booking/select/`). Iterates one URL per date in the watch range (single-date search limitation). Always requests and returns **TRY** prices. Never raises outward. |
| `bot/pegasus_scraper.py` | `fetch_price()` — Playwright headless Chromium scraper for Pegasus Airlines (`web.flypgs.com/booking`). Iterates one URL per date in the watch range. Always requests and returns **EUR** prices. Never raises outward. |
| `bot/scheduler.py` | `poll_all_watches(bot, db_path, travelpayouts_token, duffel_api_key)` — async APScheduler job. Polling chain: Travelpayouts → SunExpress → Pegasus. `_normalize_price()` converts scraper results to the watch's currency (EUR↔TRY via `EUR_TRY_RATE`) before threshold comparison. |

---

## Data Flows

### Polling flow (fires every 60 minutes)

```
AsyncIOScheduler
  └─ poll_all_watches(bot, db_path, travelpayouts_token, duffel_api_key)
       └─ db.get_all_active_watches(db_path)
            └─ for each watch:
                 travelpayouts_client.fetch_price(origin, dest, date_from, token, currency)
                   └─ GET https://api.travelpayouts.com/v1/prices/cheap
                        [header: X-Access-Token: ...]
                        ├─ data[dest] found → return {price, currency, booking_url, airline}
                        └─ no data → return None
                 if None → sunexpress_scraper.fetch_price(...)  [fallback 1, returns TRY]
                 if None → pegasus_scraper.fetch_price(...)    [fallback 2, returns EUR]
                 if None → skip watch (log INFO)
                 _normalize_price(price, src_currency, watch_currency)
                   [converts TRY↔EUR via EUR_TRY_RATE when currencies differ]
                 db.insert_price_history(db_path, watch_id, price, currency, booking_url)
                 if price <= watch["max_price"]:
                   db.should_send_alert(db_path, watch_id, price)
                     ├─ False → skip (deduplication blocked)
                     └─ True  →
                          duffel_client.verify_price(origin, dest, date_from, api_key, currency)
                            ├─ None → use polled price (Duffel failure must not suppress alert)
                            ├─ price > max_price → suppress alert (cached price was stale)
                            └─ price <= max_price → use Duffel price + fare_family
                          formatter.format_alert(watch, price, currency, booking_url, fare_family)
                          db.record_alert_sent(db_path, watch_id, price)
                          await bot.send_message(chat_id=watch["user_id"], text=message)
                          LOG INFO: Alert sent for watch {id} at {price} {currency}
```

### Command flow (user sends a Telegram command)

```
Telegram update received
  └─ python-telegram-bot dispatcher
       └─ handlers.py (async handler function)
            ├─ parse + validate args from context.args
            ├─ db.create_watch() | get_watches_for_user() | delete_watch()
            └─ await update.message.reply_text(reply_string)
```

---

## SQLite Schema

### `watches`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `user_id` | INTEGER | NOT NULL | Telegram user ID |
| `origin` | TEXT | NOT NULL | IATA code, e.g. `"IST"` |
| `destination` | TEXT | NOT NULL | IATA code, e.g. `"LHR"` |
| `date_from` | TEXT | NOT NULL | ISO-8601 date string `"YYYY-MM-DD"` |
| `date_to` | TEXT | NOT NULL | ISO-8601 date string `"YYYY-MM-DD"` |
| `max_price` | REAL | NOT NULL | User's price threshold |
| `currency` | TEXT | NOT NULL DEFAULT `'TRY'` | ISO 4217 currency code (e.g. `"TRY"`, `"EUR"`) — added via `ALTER TABLE` on startup |
| `created_at` | TEXT | NOT NULL DEFAULT (datetime('now')) | |
| `is_active` | INTEGER | NOT NULL DEFAULT 1 | 1 = active, 0 = soft-deleted |

### `price_history`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `watch_id` | INTEGER | NOT NULL REFERENCES watches(id) | |
| `price` | REAL | NOT NULL | |
| `currency` | TEXT | NOT NULL DEFAULT 'EUR' | |
| `booking_url` | TEXT | NOT NULL | |
| `checked_at` | TEXT | NOT NULL DEFAULT (datetime('now')) | |

### `alerts_sent`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `watch_id` | INTEGER | NOT NULL REFERENCES watches(id) | |
| `price` | REAL | NOT NULL | Price at the time the alert fired |
| `sent_at` | TEXT | NOT NULL DEFAULT (datetime('now')) | |

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_watches_user_id     ON watches(user_id);
CREATE INDEX IF NOT EXISTS idx_watches_is_active    ON watches(is_active);
CREATE INDEX IF NOT EXISTS idx_price_history_watch  ON price_history(watch_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_watch    ON alerts_sent(watch_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_dedup    ON alerts_sent(watch_id, price);
```

### Threading constraint

SQLite connections must not be shared across threads. The `AsyncIOScheduler` job and Telegram handler coroutines both execute on the same asyncio event loop but `sqlite3` uses OS thread affinity. Every function in `bot/db.py` must open its own `sqlite3.connect(DB_PATH)` using a `with` context manager and close it before returning. No connection object stored at module scope.

---

## Deduplication Algorithm

`db.should_send_alert(db_path, watch_id, price) -> bool`

```python
# Layer 1 — exact price check
row = SELECT COUNT(*) FROM alerts_sent WHERE watch_id = ? AND price = ?
if count > 0:
    return False  # this exact price was already alerted for this watch

# Layer 2 — 5% additional-drop check
row = SELECT price FROM alerts_sent WHERE watch_id = ? ORDER BY sent_at DESC LIMIT 1
if row exists:
    last_alerted_price = row.price
    if price > last_alerted_price * 0.95:
        return False  # new price is less than 5% lower than last alert

# Both layers passed
return True
```

**Boundary:** `price == last_alerted_price * 0.95` → condition `price > last * 0.95` is `False` → function returns `True` → alert fires. A drop of exactly 5% triggers an alert.

**Important:** `should_send_alert` is read-only. It does not insert into `alerts_sent`. The caller (`scheduler.py`) must call `db.record_alert_sent()` after a confirmed Telegram send.

---

## External API Contracts

### Travelpayouts Aviasales Data API (primary poller)

| Field | Value |
|---|---|
| Method | `GET` |
| URL | `https://api.travelpayouts.com/v1/prices/cheap` |
| Auth | HTTP header `X-Access-Token: {TRAVELPAYOUTS_TOKEN}` — **never a query parameter** |
| `origin` | Origin IATA code |
| `destination` | Destination IATA code |
| `currency` | ISO 4217 code; TRY support is undocumented — API may reject it |
| `depart_date` | `YYYY-MM-DD` format |
| `one_way` | `true` |

**Response shape:**
```json
{
  "data": {
    "ANK": {
      "0": { "price": 120.0, "airline": "TK", "..." : "..." }
    }
  }
}
```

**Result extraction:** pick the entry with the lowest `price` across all keys under `data[destination]`. Booking URL is constructed as `https://www.aviasales.com/search/{origin}{DDMM}{destination}1`.

**No results / destination absent:** log `WARNING`, return `None`.

**HTTP error (non-2xx):** log at `ERROR` level, return `None`. Do not raise.

**Debug logging:** log raw response body at `DEBUG` level on every call.

---

### Duffel API (pre-alert verifier)

| Field | Value |
|---|---|
| Method | `POST` |
| URL | `https://api.duffel.com/air/offer_requests?return_offers=true` |
| Auth | HTTP header `Authorization: Bearer {DUFFEL_API_KEY}` |
| `Duffel-Version` header | `v2` |
| Body | `{"data": {"slices": [...], "passengers": [{"type": "adult"}], "cabin_class": "economy"}}` |

**Response shape:**
```json
{
  "data": {
    "offers": [
      {
        "total_amount": "135.00",
        "total_currency": "EUR",
        "slices": [{ "fare_brand_name": "EcoFly" }]
      }
    ]
  }
}
```

**Result extraction:** pick the offer with the lowest `total_amount`. `fare_family = slices[0]["fare_brand_name"]` (may be `null`).

**No offers / error:** log `WARNING`/`ERROR`, return `None`. Callers must treat `None` as non-fatal — Duffel failure must never suppress an alert.

**Cost model:** $0.005 per call beyond the 1500:1 search-to-book ratio. For this personal bot (no booking flow, zero orders), every verify call incurs the fee. At rare alert thresholds this is negligible; see `docs/adr/002-duffel-verification.md`.

---

## Telegram Command Interface

| Command | Signature | Success reply | Error reply |
|---|---|---|---|
| `/watch` | `/watch <origin> <destination> <date_from> <date_to> <max_price> [currency]` — currency defaults to `TRY` | `Watch created (ID: {id}). I'll alert you when {origin} → {destination} drops to {max_price} {currency} or below.` | Usage string or validation error message |
| `/list` | `/list` | Formatted list — one watch per line: `[{id}] {origin}→{destination} {date_from}–{date_to} max {max_price} {currency}` | `You have no active watches.` |
| `/delete` | `/delete <watch_id>` | `Watch {watch_id} deleted.` | `Watch not found or does not belong to you.` |

- All operations are scoped to `update.effective_user.id`.
- `/delete` enforces ownership at the SQL level: `WHERE id = ? AND user_id = ?`.
- `/watch` validates: arg count == 5 or 6, `max_price` is positive float, `date_from` and `date_to` are valid `YYYY-MM-DD`. Currency defaults to `EUR` when omitted. On failure: reply with usage string, no DB write.
- **No allowlist/authorization check.** Any Telegram user who finds the bot can create watches. This is intentional for personal use — if you expose the bot publicly, add an `AUTHORIZED_USER_IDS` check before any DB write.

---

## Configuration Reference

| Variable | Required | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `TRAVELPAYOUTS_TOKEN` | Yes | Travelpayouts Data API token (free, from travelpayouts.com) |
| `DUFFEL_API_KEY` | Yes | Duffel API key (from app.duffel.com) |
| `LOG_LEVEL` | No (default `INFO`) | Python logging level |
| `EUR_TRY_RATE` | No (default `54.0`) | Exchange rate used to convert Pegasus (EUR) prices to TRY and vice versa |

`DB_PATH` is defined once in `bot/db.py` (`"data/airboard.db"`) and imported by `main.py` and `handlers.py`. Not env-configurable.

---

## Key Architectural Decisions

### AsyncIOScheduler over BackgroundScheduler
python-telegram-bot v20 owns a single `asyncio` event loop. `AsyncIOScheduler` schedules coroutines on that same loop, so `poll_all_watches` can `await bot.send_message()` directly with no cross-thread machinery. `BackgroundScheduler` would run the job in a `ThreadPoolExecutor` and require `asyncio.run_coroutine_threadsafe(coro, loop)` — unnecessary complexity. See `docs/adr/001-apscheduler-integration.md`.

### httpx over requests for all HTTP calls
The polling job is `async def`. `requests.get` is synchronous — calling it inside the async job blocks the event loop for the full HTTP round-trip, stalling all Telegram updates during that time. `httpx.AsyncClient()` with `await` integrates cleanly without blocking. `requests` must not be used anywhere inside the bot package.

### SQLite + connection-per-call, no ORM
Single-user personal tool — SQLite's zero-overhead, no-server model is correct at this scale. The connection-per-call pattern (open → use → close per function) is required because the scheduler and Telegram handler threads are separate OS threads; a shared connection raises `sqlite3.ProgrammingError`.

### Soft-delete for watches
`/delete` sets `is_active = 0` rather than `DELETE FROM watches`. This preserves referential integrity: `price_history` and `alerts_sent` reference `watch_id` via foreign keys. Hard-deleting a watch would orphan those rows.

---

## Known Gotchas

1. **SQLite connection-per-call — no shared global**
   - **Symptom:** `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.`
   - **Fix:** Every function in `bot/db.py` opens its own `sqlite3.connect(DB_PATH)` via a `with` block. No module-level connection object.

2. **`requests.get` inside the async job blocks the event loop**
   - **Symptom:** Telegram commands become unresponsive during the 60-minute poll; updates queue up and fire in a burst after polling completes.
   - **Fix:** Use `await client.get(...)` with `httpx.AsyncClient()` inside `fetch_price`. `requests` must not be used anywhere in the bot package.

3. **Rate limiting from upstream APIs**
   - **Symptom:** Intermittent 429 responses or silent empty `data` arrays when many watches are active back-to-back.
   - **Fix:** `poll_all_watches` includes `await asyncio.sleep(0.5)` between per-watch iterations. Log a `WARNING` on any non-2xx API response.

4. **`should_send_alert` does not write to `alerts_sent`**
   - **Symptom:** Alerts fire repeatedly for the same price because the deduplication record is never written.
   - **Fix:** The caller (`scheduler.py`) must call `db.record_alert_sent(db_path, watch_id, price)` after a confirmed `await bot.send_message()`. `should_send_alert` is read-only.

5. **`AsyncIOScheduler` must be started before `application.run_polling()`**
   - **Symptom:** Scheduler never fires; no poll-related log lines appear.
   - **Fix:** Call `scheduler.start()` before `application.run_polling()`. `run_polling()` blocks the thread — anything after it only executes on shutdown.

6. **Travelpayouts token goes in the header, never the URL**
   - **Symptom:** 401 or silent empty response from Travelpayouts.
   - **Fix:** `headers={"X-Access-Token": TRAVELPAYOUTS_TOKEN}` in the `httpx` request. Never include the token as a query parameter.

7. **Travelpayouts TRY currency support is undocumented**
   - **Symptom:** Travelpayouts returns a non-2xx response or empty data when `currency=TRY` is passed.
   - **Fix:** The scheduler falls through to SunExpress when `fetch_price` returns `None`. No special handling in the client — if TRY is unsupported, the fallback chain handles it transparently.

8. **Duffel `None` return must not suppress an alert**
   - **Symptom:** Alerts stop firing even though Travelpayouts found a matching price.
   - **Fix:** In `scheduler.py`, when `duffel_client.verify_price()` returns `None`, proceed with the originally polled price and send the alert. Duffel is a best-effort verifier, not a gating condition.

9. **Scraper currencies are fixed — SunExpress always TRY, Pegasus always EUR**
   - **Symptom:** Changing the watch currency does not change what currency the scraper requests or returns. SunExpress always hits `currency=TRY` in the URL and returns TRY prices; Pegasus always hits `currency=EUR` and returns EUR prices.
   - **Fix:** `_normalize_price()` in `scheduler.py` automatically converts the scraper result to the watch's currency using `EUR_TRY_RATE` before the threshold comparison. No manual action needed — just keep `EUR_TRY_RATE` in `.env` up to date.

10. **`watches.currency` column is added via `ALTER TABLE` at startup for existing DBs**
   - **Symptom:** `OperationalError: table watches has no column named currency` on an old database.
   - **Fix:** `db.init_db()` wraps the `ALTER TABLE` in `try/except sqlite3.OperationalError` so it silently skips on fresh installs (column already in `CREATE TABLE`) and applies on old databases.

