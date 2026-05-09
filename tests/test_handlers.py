from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import db, handlers


def _make_update(user_id: int = 42) -> MagicMock:
    user = MagicMock()
    user.id = user_id

    message = AsyncMock()
    message.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_user = user
    update.effective_message = message
    update.message = message
    return update


def _make_context(db_path: str, args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    ctx.application = MagicMock()
    ctx.application.bot_data = {"db_path": db_path}
    return ctx


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "handlers.db")
    db.init_db(path)
    return path


# --- /watch ---

async def test_watch_handler_creates_watch_and_replies_with_id(db_path):
    update = _make_update()
    ctx = _make_context(
        db_path,
        args=["IST", "LHR", "2026-06-01", "2026-06-10", "200.0"],
    )

    await handlers.watch_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "Watch created" in reply_text
    assert "ID:" in reply_text
    watches = db.get_watches_for_user(db_path, 42)
    assert len(watches) == 1
    assert watches[0]["currency"] == "EUR"


async def test_watch_handler_accepts_try_currency(db_path):
    update = _make_update()
    ctx = _make_context(
        db_path,
        args=["IST", "ANK", "2026-08-01", "2026-08-05", "5000.0", "TRY"],
    )

    await handlers.watch_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "TRY" in reply_text
    watches = db.get_watches_for_user(db_path, 42)
    assert watches[0]["currency"] == "TRY"


async def test_watch_handler_wrong_arg_count_sends_usage(db_path):
    update = _make_update()
    ctx = _make_context(db_path, args=["IST", "LHR"])

    await handlers.watch_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "Usage" in reply_text
    assert db.get_watches_for_user(db_path, 42) == []


async def test_watch_handler_invalid_max_price_sends_error(db_path):
    update = _make_update()
    ctx = _make_context(db_path, args=["IST", "LHR", "2026-06-01", "2026-06-10", "notanumber"])

    await handlers.watch_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "positive" in reply_text.lower() or "price" in reply_text.lower()


# --- /list ---

async def test_list_handler_returns_watches(db_path):
    db.create_watch(db_path, 42, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    update = _make_update()
    ctx = _make_context(db_path)

    await handlers.list_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "IST" in reply_text


async def test_list_handler_empty_graceful(db_path):
    update = _make_update()
    ctx = _make_context(db_path)

    await handlers.list_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "no active watches" in reply_text.lower()


# --- /delete ---

async def test_delete_handler_own_watch(db_path):
    watch_id = db.create_watch(db_path, 42, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    update = _make_update()
    ctx = _make_context(db_path, args=[str(watch_id)])

    await handlers.delete_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "deleted" in reply_text.lower()
    assert db.get_watches_for_user(db_path, 42) == []


async def test_delete_handler_other_user_rejected(db_path):
    watch_id = db.create_watch(db_path, 99, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    update = _make_update(user_id=42)
    ctx = _make_context(db_path, args=[str(watch_id)])

    await handlers.delete_handler(update, ctx)

    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "not found" in reply_text.lower() or "belong" in reply_text.lower()
    # Watch still active
    assert len(db.get_all_active_watches(db_path)) == 1
