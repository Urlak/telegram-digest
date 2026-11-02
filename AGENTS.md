# AGENTS.md

Telegram digest service: a Telethon user client reads group messages, Gemini summarizes them, aiogram serves a bot, FastAPI hosts both. `src/api.py` is the production entrypoint; `src/main.py` is the CLI.

## Commands

```powershell
# Windows: repo uses .venv (Python 3.12 locally; Docker image is 3.11)
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

pytest                                             # full suite, no network or credentials needed
pytest tests/test_main.py -q                       # one file
pytest tests/test_main.py::test_auto_mode_full_happy_path -q

uvicorn src.api:app --host 0.0.0.0 --port 8000     # API + bot (needs a valid Telegram session)
python -m src.main                                 # interactive CLI
python -m src.main --auto                          # non-interactive; TARGET_GROUP required
docker compose up --build -d                       # host :8041 -> container :8000
```

No lint, formatter, typecheck, or CI config exists; do not invent commands. Run `pytest` from the repo root (`pytest.ini` sets `pythonpath = .`).


## Code Change Principles
Scope
- Make the smallest change that solves the task. If the diff exceeds roughly the size of the logic you're modifying, stop and justify it.
- Prefer editing existing code over adding new code, functions, or files. Create a new file only when it is clearly the right home for the code.
- Do not touch code unrelated to the task: no opportunistic cleanup, reformatting, renaming, or "while I'm here" changes.
- Do not rewrite a function to add a line. Make targeted edits.
- Do not add new dependencies for a small task.
- Delete unused or replaced code immediately. Since there is no backward compatibility, do not leave deprecated functions, legacy files, or commented-out code.

Match the codebase
- Match the error-handling, validation, logging, comment density, and abstraction level of the surrounding code. If neighbors don't null-check, don't add null checks.
- Before writing a helper, search the codebase and stdlib for one that already exists.
- Validate at boundaries only: public APIs, user input, external data, deserialization. Internal callers are trusted; do not re-validate inside private methods.

Simplicity
- Inline one-off helpers. Do not introduce a function, class, interface, or abstraction with fewer than two concrete call sites.
- No speculative generality: no unused parameters, config flags, options, compatibility layers, or interfaces with one implementer.
- Handle errors that can actually occur, not hypothetical ones. Do not add try/catch that only logs, re-throws, or swallows.
- Prefer modifying existing logic over wrapping it.

Tests
- Test behavior, not implementation. Do not duplicate existing coverage. One test per behavior is usually enough.
- Avoid heavy mocking for internal logic. Test against real internal dependencies where possible to keep the architecture simple.

Workflow
- Before editing, state in one or two sentences which files and functions you will change and roughly how many lines. If that is more than a handful of files, confirm with me first.
- After editing, review your own diff: is every changed line necessary for the stated task? Remove anything that isn't. Do not re-emit unchanged code.

## Architecture and data flow

- `src/api.py` lifespan validates config, connects Telethon, derives `owner_id` from the logged-in account, and starts aiogram polling with `handle_signals=False` so Uvicorn owns SIGTERM/SIGINT. Cleanup runs in `try/finally`.
- `/health` returns `200` only when the polling task is alive and the Telegram client is connected; otherwise it returns `503` with details.
- `/start` lists unread groups; the selected group's callback runs `execute_digest_pipeline()` in `src/service.py` with `unread_only=True`.
- Pipeline order: resolve dialog -> fetch oldest unread batch (`telegram_client.py`) -> collapse consecutive same-sender/thread messages within 5 min and `MAX_BLOCK_CHARS` (`processor.py`) -> Gemini (`summarizer.py`) -> report/export (`reporter.py`, `logic.py`) -> acknowledge the processed batch.
- The pipeline is serialized by a module-level `asyncio.Lock` and catches all exceptions, returning `{"status": "success" | "no_messages" | "incomplete" | "error", ...}`. Preserve that contract instead of letting errors escape.
- Read receipts are sent only after a successful summary or export. A Gemini failure, partial fetch, or failed report write must leave messages unread.
- Read state is a Telegram high-water mark. The pipeline acknowledges only a contiguous unread prefix where every message was processed or intentionally filtered, using `send_read_acknowledge(..., max_id=...)`. Never acknowledge without an explicit `max_id`.
- Fetch behavior: with unread messages it fetches the **oldest** `min(unread_count, limit)` messages using `min_id=read_inbox_max_id` and `reverse=True`. `HOURS_BACK` applies only to the fallback mode (`unread_only=False`), which fetches recent history and does not acknowledge anything. An exhausted retry budget returns `incomplete=True` and no acknowledgement.
- `src/config.py` validates numeric limits and credentials at entrypoints (`validate_config`), not on plain module import.

