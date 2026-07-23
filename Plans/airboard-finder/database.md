# Database — AirBoardFinder

**Lane**: database
**Tool**: Codex CLI
**Status**: not started
**Brief**: ./2026-05-08-summary.md
**Implements before**: backend.md

## Goal

Define and create the three SQLite tables that underpin all bot functionality: watch management, price polling history, and deduplication state. Tables are created via `CREATE TABLE IF NOT EXISTS` on bot startup — there is no migration toolchain.

## Schema Changes

```sql
-- forward (called from bot/db.py on startup)

CREATE TABLE IF NOT EXISTS watches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    origin      TEXT    NOT NULL,
    destination TEXT    NOT NULL,
    date_from   TEXT    NOT NULL,   -- ISO-8601 date string, e.g. "2026-06-01"
    date_to     TEXT    NOT NULL,   -- ISO-8601 date string
    max_price   REAL    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active   INTEGER NOT NULL DEFAULT 1   -- 1 = active, 0 = soft-deleted
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id    INTEGER NOT NULL REFERENCES watches(id),
    price       REAL    NOT NULL,
    currency    TEXT    NOT NULL DEFAULT 'EUR',
    booking_url TEXT    NOT NULL,
    checked_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id    INTEGER NOT NULL REFERENCES watches(id),
    price       REAL    NOT NULL,
    sent_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- rollback (drop tables in reverse dependency order)
-- WARNING: destructive — only run if wiping all data is acceptable.

DROP TABLE IF EXISTS alerts_sent;
DROP TABLE IF EXISTS price_history;
DROP TABLE IF EXISTS watches;
```

## Indexes and Constraints

- `watches(user_id)` — index to support fast `/list` and ownership checks for `/delete`.
- `watches(is_active)` — index (or partial index if supported) to support the scheduler query that fetches only active watches.
- `price_history(watch_id)` — index to support chronological lookups per watch.
- `alerts_sent(watch_id)` — index to support deduplication lookups.
- `alerts_sent(watch_id, price)` — composite index for the "exact price already alerted" check (layer 1 of deduplication).
- No ORM — all DDL and queries are raw `sqlite3` calls.

```sql
CREATE INDEX IF NOT EXISTS idx_watches_user_id   ON watches(user_id);
CREATE INDEX IF NOT EXISTS idx_watches_is_active  ON watches(is_active);
CREATE INDEX IF NOT EXISTS idx_price_history_watch ON price_history(watch_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_watch   ON alerts_sent(watch_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_dedup   ON alerts_sent(watch_id, price);
```

## Threading Constraint

**Critical:** SQLite connections must not be shared across threads.

- The scheduler job thread pool and Telegram handler threads are separate OS threads.
- `bot/db.py` must open a new `sqlite3.connect(DB_PATH)` at the start of every function and close it (or use `with` context manager) before returning.
- Do not store a module-level connection object.
- Do not use `check_same_thread=False` unless writes are serialized externally — they are not in this architecture.

## Data Backfill

None. This is a greenfield deployment. No existing data to migrate.

## Migration Strategy

- Forward: `CREATE TABLE IF NOT EXISTS` statements run inside `init_db()` in `bot/db.py`, called once at bot startup (`main.py`). Idempotent — safe to call on every restart.
- Rollback: Drop statements above. Manual action only; not wired into any automated process.
- Lock implications: SQLite acquires a write lock during `CREATE TABLE`. On startup (before any handlers or scheduler jobs are active) this is safe. No concurrent reads/writes at the moment `init_db()` runs.

## Acceptance Criteria

- AC-DB1: `init_db()` applies all three `CREATE TABLE IF NOT EXISTS` statements cleanly on a fresh (empty) database file.
- AC-DB2: `init_db()` is idempotent — calling it twice on the same database does not raise an error or alter existing rows.
- AC-DB3: All five indexes are created by `init_db()` without error.
- AC-DB4: Each `bot/db.py` function opens its own connection and does not reuse a module-level global.
- AC-DB5: Rollback drops all three tables and leaves the database file intact (empty).

## Out of Scope

- Database migrations toolchain (Alembic, Flyway, etc.)
- PostgreSQL, MySQL, or any non-SQLite backend
- ORM layer (SQLAlchemy, Peewee, etc.)
- Schema versioning table
