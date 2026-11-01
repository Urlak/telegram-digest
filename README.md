# Telegram Digest

A container-friendly Telegram digest tool. It reads messages from your Telegram
account, summarizes them with Google Gemini, and returns a Markdown digest from
either a FastAPI + aiogram bot or a CLI.

The bot is **owner-only**: it only answers the Telegram account that owns the
Telethon session. It is designed for a single user, typically hosted on a
personal NAS.

## What it does

- `/start` lists groups with unread messages.
- Selecting a group processes the **oldest unread batch** and acknowledges only
  that batch. Newer unread messages stay unread for the next run, so a large
  backlog is drained safely instead of being marked read all at once.
- Messages are filtered, media-only messages get markers (`[Фото]`,
  `[Голосовое, 0:42]`, ...), links are compacted to platform markers (`[YT]`,
  `[TG]`, ...), and the prompt is bounded by `MAX_LLM_CHARS`.
- The digest contains a short `Главное` section, topics, decisions/actions and
  open questions when they exist.
- Reports are archived as `digest_<group>_<id>_<timestamp>.md` plus a
  `*_latest.md` convenience copy.
- A failed Gemini call, a partial Telegram fetch, or a failed report write never
  marks messages as read.

## Tech stack

- Python 3.11+
- FastAPI + aiogram
- Telethon
- Google `google-genai` SDK
- Docker / Docker Compose

## Prerequisites

- Telegram API credentials from https://my.telegram.org/apps
- A Telegram bot token from @BotFather
- A Google Gemini API key from Google AI Studio
- The Telegram account whose messages will be read

## First-time Telegram session setup

The Telethon session is interactive and **must be created before Docker is
started**. A clean clone has no `data/session.session`, and the container has no
terminal for the login prompt.

1. Create `.env` from `.env.template` and fill in `TG_API_ID`, `TG_API_HASH`,
   `TG_PHONE_NUMBER`, `TG_BOT_TOKEN`, `GEMINI_API_KEY`.
2. Install dependencies and run the CLI once locally:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   python -m src.main
   ```

3. Complete the Telegram login prompt. This creates
   `data/session.session`.
4. Only then start Docker Compose. The `./data` directory is mounted into the
   container, so the session is reused there.

`data/session.session` is sensitive authentication data: never commit it, move
it, or delete it.

## Environment variables

See [.env.template](.env.template) for the full list. The important ones:

```env
TG_API_ID=123456
TG_API_HASH=your_telegram_api_hash
TG_PHONE_NUMBER=+1234567890
TG_BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_key

TARGET_GROUP=            # only for `python -m src.main --auto`
MESSAGE_LIMIT=100        # messages per unread batch
HOURS_BACK=24            # fallback mode only (no unread messages)
EXPORT_ONLY=False
MAX_LLM_MESSAGES=500
MAX_LLM_CHARS=60000
MAX_BLOCK_CHARS=4000
TIMEZONE=Europe/Moscow   # empty = system timezone
GEMINI_TIMEOUT_SECONDS=120
TELEGRAM_TIMEOUT_SECONDS=60
REQUEST_RETRIES=2
MAX_FLOOD_WAIT_SECONDS=300
```

`TARGET_GROUP` accepts **one** exact chat title or numeric ID. It is only used
by `--auto`; the bot lists chats interactively.

## Running the API and bot

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

`/health` returns `200` only when the aiogram polling task is alive and the
Telegram client is connected. If polling dies, it returns `503` with details.

Then open your bot and send `/start`.

## Running the CLI

Interactive mode:

```bash
python -m src.main
```

Non-interactive mode:

```bash
python -m src.main --auto
```

`--auto` requires `TARGET_GROUP`. The CLI exits with a non-zero code on
configuration errors, pipeline errors and incomplete fetches.

## Output files

Reports and exports live in `data/`:

- `digest_<group>_<group_id>_<YYYY-MM-DD_HHMMSS>.md` — archived digest
- `digest_<group>_<group_id>_latest.md` — latest digest copy
- `clean_messages_<group>_<group_id>_<YYYY-MM-DD_HHMMSS>.md` — `EXPORT_ONLY`
  output with original messages, IDs, authors, local time and full URLs

Reports include metadata: group name/ID, generation time, actual message period,
Gemini model, source/collapsed/LLM counts, characters sent, truncation status,
API duration and acknowledgement status.

## Docker deployment

```bash
docker compose up --build -d
```

The host port is `8041` (container port `8000`). Compose mounts `./data` into
`/app/data`, sets a container timezone via `TZ`, rotates Docker logs and uses
the `/health` endpoint for its healthcheck.

Before the first Docker run, make sure `data/session.session` already exists
(see the session setup section above).

## Testing

Tests are fully mocked and require no Telegram session or API keys:

```bash
pip install -r requirements-dev.txt
pytest
```

Runtime dependencies are in `requirements.txt`; test-only dependencies are in
`requirements-dev.txt`.

## Project structure

- [src/api.py](src/api.py) — FastAPI app and bot polling lifecycle
- [src/bot.py](src/bot.py) — aiogram handlers and Telegram HTML delivery
- [src/service.py](src/service.py) — digest pipeline and read-ack policy
- [src/telegram_client.py](src/telegram_client.py) — fetch, parse and acknowledge
- [src/summarizer.py](src/summarizer.py) — prompt construction and Gemini call
- [src/reporter.py](src/reporter.py) — report metadata, archive paths, atomic writes
- [src/telegram_format.py](src/telegram_format.py) — Markdown → Telegram HTML
- [src/main.py](src/main.py) — CLI entry point
- [tests/](tests/) — unit tests
