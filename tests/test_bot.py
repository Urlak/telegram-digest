import pytest
from unittest.mock import MagicMock
from aiogram import Dispatcher
from src.bot import create_bot
from src.config import AppConfig

def test_create_bot_registers_single_start_command():
    config = AppConfig(
        tg_api_id=1,
        tg_api_hash="hash",
        tg_phone_number="+1",
        tg_bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        gemini_api_key="gemini_key",
        target_group="test_group",
        message_limit=10,
        hours_back=24,
        export_only=False,
        max_llm_messages=10,
        max_fetch_limit=100,
        session_path="data/session"
    )
    mock_telethon = MagicMock()
    bot, dp = create_bot(config, mock_telethon, owner_id=12345)
    
    assert isinstance(dp, Dispatcher)
    assert bot.token == config.tg_bot_token
