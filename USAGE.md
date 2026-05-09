# AirBoardFinder — User Guide

This guide answers the practical questions: how to get the bot running, how to create a Telegram bot account for it, where you enter your flight criteria, and how the automatic price-source selection works.

---

## How It Works (Big Picture)

You run this program on your own computer (or a server). It creates a **Telegram bot** — a dedicated bot account that you chat with inside Telegram. You tell the bot which flights to watch and at what price. Every 60 minutes it silently checks prices in the background and sends you a Telegram message when a price drops to your target.

- **Your Telegram account** = how you receive alerts and type commands.
- **The bot account (created via BotFather)** = what the program logs in as and what you chat with.
- **No web interface.** Everything happens through Telegram commands.

---

## Step 1 — Create a Telegram Bot Account

You need to create a bot account on Telegram. This is free and takes 2 minutes.

1. Open Telegram and search for **@BotFather** (the official bot management service).
2. Start a chat with BotFather and send: `/newbot`
3. Follow the prompts — choose any name (e.g. "My Flight Watcher") and any username ending in `bot` (e.g. `myflightwatcher_bot`).
4. BotFather will reply with a **token** that looks like this:

   ```
   123456789:AAHdqTcvCH1vGWJxfSeofSs35ci-Y-nvKA
   ```

5. Copy that token. It goes into your `.env` file as `TELEGRAM_TOKEN`.

> Your personal Telegram account and this bot account are separate things. You'll send commands to the bot from your own account. The program runs as the bot.

---

## Step 2 — Get a Kiwi Tequila API Key (Required)

Kiwi Tequila is the primary flight price source.

