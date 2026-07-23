# Tests — AirBoardFinder

**Lane**: tests
**Tools**: Playwright MCP (unit / integration), pytest (direct)
**Status**: not started
**Brief**: ./2026-05-08-summary.md

## Test Plan by Acceptance Criterion

| AC | Lane | Tier | Tool | Description |
|---|---|---|---|---|
| AC1 | backend | unit | pytest | `/watch` handler stores a row in `watches` and returns a reply containing the watch ID |
| AC2 | backend | unit | pytest | `/list` returns formatted watch list for user; empty-list reply when no watches exist |
| AC3 | backend | unit | pytest | `/delete` soft-deletes own watch; rejects deletion of another user's watch ID |
| AC4 | backend | integration | pytest | Scheduler `poll_all_watches` calls `insert_price_history` for each active watch via Kiwi → Amadeus → SunExpress fallback chain |
| AC5 | backend | integration | pytest | `poll_all_watches` calls `bot.send_message` when price <= max_price and dedup passes |
| AC6 | backend | unit | pytest | `should_send_alert` returns False for same watch+price already in `alerts_sent` |
| AC6 | backend | unit | pytest | `should_send_alert` returns False when new price is not 5% lower than last alerted price |
| AC7 | backend | unit | pytest | `kiwi_client.fetch_price` returns fast-flights result and logs WARNING when Kiwi returns empty data |
| AC7 | backend | unit | pytest | `kiwi_client.fetch_price` returns None and logs WARNING when both Kiwi and fast-flights fail |
| AC7 | backend | unit | pytest | Scheduler tries Amadeus after Kiwi returns None; logs WARNING at each fallback step |
| AC7 | backend | unit | pytest | Scheduler tries SunExpress scraper after both Kiwi and Amadeus return None |
| AC8 | backend | unit | pytest | `KIWI_API_KEY` appears in request header, not in URL string |
| AC8 | backend | unit | pytest | `AMADEUS_CLIENT_ID`/`SECRET` are passed to SDK constructor, never appear in logged URLs |
| AC9 | database | unit | pytest | All CRUD operations on `watches` and both dedup layers — see detail below |
| AC10 | backend | unit | pytest | Log file receives INFO entry after a successful alert send |
| AC11 | backend | unit | pytest | `amadeus_client.fetch_price` returns `{"price", "currency", "booking_url"}` dict from mocked SDK response |
| AC11 | backend | unit | pytest | `amadeus_client.fetch_price` returns None and logs ERROR when SDK raises an exception |
| AC12 | backend | unit | pytest | `sunexpress_scraper.fetch_price` returns None and logs WARNING on any exception — never raises |
| AC12 | backend | unit | pytest | `sunexpress_scraper.fetch_price` closes the browser even when an exception occurs |

---

## Detailed Test Cases

### `tests/test_db.py`

All tests use a temporary in-memory or temp-file SQLite database created fresh per test via `tmp_path` fixture.

**Watches CRUD**

| Test | Description |
|---|---|
| `test_create_watch_returns_id` | `create_watch(...)` returns an integer ID > 0 |
| `test_get_watches_for_user_empty` | Returns `[]` when no watches exist for user |
| `test_get_watches_for_user_scoped` | User A's watches do not appear in User B's list |
| `test_get_watches_for_user_active_only` | Soft-deleted watch (is_active=0) does not appear in list |
| `test_delete_watch_own` | `delete_watch(watch_id, user_id=owner)` returns `True`; watch no longer in active list |
| `test_delete_watch_other_user` | `delete_watch(watch_id, user_id=other)` returns `False`; watch still active |
| `test_get_all_active_watches` | Returns only is_active=1 rows across all users |

**Deduplication — `should_send_alert`**

| Test | Description |
|---|---|
| `test_should_send_alert_no_prior_alerts` | Returns `True` when `alerts_sent` is empty for the watch |
| `test_should_send_alert_exact_price_duplicate` | Returns `False` when the exact same price already exists in `alerts_sent` for the watch |
| `test_should_send_alert_5pct_drop_passes` | Returns `True` when new price is >5% lower than last alerted price (e.g. last=100, new=94) |
| `test_should_send_alert_5pct_drop_fails` | Returns `False` when new price is only 3% lower than last alerted price (e.g. last=100, new=97) |
| `test_should_send_alert_exact_boundary` | Returns `True` when new price equals exactly 95% of last alerted price — boundary confirmed: condition is `price > last * 0.95`, so equality passes and alert fires |