## Summarization

- `src/summarizer.py` uses `google.genai` (model `gemini-2.5-flash`) and deliberately produces Russian Markdown.
- The service runs the synchronous Gemini call through `asyncio.to_thread` and wraps it in `asyncio.wait_for`, so a slow request cannot block the Telegram bot.
- The prompt includes local timestamps with an explicit UTC offset, current date/time, media markers and link-platform markers.
- Message IDs appear only in the LLM input (for reply-chain reasoning) and in `[LLM_INPUT_IDS]` logs. The generated digest must list participants only — never `Msg: <id>` or other technical IDs.
- Input is bounded by both `MAX_LLM_MESSAGES` and `MAX_LLM_CHARS`; individual blocks are capped by `MAX_BLOCK_CHARS`. Truncation is reported in the summary and report metadata.
- `EXPORT_ONLY` uses `all_messages` (original messages with full URLs), not collapsed blocks.
- `requirements.txt` is runtime-only; `google-genai` is the active SDK. Tests must not depend on the deprecated `google-generativeai` package.

## Configuration and runtime

- `.env` at repo root is loaded by `python-dotenv`; keys and defaults are documented in `.env.template`. `src/config.py` loads config at import time, so restart after changing environment values.
- `TIMEZONE` is an optional IANA name (for example `Europe/Moscow`). Empty means the system timezone of the host/container. `tzdata` is installed for environments without a system tz database.
- `data/session.session` is live Telegram authentication data. It is gitignored and sensitive: never delete, move, or commit it. First-time login is interactive, so provision the session locally before starting Docker.
- All output paths derive from `src/config.py`'s location (`<repo>/data`), not the current directory; Docker mounts `./data:/app/data`. Keep persistence under the data folder.
- Reports are archived, never overwritten: `digest_<group>_<group_id>_<timestamp>.md` plus `*_latest.md`. Exports use the `clean_messages_` prefix.
- `.env` is excluded from the Docker image (`.dockerignore`); Compose supplies it via `env_file`.

## Testing

- Tests mock Telegram, the filesystem, and Gemini completely; no services or real keys are required.
- Async tests use `@pytest.mark.asyncio` (strict mode). Test modules define a local `make_config()` built from `AppConfig` plus `dataclasses.replace`.
- `execute_digest_pipeline()` exposes dependency-injection parameters (`fetch_messages_fn`, `summarize_messages_fn`, etc.) for tests. Fetch functions return `FetchOutcome`; legacy list/tuple returns are normalized for compatibility.
- Existing tests encode important behavior: auto mode always passes `force_fetch_fallback=True`, `EXPORT_ONLY` skips Gemini, failed summarization does not mark messages read, and only a contiguous processed prefix is acknowledged.
- `tests/test_setup.py` checks the active `google.genai` import.

## Conventions and gotchas

- `setup_logging()` (in `src/config.py`) logs to stderr and replaces Uvicorn handlers. Call it before other loggers emit, as `src/api.py` does.
- `src/main.py` reconfigures stdout/stderr to UTF-8 on Windows; preserve this if adding CLI output, since summaries are Cyrillic.
- Output filenames sanitize group names with `[^\w\s.-]`; Python `\w` keeps Cyrillic characters, so Russian group names remain readable in filenames.
- Per-message skip logs are `DEBUG`; aggregate fetch/filter statistics are `INFO`. Keep it that way to avoid filling NAS logs.
- Do not hand-edit generated reports.
