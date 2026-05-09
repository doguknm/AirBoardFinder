from __future__ import annotations

import pytest

from bot import db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


# --- init_db ---

def test_init_db_idempotent(db_path):
    db.init_db(db_path)  # second call must not raise


# --- create_watch ---

def test_create_watch_returns_id(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    assert isinstance(watch_id, int)
    assert watch_id > 0


# --- get_watches_for_user ---

def test_get_watches_for_user_empty(db_path):
    assert db.get_watches_for_user(db_path, 999) == []


def test_get_watches_for_user_scoped(db_path):
    db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    assert db.get_watches_for_user(db_path, 2) == []


def test_get_watches_for_user_active_only(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    db.delete_watch(db_path, watch_id, 1)
    assert db.get_watches_for_user(db_path, 1) == []


# --- delete_watch ---

def test_delete_watch_own(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    assert db.delete_watch(db_path, watch_id, 1) is True
    assert db.get_watches_for_user(db_path, 1) == []


def test_delete_watch_other_user(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    assert db.delete_watch(db_path, watch_id, 2) is False
    assert len(db.get_watches_for_user(db_path, 1)) == 1


# --- get_all_active_watches ---

def test_get_all_active_watches(db_path):
    db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    db.create_watch(db_path, 2, "AMS", "JFK", "2026-07-01", "2026-07-10", 300.0)
    third_id = db.create_watch(db_path, 3, "BER", "CDG", "2026-08-01", "2026-08-10", 150.0)
    db.delete_watch(db_path, third_id, 3)
    watches = db.get_all_active_watches(db_path)
    assert len(watches) == 2
    assert all(w["is_active"] == 1 for w in watches)


# --- should_send_alert ---

def test_should_send_alert_no_prior_alerts(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    assert db.should_send_alert(db_path, watch_id, 190.0) is True


def test_should_send_alert_exact_price_duplicate(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    db.record_alert_sent(db_path, watch_id, 190.0)
    assert db.should_send_alert(db_path, watch_id, 190.0) is False


def test_should_send_alert_5pct_drop_passes(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    db.record_alert_sent(db_path, watch_id, 100.0)
    # 94 < 100 * 0.95 → passes both layers
    assert db.should_send_alert(db_path, watch_id, 94.0) is True


def test_should_send_alert_5pct_drop_fails(db_path):
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    db.record_alert_sent(db_path, watch_id, 100.0)
    # 97 > 100 * 0.95 = 95 → blocked
    assert db.should_send_alert(db_path, watch_id, 97.0) is False


def test_should_send_alert_exact_boundary(db_path):
    # price == last * 0.95 → condition is price > last*0.95, which is False → alert fires
    watch_id = db.create_watch(db_path, 1, "IST", "LHR", "2026-06-01", "2026-06-10", 200.0)
    db.record_alert_sent(db_path, watch_id, 100.0)
    assert db.should_send_alert(db_path, watch_id, 95.0) is True