1. Go to [tequila.kiwi.com](https://tequila.kiwi.com) and create a free account.
2. After signing in, go to **My API Keys** and create a new key.
3. Copy the key. It goes into your `.env` file as `KIWI_API_KEY`.

The free tier is sufficient for personal use with a handful of watches.

---

## Step 3 — Get Amadeus API Credentials (Optional but Recommended)

Amadeus is the fallback source when Kiwi returns no results. Without it, the bot falls back to a web scraper.

1. Go to [developers.amadeus.com](https://developers.amadeus.com) and create a free account.
2. Create a new **Self-Service** application.
3. Copy the **Client ID** and **Client Secret**.
4. These go into your `.env` file as `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET`.

If you skip this step, leave those two lines in `.env` with their placeholder values. The bot will skip Amadeus and try the SunExpress scraper instead when Kiwi finds nothing.

---

## Step 4 — Configure Your `.env` File

In the project folder, copy the template and fill it in:

```bash
cp .env.example .env
```

Then open `.env` in any text editor and fill in your values:

```
TELEGRAM_TOKEN=123456789:AAHdqTcvCH1vGWJxfSeofSs35ci-Y-nvKA
KIWI_API_KEY=your_kiwi_key_here
AMADEUS_CLIENT_ID=your_amadeus_client_id_here
AMADEUS_CLIENT_SECRET=your_amadeus_client_secret_here
LOG_LEVEL=INFO
```

> Never share this file. The `.env` file is gitignored and will not be committed to version control.

---

## Step 5 — Install and Run

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install the Chromium browser (used by the SunExpress fallback scraper)
python -m playwright install chromium

# Start the bot (runs in the foreground; keep the terminal open)
python main.py
```

You'll see log output in the terminal and in `logs/bot.log`. The bot is ready when you see no errors and it's waiting for updates.

---

## Step 6 — Using the Bot in Telegram

Open Telegram, search for the username you chose in Step 1 (e.g. `@myflightwatcher_bot`), and start a chat with it.

### Creating a Watch — `/watch`

This is where you enter your flight criteria. Send:

```
/watch <origin> <destination> <date_from> <date_to> <max_price>
```

| Parameter | What it is | Example |
|---|---|---|
| `origin` | Departure airport — 3-letter IATA code | `IST` |
| `destination` | Arrival airport — 3-letter IATA code | `LHR` |
| `date_from` | Earliest departure date (YYYY-MM-DD) | `2026-08-01` |
| `date_to` | Latest departure date (YYYY-MM-DD) | `2026-08-15` |
| `max_price` | Your maximum acceptable price in EUR | `200` |

**Example:**
```
/watch IST LHR 2026-08-01 2026-08-15 200
```
→ Bot replies: `Watch created (ID: 1). I'll alert you when IST → LHR drops to 200.0 EUR or below.`

**Finding IATA codes:** Search for the airport name + "IATA code" on Google. Common examples:
- Istanbul (Sabiha Gökçen): `SAW`
- Istanbul (Atatürk/new): `IST`
- London Heathrow: `LHR`
- London Gatwick: `LGW`
- Amsterdam: `AMS`
- Frankfurt: `FRA`

You can create multiple watches — one per route/date combination.

---

### Listing Your Watches — `/list`

```
/list
```

Shows all your active price watches:

```
[1] IST→LHR 2026-08-01–2026-08-15 max 200.0 EUR
[2] SAW→AMS 2026-09-10–2026-09-20 max 150.0 EUR
```

---

### Deleting a Watch — `/delete`

```
/delete <watch_id>
```

Use the ID number shown in `/list`. For example:

```
/delete 1
```

→ Bot replies: `Watch 1 deleted.`

You can only delete your own watches. Another Telegram user running the same bot cannot delete yours.

---

## How Price Sources Work (Automatic)

You cannot manually choose which source to use — the bot tries them in order, automatically:

1. **Kiwi Tequila** (primary): checked first on every poll. Covers most routes globally.
2. **Amadeus** (fallback): tried when Kiwi returns no results for a specific watch. Covers major airlines and routes.
3. **SunExpress scraper** (last resort): a web scraper that opens the SunExpress website in a headless browser. Only tried when both Kiwi and Amadeus return nothing. Useful for SunExpress-only routes (e.g. Turkey domestic / charter to Germany).

If all three return nothing for a watch, the bot skips that watch for this poll and tries again in 60 minutes. No error is sent to you.

---

## When Will I Receive an Alert?

The bot sends you a Telegram message when **all** of these are true:

1. A price was found (from any of the three sources above).
2. The price is at or below the `max_price` you set.
3. You haven't already been alerted for that exact price on that watch.
4. The new price is at least 5% lower than the last price you were alerted about.

Rule 4 prevents spam when prices oscillate. For example: if you were alerted at €190, the next alert only fires if the price drops to €180.50 or lower (5% below €190).

The alert message looks like this:

```
Flight alert: IST → LHR
Dates: 2026-08-01 – 2026-08-15
Price: 185.0 EUR  (your threshold: 200.0 EUR)
Book: https://www.kiwi.com/deep?token=...
```

Click the booking URL to go directly to the cheapest result found.

---

## Keeping the Bot Running

The bot stops when you close the terminal. To keep it running continuously:

- **On your own PC:** Leave the terminal open, or use a tool like `nohup` (Linux/Mac) or run it as a Windows service.
- **On a server:** Use a process manager like `systemd` or `supervisord`.
- **Cheap option:** Any always-on machine works — a Raspberry Pi, a cheap VPS, etc.

Logs are written to `logs/bot.log`. If something seems wrong, check that file first.

---

## Troubleshooting

**The bot doesn't respond to my commands.**
- Make sure `python main.py` is still running in your terminal.
- Check `logs/bot.log` for errors.

**I never get any price alerts.**
- Check that your `max_price` is realistic (above current market price for the route).
- Verify your `KIWI_API_KEY` is valid — log into tequila.kiwi.com and check the key status.
- Set `LOG_LEVEL=DEBUG` in `.env` and restart; this logs every Kiwi API response to `logs/bot.log`.

**I get the error "No module named telegram".**
- Run `pip install -r requirements.txt` again.

**I get the error "TELEGRAM_TOKEN environment variable is not set".**
- Your `.env` file is missing or has a placeholder value. Open it and paste in your real BotFather token.

**The SunExpress scraper fails.**
- Run `python -m playwright install chromium` to make sure the browser is installed.