---

### `tests/test_kiwi_client.py`

All HTTP calls are mocked via `pytest-mock` patching `httpx.AsyncClient`. No real network calls.

| Test | Description |
|---|---|
| `test_fetch_price_success` | Mocked `httpx.AsyncClient.get` returns valid Kiwi JSON; `fetch_price` returns dict with `price`, `currency`, `booking_url` |
| `test_fetch_price_empty_kiwi_triggers_fallback` | Mocked Kiwi returns `{"data": []}`; asserts fast-flights fallback is called; asserts `WARNING` is emitted via `caplog` |
| `test_fetch_price_fallback_exception_returns_none` | Mocked Kiwi returns empty; fast-flights raises exception; `fetch_price` returns `None`; `WARNING` is logged |
| `test_fetch_price_http_error_returns_none` | Mocked `httpx.AsyncClient.get` returns a 500 response; `fetch_price` returns `None`; `ERROR` is logged |
| `test_api_key_in_header_not_url` | Captures the `httpx` request; asserts `headers["apiKey"]` is set; asserts the URL string does not contain the API key value |

---

### `tests/test_amadeus_client.py`

Amadeus SDK calls mocked via `unittest.mock.patch` or `pytest-mock` on the `amadeus.Client` instance. No real network calls.

| Test | Description |
|---|---|
| `test_fetch_price_success` | Mocked SDK `shopping.flight_offers_search.get` returns valid offer; `fetch_price` returns dict with `price`, `currency`, `booking_url` |
| `test_fetch_price_no_offers_returns_none` | Mocked SDK returns response with empty `data`; `fetch_price` returns `None` |
| `test_fetch_price_sdk_error_returns_none` | Mocked SDK raises `amadeus.ResponseError`; `fetch_price` returns `None`; `ERROR` is logged |
| `test_credentials_not_in_logged_output` | `fetch_price` is called; `caplog` output does not contain `AMADEUS_CLIENT_ID` or `AMADEUS_CLIENT_SECRET` values |

---

### `tests/test_sunexpress_scraper.py`

Playwright is mocked via `unittest.mock.AsyncMock` — no real browser launched.

| Test | Description |
|---|---|
| `test_fetch_price_exception_returns_none` | `async_playwright().__aenter__` raises an exception; `fetch_price` returns `None`; `WARNING` is logged via `caplog` |
| `test_fetch_price_never_raises` | Any exception inside the scraper is caught; `fetch_price` returns `None` without propagating — verified with `pytest.raises` expectation inverted |
| `test_browser_closed_on_exception` | Browser context manager `__aexit__` is called even when an exception occurs mid-scrape |

---

### `tests/test_formatter.py`

| Test | Description |
|---|---|
| `test_format_alert_contains_route` | Output string contains `{origin}` and `{destination}` |
| `test_format_alert_contains_price` | Output string contains the price value and currency |
| `test_format_alert_contains_booking_url` | Output string contains the full booking URL |
| `test_format_alert_contains_threshold` | Output string contains the watch's `max_price` |
| `test_format_alert_contains_dates` | Output string contains `date_from` and `date_to` |

---

## Test Configuration

- Runner: `pytest`
- Coverage: `pytest --cov=bot --cov-report=term-missing`
- Async support: `pytest-asyncio` with `asyncio_mode = "auto"` in `pytest.ini` or `pyproject.toml`
- Fixtures: `tmp_path` (stdlib pytest) for per-test SQLite databases
- No real network calls in any test — all external I/O is mocked

## TestSprite PRD Summary

AirBoardFinder is a Telegram bot with no web UI. There are no browser-based flows for TestSprite E2E testing. All acceptance criteria are verified at the unit and integration level via pytest. TestSprite is not applicable to this project.

## Out of Scope

- E2E browser tests (no web UI exists)
- Live Kiwi Tequila API calls in tests
- Live Amadeus API calls in tests (use mocked SDK)
- Live SunExpress browser sessions in tests (use mocked Playwright)
- Live Telegram API calls in tests
- Load or performance testing
- Scheduler timing precision tests (60-minute interval not tested in unit suite)
