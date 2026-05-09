# AirBoardFinder

AirBoardFinder is a single-process Python 3.12 Telegram bot that watches flight prices and sends Telegram alerts when a route drops to or below a user-defined threshold. It polls Travelpayouts (cached prices) as the primary source, verifies candidates with Duffel (real-time) before alerting, and falls back to a SunExpress Playwright scraper as the last resort.

## Quickstart

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy the environment template and fill in credentials:

   ```bash
   cp .env.example .env
   ```

3. Install the Chromium browser used by the SunExpress fallback:

   ```bash
   python -m playwright install chromium
   ```

4. Run the bot:

   ```bash
   python main.py
   ```

## Commands

- `/watch <origin> <destination> <date_from> <date_to> <max_price>`
- `/list`
- `/delete <watch_id>`

## Development

Run tests with:

```bash
pytest
```

Runtime logs are written to `logs/bot.log`. The SQLite database is created at `data/airboard.db`.
