# Telegram Digest

A container-friendly Telegram digest tool that collects messages from Telegram groups or channels, summarizes them with Google Gemini, and can be driven either from a CLI or from a running FastAPI + Telegram bot service.

## What the current code does

- The main runtime is a FastAPI application in [src/api.py](src/api.py).
- On startup, it initializes a Telethon client, creates the Telegram bot, and starts aiogram polling.
- The bot exposes commands such as `/start`, `/help`, `/groups`, and `/digest`.
- When a user selects a dialog, the bot runs the digest pipeline and sends the summary back to Telegram.
- A health endpoint is available at `/health`.
- The older CLI workflow is still available through [src/main.py](src/main.py) for interactive or auto runs.

## Tech stack

- Python 3.11+
- FastAPI
- Telethon
- aiogram
- Google Generative AI SDK
- Docker / Docker Compose

## Prerequisites

- Telegram API credentials from https://my.telegram.org/apps
- A Telegram bot token from BotFather
- A Google Gemini API key from Google AI Studio
- A Telegram account that will be used to authenticate the session; the bot only responds to that account owner

## Environment variables

Create a `.env` file with at least the following values:

```env
TG_API_ID=123456
TG_API_HASH=your_telegram_api_hash
TG_PHONE_NUMBER=+1234567890
TG_BOT_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_key

# Optional
TARGET_GROUP=
MESSAGE_LIMIT=100
HOURS_BACK=24
EXPORT_ONLY=False
MAX_LLM_MESSAGES=500
```

## Local setup

```bash
git clone <repo-url>
cd telegram-digest

python -m venv .venv
source .venv/bin/activate  # on Windows use .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Running the API and Telegram bot

The current default entry point is the FastAPI app, which also starts the Telegram bot:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Then check the health endpoint:

```bash
curl http://localhost:8000/health
```

After the app is running, start a chat with your bot and use:

- `/start` or `/help` to see the available actions
- `/groups` to list available dialogs with unread messages
- `/digest` to start the selection flow

## Running the CLI pipeline

If you want to use the original command-line flow instead of the bot-driven API service:

```bash
python -m src.main
```

Or run in non-interactive mode using `.env` values:

```bash
python -m src.main --auto
```

## Docker deployment

The repository includes a container setup that starts the API service and its embedded bot:

```bash
docker compose up --build -d
```

The app is exposed on port `8041` in the host mapping, and the container uses the `./data` directory for the Telegram session and generated Markdown outputs.

## Project structure

- [src/api.py](src/api.py) — FastAPI app and bot startup lifecycle
- [src/bot.py](src/bot.py) — aiogram handlers and Telegram bot commands
- [src/main.py](src/main.py) — CLI entry point
- [src/service.py](src/service.py) — digest execution pipeline
- [data/](data/) — Telegram session file and generated reports
- [tests/](tests/) — unit tests