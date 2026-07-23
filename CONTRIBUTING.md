# Contributing

## Setup

Use Python 3.12, then install the pinned dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env` from the committed template:

```bash
cp .env.example .env
```

Fill in `TELEGRAM_TOKEN`, `TRAVELPAYOUTS_TOKEN`, and `DUFFEL_API_KEY`. Do not commit `.env`.
`EUR_TRY_RATE` is optional (default `54.0`) — it converts scraper prices between EUR and TRY.

Install the Playwright Chromium browser after installing Python packages:

```bash
python -m playwright install chromium
```

## Development Commands

```bash
python main.py
pytest
pytest --cov=bot --cov-report=term-missing
```

## Debugging

Check `logs/bot.log` first, then inspect `data/airboard.db` if watch or alert state looks wrong. Set `LOG_LEVEL=DEBUG` to include raw Travelpayouts response bodies in the log.

## Project Rules

- Read `ARCHITECTURE.md` before changing bot logic.
- Keep the Travelpayouts token in the `X-Access-Token` request header, never in the URL.
- Open a fresh SQLite connection per database function.
- Keep the SunExpress and Pegasus scrapers as fallback-only behavior — Travelpayouts stays the primary source.
