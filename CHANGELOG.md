# Changelog

## Unreleased

### Added

- **Pegasus Airlines scraper as a second fallback** (`bot/pegasus_scraper.py`) — a Playwright
  headless-Chromium scraper against `web.flypgs.com/booking`, tried after SunExpress when
  Travelpayouts has no data for a watch. Always requests and returns **EUR** prices.
- **`bot/scraper_utils.py`** — `date_range()` and `extract_price()`, shared by both scrapers
  (each site only supports single-date search, so the range is iterated one URL per day).
- **`EUR_TRY_RATE` env var** (default `54.0`) — `_normalize_price()` in `bot/scheduler.py`
  converts a scraper result to the watch's currency before the threshold comparison, since
  SunExpress is TRY-only and Pegasus is EUR-only.
- **Short `/watch` form** — `/watch <ORIG-DEST> <date> <max_price> [currency]` sets `date_to`
  to `date` automatically; the full six-argument form still works.

### Changed

- **Default watch currency is now `TRY`** (was `EUR`) — affects the `watches.currency` column
  default and the optional `/watch` currency argument.
- Documentation files (`AGENTS.md`, `CHANGELOG.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `Plans/`)
  are no longer gitignored, so the repository carries its own development history.

### Removed

- Kiwi Tequila and Amadeus implementations and all references to them (the polling chain is
  Travelpayouts → SunExpress → Pegasus, verified pre-alert by Duffel).

### Earlier

- Initial AirBoardFinder backend scaffold and bot implementation.
