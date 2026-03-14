# Project: telegram-digest
**Role:** Senior Python & DevOps Engineer
**Objective:** Automate Telegram message extraction and Gemini-powered summarization.

## Environment & Tech Stack
- **OS:** macOS (Apple Silicon MacBook Pro)
- **Runtime:** Python 3.12+ (running in `.venv`)
- **Dependencies:** Update [requirements.txt](cci:7://file:///Users/romanstrijac/Developer/local-experiments/telegram-digest/requirements.txt:0:0-0:0) for any new packages.
- **Deployment:** Docker container for Synology NAS (Container Manager)
- **Key Libraries:** Telethon (TG Client), google-generativeai, python-dotenv
- **Storage:** SQLite (stored in [/data/digest.db](cci:7://file:///Users/romanstrijac/Developer/local-experiments/telegram-digest/data/digest.db:0:0-0:0))

## Coding Standards
- **Style:** Concise, PEP8 compliant, well-documented functions.
- **Error Handling:** Use try-except blocks for all network (Telegram/API) calls.
- **Logging:** Use the `logging` module outputting to stdout for Docker log capture.
- **Security:** Never hardcode keys; always read from [.env](cci:7://file:///Users/romanstrijac/Developer/local-experiments/telegram-digest/.env:0:0-0:0).
- **Brevity:** Keep explanations brief and information-dense. No "fluff."

## Constraints & Boundaries
- **Telegram Session:** The `data/*.session` files are sensitive. Never move or delete them without asking.
- **Persistence:** Ensure all database paths are relative to the `/data` folder to support Docker volume mounting.
- **App Output:** The script should output Gemini summaries as clear Markdown bullet points.

## Command Shortcuts
- **Run:** `python -m src.main`
- **Test:** `pytest`
- **Deploy:** `docker-compose up --build -d`
