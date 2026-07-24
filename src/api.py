import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telethon import TelegramClient

from src.config import load_config, setup_logging
from src.telegram_client import get_client
from src.bot import create_bot

# Initialize standard logging configuration for stdout/stderr
setup_logging()

logger = logging.getLogger(__name__)

config = load_config()

async def _init_client() -> TelegramClient:
    import os
    os.makedirs(os.path.dirname(config.session_path), exist_ok=True)
    return await get_client(
        config.session_path, 
        config.tg_api_id, 
        config.tg_api_hash, 
        config.tg_phone_number
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    client = await _init_client()
    me = await client.get_me()
    bot, dp = create_bot(config, client, owner_id=me.id)
    
    app.state.tg_client = client
    app.state.bot = bot
    
    polling_task = asyncio.create_task(dp.start_polling(bot))
    
    yield
    
    # Teardown
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass
        
    await bot.session.close()
    await client.disconnect()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}
