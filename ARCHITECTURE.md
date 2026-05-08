# ARCHITECTURE.md — AirBoardFinder

Authoritative technical reference. Read this before touching any module.

---

## System Purpose

AirBoardFinder is a single-process Python 3.12 Telegram bot that monitors flight prices on behalf of registered users. Every 60 minutes APScheduler fires a polling job that queries the Kiwi Tequila API for each active watch (origin, destination, date range, price threshold stored in SQLite). When a found price is at or below the user's threshold and passes a two-layer deduplication check, the bot sends a Telegram alert with the route, price, and booking URL. Users create and manage watches via three Telegram commands: `/watch`, `/list`, `/delete`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Bot framework | python-telegram-bot 20.x |
| Scheduler | APScheduler 3.x (AsyncIOScheduler) |
| Flight data | Kiwi Tequila API v2 |
| HTTP client | httpx (async) |
| Storage | SQLite 3 (stdlib `sqlite3`, no ORM) |
| Fallback flight data | fast-flights (PyPI) |
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
│   ├── kiwi_client.py               # Kiwi Tequila HTTP client + fast-flights fallback
│   ├── formatter.py                 # Alert message formatter
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
| `bot/kiwi_client.py` | `fetch_price()` — async GET to Kiwi Tequila with `apiKey` header, parses cheapest result. Triggers fast-flights fallback when Kiwi returns no results. Returns `dict | None`. |
| `bot/formatter.py` | `format_alert()` — produces the Telegram message string from watch + price data. All required fields: route, dates, price + currency, threshold, booking URL. |
| `bot/handlers.py` | Async handlers for `/watch` (create), `/list` (read), `/delete` (soft-delete). Validates input, calls `db`, replies to user. All operations scoped to `update.effective_user.id`. |
| `bot/scheduler.py` | `poll_all_watches(bot, db_path, kiwi_api_key)` — async APScheduler job. Iterates active watches, fetches prices, inserts history, checks deduplication, sends alerts, records sent alerts. |

---

## Data Flows

### Polling flow (fires every 60 minutes)

```
AsyncIOScheduler
  └─ poll_all_watches(bot, db_path, kiwi_api_key)
       └─ db.get_all_active_watches(db_path)
            └─ for each watch:
                 kiwi_client.fetch_price(origin, dest, date_from, date_to, api_key)
                   └─ GET https://api.tequila.kiwi.com/v2/search  [header: apiKey: ...]
                        ├─ data[0] found → return {price, currency, booking_url}
                        └─ data empty   → fast-flights fallback → return dict | None
                 db.insert_price_history(db_path, watch_id, price, currency, booking_url)
                 if price <= watch["max_price"]:
                   db.should_send_alert(db_path, watch_id, price)
                     ├─ False → skip (deduplication blocked)
                     └─ True  →
                          formatter.format_alert(watch, price, currency, booking_url)
                          await bot.send_message(chat_id=watch["user_id"], text=message)
                          db.record_alert_sent(db_path, watch_id, price)
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

## External API Contract

### Kiwi Tequila v2 Search

| Field | Value |
|---|---|
| Method | `GET` |
| URL | `https://api.tequila.kiwi.com/v2/search` |
| Auth | HTTP header `apiKey: {KIWI_API_KEY}` — **never a query parameter** |
| `fly_from` | Origin IATA code |
| `fly_to` | Destination IATA code |
| `date_from` | `DD/MM/YYYY` format |
| `date_to` | `DD/MM/YYYY` format |
| `curr` | `EUR` (fixed) |
| `limit` | `1` (cheapest result only) |
| `sort` | `price` |

**Response shape:**
```json
{
  "data": [
    {
      "price": 189.0,
      "deep_link": "https://www.kiwi.com/deep?...",
      "..."  : "..."
    }
  ]
}
```

**Result extraction:** `data[0]["price"]` → price (float), `data[0]["deep_link"]` → booking URL. Currency is always EUR (fixed in request).

**No results:** `data` is empty or absent → trigger fast-flights fallback, log `WARNING`.

**HTTP error (non-2xx):** log at `ERROR` level, return `None`. Do not raise.

**Debug logging:** log raw response body at `DEBUG` level on every call.

---

## Telegram Command Interface

| Command | Signature | Success reply | Error reply |
|---|---|---|---|
| `/watch` | `/watch <origin> <destination> <date_from> <date_to> <max_price>` | `Watch created (ID: {id}). I'll alert you when {origin} → {destination} drops to {max_price} EUR or below.` | Usage string or validation error message |
| `/list` | `/list` | Formatted list — one watch per line: `[{id}] {origin}→{destination} {date_from}–{date_to} max {max_price} EUR` | `You have no active watches.` |
| `/delete` | `/delete <watch_id>` | `Watch {watch_id} deleted.` | `Watch not found or does not belong to you.` |

