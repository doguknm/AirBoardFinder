# Plan: Add Pegasus Airlines Scraper

## Context

The bot currently chains three price sources: Travelpayouts (primary) → SunExpress scraper
(fallback 1) → None. Pegasus Airlines (flypgs.com) is a major Turkish LCC covering routes
like SAW→HTY that the existing sources may miss. This adds Pegasus as fallback 2, slotting
in after SunExpress with zero changes to the existing source order.

## Fallback chain (before → after)
TP → SunExpress → [None, notify if notify_always]
TP → SunExpress → Pegasus → [None, notify if notify_always] ← after

---

## Files

| Action | File |
|--------|------|
| Create | `bot/pegasus_scraper.py` |
| Modify | `bot/scheduler.py` |
| Create | `tests/test_pegasus_scraper.py` |
| Modify | `tests/test_scheduler.py` |
| Modify | `tests/test_backend_smoke.py` |

---

## Step 1 — Create `bot/pegasus_scraper.py`

Exact structural mirror of `bot/sunexpress_scraper.py` with these substitutions:

| SunExpress | Pegasus |
|---|---|
| `SUNEXPRESS_SEARCH_URL = "https://www.sunexpress.com/en/"` | `PEGASUS_SEARCH_URL = "https://www.flypgs.com/en/"` |
| Currency `"EUR"`, regex `(?:€\|EUR)` | Currency `"TRY"`, regex `(?:₺\|TRY)` |
| `"SunExpress scraper failed"` log message | `"Pegasus scraper failed"` |
| `"input[name='from']"` in origin selector list | `"input[id*='origin']"` |
| `"input[name='to']"` in destination selector list | `"input[id*='destination']"` |

Everything else is identical: `_fill_first_available`, `_extract_price`, the try/finally
browser close, the outer except that returns `None`, and the `ImportError` guard at the top.

Price regex for Pegasus:
```python
r"(?:₺|TRY)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:₺|TRY)"
Return dict on success: {"price": float, "currency": "TRY", "booking_url": str}

Step 2 — Modify bot/scheduler.py
Line 9 — add pegasus_scraper to the import:
from bot import db, duffel_client, formatter, pegasus_scraper, sunexpress_scraper, travelpayouts_client
After the SunExpress if result is None: block — insert the Pegasus call:
        if result is None:
            failed_sources.append(
                "SunExpress scraper — no prices found "
                "(route may not be served by SunExpress, or the website blocked the scraper)"
            )
            result = await pegasus_scraper.fetch_price(
                watch["origin"],
                watch["destination"],
                watch["date_from"],
                watch["date_to"],
            )
            if result is None:
                failed_sources.append(
                    "Pegasus scraper — no prices found "
                    "(route may not be served by Pegasus, or the website blocked the scraper)"
                )
                The existing LOGGER.warning("Travelpayouts returned no result … trying SunExpress.") line
is left unchanged.

Step 3 — Create tests/test_pegasus_scraper.py
Mirror of tests/test_sunexpress_scraper.py with these substitutions:

SunExpress	Pegasus
from bot import sunexpress_scraper	from bot import pegasus_scraper
monkeypatch.setattr(sunexpress_scraper, ...)	monkeypatch.setattr(pegasus_scraper, ...)
logger "bot.sunexpress_scraper"	logger "bot.pegasus_scraper"
"SunExpress scraper failed"	"Pegasus scraper failed"
Three tests (same structure as sunexpress):

test_fetch_price_exception_returns_none — __aenter__ raises → logs warning → returns None
test_fetch_price_never_raises — same exception must not propagate
test_browser_closed_on_exception — page.goto raises → browser.close awaited once
Step 4 — Modify tests/test_scheduler.py
Add one new test after test_poll_falls_back_to_sunexpress_when_travelpayouts_returns_none:

async def test_poll_falls_back_to_pegasus_when_sunexpress_returns_none(
    db_path, watch_id, monkeypatch
):
    bot = AsyncMock()
    pegasus_mock = AsyncMock(
        return_value={"price": 750.0, "currency": "TRY", "booking_url": "https://flypgs.test"}
    )
    monkeypatch.setattr(
        "bot.scheduler.travelpayouts_client.fetch_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "bot.scheduler.sunexpress_scraper.fetch_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("bot.scheduler.pegasus_scraper.fetch_price", pegasus_mock)
    monkeypatch.setattr(
        "bot.scheduler.duffel_client.verify_price", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("bot.scheduler.asyncio.sleep", AsyncMock())

    await poll_all_watches(bot, db_path, "tp-token", "duffel-key")

    pegasus_mock.assert_awaited_once()
    bot.send_message.assert_not_called()  # 750 TRY > 200 EUR threshold
Note: watch_id fixture creates a watch with max_price=200.0 (EUR). 750 TRY is above
that threshold, so no alert fires and send_message is not called.

Step 5 — Modify tests/test_backend_smoke.py
Add pegasus_scraper to the import:

from bot import db, pegasus_scraper, sunexpress_scraper
Add one test at the end of the file:

@pytest.mark.asyncio
async def test_pegasus_fetch_price_returns_none_when_dependencies_missing(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(pegasus_scraper, "async_playwright", None)
    monkeypatch.setattr(pegasus_scraper, "stealth_async", None)

    with caplog.at_level("WARNING"):
        result = await pegasus_scraper.fetch_price("SAW", "HTY", "2026-06-01", "2026-06-10")

    assert result is None
    assert "Pegasus scraper failed" in caplog.text
Verification
# New/modified tests only
pytest tests/test_pegasus_scraper.py tests/test_scheduler.py tests/test_backend_smoke.py -v

# Full suite — confirm zero regressions
pytest

# With coverage
pytest --cov=bot --cov-report=term-missing
Expected: 5 new passing tests (3 in test_pegasus_scraper.py, 1 in test_scheduler.py,
1 in test_backend_smoke.py), all pre-existing tests still passing.