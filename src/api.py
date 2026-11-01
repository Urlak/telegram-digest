import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from telethon import TelegramClient

from src.config import load_config, setup_logging, validate_config

# Initialize unbuffered logging before any application modules emit logs.
setup_logging()

from src.bot import create_bot
from src.heartbeat import run_heartbeat
from src.telegram_client import get_client

logger = logging.getLogger(__name__)

config = load_config()


async def _init_client() -> TelegramClient:
    """Initializes Telethon Telegram client and ensures session storage exists."""
    import os

    os.makedirs(os.path.dirname(config.session_path), exist_ok=True)
    return await get_client(
        config.session_path,
        config.tg_api_id,
        config.tg_api_hash,
        config.tg_phone_number,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages FastAPI startup and teardown, including bot polling lifecycle.

    aiogram signal handlers are disabled so Uvicorn owns SIGTERM/SIGINT.  A
    polling task that dies unexpectedly flips ``/health`` to 503 instead of
    leaving the container looking healthy while the bot is dead.
    """
    validate_config(config, require_bot=True, require_gemini=not config.export_only)

    client: TelegramClient | None = None
    bot = None
    polling_task: asyncio.Task | None = None
    heartbeat_task: asyncio.Task | None = None

    try:
        client = await _init_client()
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Telegram session is not authorized (get_me returned None).")

        bot, dp = create_bot(config, client, owner_id=me.id)

        app.state.tg_client = client
        app.state.bot = bot
        app.state.polling_alive = True
        app.state.polling_error = None

        polling_task = asyncio.create_task(
            dp.start_polling(
                bot,
                handle_signals=False,
                close_bot_session=False,
            ),
            name="aiogram-polling",
        )
        app.state.polling_task = polling_task

        def _polling_done(task: asyncio.Task) -> None:
            app.state.polling_alive = False
            if task.cancelled():
                logger.warning("Telegram bot polling was cancelled.")
                return
            error = task.exception()
            if error is not None:
                app.state.polling_error = str(error)
                logger.error(
                    "Telegram bot polling stopped unexpectedly: %s",
                    error,
                    exc_info=error,
                )
            else:
                logger.warning("Telegram bot polling stopped.")

        polling_task.add_done_callback(_polling_done)

        # /health is polled every 30s but filtered from the log, so a quiet
        # container would look dead; one line per 10 minutes proves it is alive.
        heartbeat_task = asyncio.create_task(
            run_heartbeat(_health_snapshot),
            name="heartbeat",
        )

        yield

    finally:
        app.state.polling_alive = False

        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        if polling_task is not None:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error while waiting for bot polling shutdown.")

        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                logger.exception("Error while closing the bot session.")

        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                logger.exception("Error while disconnecting the Telegram client.")


app = FastAPI(lifespan=lifespan)


def _health_snapshot() -> dict:
    """Builds the health payload shared by /health and the periodic heartbeat."""
    polling_task = getattr(app.state, "polling_task", None)
    polling_alive = bool(polling_task and not polling_task.done())

    client = getattr(app.state, "tg_client", None)
    telegram_connected = bool(client and client.is_connected())

    payload = {
        "status": "ok" if polling_alive and telegram_connected else "degraded",
        "polling": polling_alive,
        "telegram_connected": telegram_connected,
    }

    polling_error = getattr(app.state, "polling_error", None)
    if polling_error and not polling_alive:
        payload["error"] = polling_error
    return payload


@app.get("/health")
async def health():
    """Health check used by Docker and uptime monitoring.

    Returns 200 only when the polling task is alive and the Telegram client is
    connected.  Details are included to make a silent failure visible.
    """
    payload = _health_snapshot()
    return JSONResponse(
        status_code=200 if payload["status"] == "ok" else 503,
        content=payload,
    )
