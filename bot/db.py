"""SQLite data access for AirBoardFinder."""

from __future__ import annotations

from contextlib import closing
import sqlite3
from typing import Any


DB_PATH = "data/airboard.db"

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS watches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    origin      TEXT    NOT NULL,
    destination TEXT    NOT NULL,
    date_from   TEXT    NOT NULL,
    date_to     TEXT    NOT NULL,
    max_price   REAL    NOT NULL,
    currency    TEXT    NOT NULL DEFAULT 'EUR',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active   INTEGER NOT NULL DEFAULT 1
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
"""

CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_watches_user_id ON watches(user_id);
CREATE INDEX IF NOT EXISTS idx_watches_is_active ON watches(is_active);
CREATE INDEX IF NOT EXISTS idx_price_history_watch ON price_history(watch_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_watch ON alerts_sent(watch_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_dedup ON alerts_sent(watch_id, price);
"""

ROLLBACK_SQL = """
DROP TABLE IF EXISTS alerts_sent;
DROP TABLE IF EXISTS price_history;
DROP TABLE IF EXISTS watches;
"""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row_to_dict(row) for row in rows]


def init_db(db_path: str) -> None:
    """Create the AirBoardFinder schema and indexes if they do not exist."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(CREATE_TABLES_SQL)
        conn.executescript(CREATE_INDEXES_SQL)
        try:
            conn.execute(
                "ALTER TABLE watches ADD COLUMN currency TEXT NOT NULL DEFAULT 'EUR'"
            )
        except sqlite3.OperationalError:
            pass  # column already exists on existing databases
        conn.commit()


def create_watch(
    db_path: str,
    user_id: int,
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
    max_price: float,
    currency: str = "EUR",
) -> int:
    """Insert an active watch and return its database ID."""
    with closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO watches (
                user_id,
                origin,
                destination,
                date_from,
                date_to,
                max_price,
                currency
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, origin, destination, date_from, date_to, max_price, currency),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_watches_for_user(db_path: str, user_id: int) -> list[dict[str, Any]]:
    """Return active watches owned by one Telegram user."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id,
                user_id,
                origin,
                destination,
                date_from,
                date_to,
                max_price,
                currency,
                created_at,
                is_active
            FROM watches
            WHERE user_id = ? AND is_active = 1
            ORDER BY id
            """,
            (user_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


def get_all_active_watches(db_path: str) -> list[dict[str, Any]]:
    """Return every active watch for scheduler polling."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                id,
                user_id,
                origin,
                destination,
                date_from,
                date_to,
                max_price,
                currency,
                created_at,
                is_active
            FROM watches
            WHERE is_active = 1
            ORDER BY id
            """
        ).fetchall()
        return _rows_to_dicts(rows)


def delete_watch(db_path: str, watch_id: int, user_id: int) -> bool:
    """Soft-delete a watch if it belongs to the given user."""
    with closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE watches
            SET is_active = 0
            WHERE id = ? AND user_id = ? AND is_active = 1
            """,
            (watch_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def insert_price_history(
    db_path: str,
    watch_id: int,
    price: float,
    currency: str,
    booking_url: str,
) -> None:
    """Record one observed price for a watch."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO price_history (watch_id, price, currency, booking_url)
            VALUES (?, ?, ?, ?)
            """,
            (watch_id, price, currency, booking_url),
        )
        conn.commit()


def should_send_alert(db_path: str, watch_id: int, price: float) -> bool:
    """Return True when both deduplication layers allow an alert.

    An exact 5% drop passes: price == last_alerted_price * 0.95 returns True.
    This function is read-only; callers record sent alerts after Telegram send.
    """
    with closing(sqlite3.connect(db_path)) as conn:
        exact_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM alerts_sent
            WHERE watch_id = ? AND price = ?
            """,
            (watch_id, price),
        ).fetchone()[0]
        if exact_count > 0:
            return False

        last_alert = conn.execute(
            """
            SELECT price
            FROM alerts_sent
            WHERE watch_id = ?
            ORDER BY sent_at DESC, id DESC
            LIMIT 1
            """,
            (watch_id,),
        ).fetchone()
        if last_alert is not None:
            last_alerted_price = float(last_alert[0])
            if price > last_alerted_price * 0.95:
                return False

        return True


def record_alert_sent(db_path: str, watch_id: int, price: float) -> None:
    """Record a confirmed Telegram alert send."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO alerts_sent (watch_id, price)
            VALUES (?, ?)
            """,
            (watch_id, price),
        )
        conn.commit()
