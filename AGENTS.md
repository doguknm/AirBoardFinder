# AGENTS.md

Cross-tool architecture reference for Claude Code, OpenAI Codex, Gemini CLI, OpenCode, and any other AI coding assistant working in this repository.

---

## Project Overview

AirBoardFinder is a single-process Python 3.12 Telegram bot that polls the Travelpayouts Aviasales Data API every 60 minutes via APScheduler and sends Telegram price-drop alerts when a user's watch threshold is met. Candidates are verified against Duffel in real time before an alert goes out. Users manage watches via `/watch`, `/list`, and `/delete` commands. A two-layer deduplication scheme (exact-price check + 5%-additional-drop rule) prevents alert spam.

| Layer | Technology |
|---|---|
| Bot framework | python-telegram-bot 21.x |
| Scheduler | APScheduler 3.x (AsyncIOScheduler) |
| Primary flight data | Travelpayouts Aviasales Data API (cached, free) |
| Pre-alert verification | Duffel API (real-time) |
| Fallback flight data | SunExpress Playwright scraper (TRY), then Pegasus Airlines Playwright scraper (EUR) |
| HTTP client | httpx (async) |
| Storage | SQLite 3 (stdlib, no ORM) |
| Runtime | Python 3.12 |

Default watch currency is **TRY**. Scraper prices are normalized to the watch currency via `EUR_TRY_RATE` before any threshold comparison.

---

## Read First

**`ARCHITECTURE.md`** in the repo root is the authoritative technical reference. Read it before touching any file. It documents:

- Full module map and each module's single responsibility
- Both data flows — polling (scheduler → Travelpayouts → SunExpress → Pegasus → normalize → db → dedup → Duffel verify → formatter → Telegram) and command (/watch, /list, /delete → db → reply)
- Complete SQLite schema: 3 tables, all columns with types and constraints, 5 indexes, threading constraint
- Deduplication algorithm with pseudo-code and boundary conditions (exactly 5% drop fires)
- Travelpayouts and Duffel API contracts: URL, header auth, query params, response shape, error handling
- Telegram command interface: signatures, success replies, error replies, ownership rules
- All key architectural decisions with rationale (AsyncIOScheduler, httpx, SQLite connection-per-call, soft-delete)
- 10 numbered gotchas — check this list before diagnosing any unexpected behaviour

---

## Cross-Tool Precedence

This repository has three guidance files. When all three are present, read all three before making code changes.

| File | Use for |
|---|---|
| `ARCHITECTURE.md` | Architecture facts: schema, data flows, API contracts, module responsibilities, gotchas. This is the source of truth for all technical decisions. |
| `CLAUDE.md` | Project workflow: debugging order (`logs/bot.log` first), development commands, critical patterns (header auth, connection-per-call, scraper currency normalization), recurring problems log. |
| `AGENTS.md` | This file — orientation and tool precedence only. Contains no architecture content. |

If `ARCHITECTURE.md` and `CLAUDE.md` conflict on a technical fact, `ARCHITECTURE.md` is authoritative. If they conflict on workflow or process, `CLAUDE.md` is authoritative.

---

## Key File Pointers

When a task touches one of these concerns, start here before searching broadly.

| Concern | Read first |
|---|---|
| DB schema, CRUD functions, deduplication logic | `bot/db.py` + `ARCHITECTURE.md § SQLite Schema` + `ARCHITECTURE.md § Deduplication Algorithm` |
| Polling job, alert send flow, rate-limit pacing | `bot/scheduler.py` + `ARCHITECTURE.md § Data Flows` |
| Travelpayouts API client | `bot/travelpayouts_client.py` + `ARCHITECTURE.md § External API Contract` |
| Duffel pre-alert verification | `bot/duffel_client.py` + `ARCHITECTURE.md § External API Contract` |
| Scraper fallbacks, currency normalization | `bot/sunexpress_scraper.py`, `bot/pegasus_scraper.py`, `bot/scraper_utils.py` + `ARCHITECTURE.md § Data Flows` |
| Telegram command parsing, reply format, ownership | `bot/handlers.py` + `ARCHITECTURE.md § Telegram Command Interface` |
| Startup order, env loading, scheduler wiring | `main.py` + `ARCHITECTURE.md § Key Architectural Decisions` |
| APScheduler integration rationale | `docs/adr/001-apscheduler-integration.md` |

---

## Recurring Problems

See `## Recurring Problems` in `CLAUDE.md`.
