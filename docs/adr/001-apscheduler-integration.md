# ADR 001: APScheduler Integration

## Status

Accepted

## Context

python-telegram-bot v20 runs on a single `asyncio` event loop. APScheduler offers two relevant scheduler choices for this bot.

## Options Considered

1. `AsyncIOScheduler`: schedules coroutine jobs on the existing event loop, so `await bot.send_message()` works directly inside the polling job.
2. `BackgroundScheduler`: runs jobs in a `ThreadPoolExecutor`; sending Telegram messages would require `asyncio.run_coroutine_threadsafe(coro, loop)` and a stored event loop reference.

## Decision

Use `AsyncIOScheduler` on the same event loop that `application.run_polling()` manages.

## Rationale

This keeps the polling job simple: no `asyncio.run_coroutine_threadsafe` boilerplate, no saved loop reference, and no cross-thread concerns around the Telegram bot object. The polling job is already an `async def`, so `AsyncIOScheduler` matches the execution model.

## Consequences

The polling job shares the event loop with Telegram update handling. A blocking HTTP request inside the job would stall the bot, so all HTTP clients (`travelpayouts_client`, `duffel_client`) use `httpx.AsyncClient()` with `await`. `requests.get` is intentionally not used.

## Known Risk

The polling job includes a small `asyncio.sleep(0.5)` between per-watch iterations as a precaution against rate limiting from any of the upstream APIs.