- All operations are scoped to `update.effective_user.id`.
- `/delete` enforces ownership at the SQL level: `WHERE id = ? AND user_id = ?`.
- `/watch` validates: arg count == 5, `max_price` is positive float, `date_from` and `date_to` are valid `YYYY-MM-DD`. On failure: reply with usage string, no DB write.

---

## Configuration Reference

| Variable | Required | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `KIWI_API_KEY` | Yes | API key from tequila.kiwi.com |
| `LOG_LEVEL` | No (default `INFO`) | Python logging level |

`DB_PATH` is a code constant in `main.py`: `"data/airboard.db"`. Not env-configurable.

---

## Key Architectural Decisions

### AsyncIOScheduler over BackgroundScheduler
python-telegram-bot v20 owns a single `asyncio` event loop. `AsyncIOScheduler` schedules coroutines on that same loop, so `poll_all_watches` can `await bot.send_message()` directly with no cross-thread machinery. `BackgroundScheduler` would run the job in a `ThreadPoolExecutor` and require `asyncio.run_coroutine_threadsafe(coro, loop)` — unnecessary complexity. See `docs/adr/001-apscheduler-integration.md`.

### httpx over requests for Kiwi HTTP calls
The polling job is `async def`. `requests.get` is synchronous — calling it inside the async job blocks the event loop for the full HTTP round-trip, stalling all Telegram updates during that time. `httpx.AsyncClient()` with `await` integrates cleanly without blocking. `requests` must not be used in `bot/kiwi_client.py`.

### SQLite + connection-per-call, no ORM
Single-user personal tool — SQLite's zero-overhead, no-server model is correct at this scale. The connection-per-call pattern (open → use → close per function) is required because the scheduler and Telegram handler threads are separate OS threads; a shared connection raises `sqlite3.ProgrammingError`.

### Soft-delete for watches
`/delete` sets `is_active = 0` rather than `DELETE FROM watches`. This preserves referential integrity: `price_history` and `alerts_sent` reference `watch_id` via foreign keys. Hard-deleting a watch would orphan those rows.

---

## Known Gotchas

1. **`apiKey` goes in the HTTP header, never the URL**
   - **Symptom:** Kiwi returns 401 or silently ignores the key.
   - **Fix:** `headers={"apiKey": KIWI_API_KEY}` in the `httpx` request. Never include the key as a query parameter.

2. **SQLite connection-per-call — no shared global**
   - **Symptom:** `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.`
   - **Fix:** Every function in `bot/db.py` opens its own `sqlite3.connect(DB_PATH)` via a `with` block. No module-level connection object.

3. **fast-flights breaks silently on protobuf schema changes**
   - **Symptom:** Fallback returns `None` or raises an opaque exception; alerts stop firing on routes where Kiwi also returns empty results.
   - **Fix:** Wrap fast-flights in `try/except Exception as e`, log `WARNING: fast-flights fallback failed: {e}`, return `None`. The fallback is advisory — never load-bearing.

4. **`requests.get` inside the async job blocks the event loop**
   - **Symptom:** Telegram commands become unresponsive during the 60-minute poll; updates queue up and fire in a burst after polling completes.
   - **Fix:** Use `await client.get(...)` with `httpx.AsyncClient()` inside `fetch_price`. `requests` is banned from `bot/kiwi_client.py`.

5. **Kiwi free-tier rate limits are undocumented**
   - **Symptom:** Intermittent 429 responses or silent empty `data` arrays when many watches are active back-to-back.
   - **Fix:** Add `await asyncio.sleep(0.5)` between per-watch iterations in `poll_all_watches`. Log a `WARNING` on any non-2xx Kiwi response.

6. **`should_send_alert` does not write to `alerts_sent`**
   - **Symptom:** Alerts fire repeatedly for the same price because the deduplication record is never written.
   - **Fix:** The caller (`scheduler.py`) must call `db.record_alert_sent(db_path, watch_id, price)` after a confirmed `await bot.send_message()`. `should_send_alert` is read-only.

7. **`AsyncIOScheduler` must be started before `application.run_polling()`**
   - **Symptom:** Scheduler never fires; no poll-related log lines appear.
   - **Fix:** Call `scheduler.start()` before `application.run_polling()`. `run_polling()` blocks the thread — anything after it only executes on shutdown.
