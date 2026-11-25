# Winpot Telegram Browser Bot

A Telegram-connected browser automation project built around reusable persistent Chromium profiles, `jev_ultrafast/snapshot.js`, and OpenRouter.

## Project Structure

- `winpot_bot/` — Main Telegram bot, AI router, Playwright profile manager, and Jev multi-step loop
  - `winpot_bot/bot.py` — Telegram UI dashboard, profile manager, settings, and natural-language handler
  - `winpot_bot/router.py` — Natural-language AI tool router (`AI_MODEL_TEXT`)
  - `winpot_bot/jev_agent.py` — Multi-step automation loop using `jev_ultrafast/snapshot.js` and `AI_MODEL_DECISIONS_API` (`typesafe/jev-1.14`)
  - `winpot_bot/browser_manager.py` — Persistent Playwright browser profile manager (`profiles/<profile_name>/`)
  - `winpot_bot/summarizer.py` — OpenRouter page summarizer
  - `winpot_bot/settings.py` — Persistent runtime settings (`settings.json`)
  - `winpot_bot/cli.py` — Local CLI runner
- `jev_ultrafast/` — Original Jev Ultrafast modules and `snapshot.js`
- `profiles/` — Persistent Chromium user-data directories (git-ignored)
- `.env` — Root environment file (`TELEGRAM_BOT_TOKEN`, `AI_MODEL_*`, `AI_REASONING_EFFORT`, `HEADLESS`)
- `docs/telegram-bot-api.md` — Local Telegram Bot API reference

## Setup

```bash
uv sync
uv run playwright install chromium
```

## Usage

### Run the Telegram Bot
```bash
uv run python -m winpot_bot.bot
```
Send `/start` in Telegram, or send any natural-language request (e.g. `"open winpot.mx/sport with winpot, wait 5s, and summarize live football"`).

### Run via CLI (without Telegram)
```bash
uv run python -m winpot_bot.cli --profile winpot --url https://www.winpot.mx/sport
```

## Checks & Tests

```bash
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
uv build
```
