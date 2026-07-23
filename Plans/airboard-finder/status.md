# Status - airboard-finder

## State
PLANNING

## Completed
- database: Implemented `bot/db.py` schema init, five indexes, watch CRUD, price history, alert recording, read-only deduplication, and rollback SQL; verified AC-DB1 through AC-DB5 on 2026-05-08.
- backend: Implemented scaffold docs, Kiwi client, Amadeus client, SunExpress scraper, formatter, Telegram handlers, fallback-chain scheduler job, entry point, APScheduler ADR, and backend smoke tests; verified `pytest -q` passes on 2026-05-08.
- tests: 42 tests written across 7 files covering all ACs; 42/42 pass, 72% overall coverage (db.py 100%, formatter.py 100%); report at `Plans/airboard-finder/reviews/tests-2026-05-08.md` — 2026-05-08.

## In Progress
_none_

## Blocked
_none_

## Drift Log
- database: Clarified AC-DB3 from "six indexes" to "five indexes"; implemented the five named indexes from `Plans/airboard-finder/database.md`.
