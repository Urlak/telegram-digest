import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telethon import TelegramClient

from src.config import load_config
from src.telegram_client import get_client
from src.service import get_available_dialogs, execute_digest_pipeline
from src.bot import create_bot

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
    bot, dp = create_bot(config, client)
    
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

class DigestRequest(BaseModel):
    target_group: str
    unread_only: bool = True
    hours_back: int | None = None
    limit_msgs: int | None = None
    export_only: bool = False

class DigestResponse(BaseModel):
    status: str
    group_name: str
    group_id: str
    summary: str
    message_count: int
    api_duration: float
    report_path: str | None
    error: str | None

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/v1/groups")
async def api_groups():
    client: TelegramClient = app.state.tg_client
    dialogs = await get_available_dialogs(client)
    return {"groups": dialogs}

@app.post("/api/v1/digest", response_model=DigestResponse)
async def api_digest(req: DigestRequest):
    client: TelegramClient = app.state.tg_client
    result = await execute_digest_pipeline(
        client=client,
        config=config,
        target_group=req.target_group,
        unread_only=req.unread_only,
        hours_back=req.hours_back,
        limit_msgs=req.limit_msgs,
        export_only=req.export_only
    )
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result)
    return result
