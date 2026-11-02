import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher

from src.bot import (
    CONTINUE_CALLBACK,
    CONTINUE_KEYBOARD,
    _group_keyboard,
    _send_digest,
    _status_notice,
    create_bot,
)
from src.config import AppConfig


def make_config() -> AppConfig:
    return AppConfig(
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
        session_path="data/session",
    )


def test_create_bot_registers_single_start_command():
    mock_telethon = MagicMock()
    bot, dp = create_bot(make_config(), mock_telethon, owner_id=12345)

    assert isinstance(dp, Dispatcher)
    assert bot.token == make_config().tg_bot_token


def test_status_notice_points_to_the_button_not_to_start():
    """The continuation hint moved from a command to an inline button."""
    notice = _status_notice({"remaining_unread": 7})

    assert "7" in notice
    assert "/start" not in notice


def test_group_keyboard_lists_groups_and_a_refresh_row():
    markup = _group_keyboard(
        [{"id": -100, "name": "Chat", "unread_count": 3}]
    )
    buttons = [button for row in markup.inline_keyboard for button in row]

    assert buttons[0].callback_data == "digest:-100"
    assert "3 unread" in buttons[0].text
    assert buttons[-1].callback_data == CONTINUE_CALLBACK


def test_refresh_keyboard_carries_the_continue_callback():
    button = CONTINUE_KEYBOARD.inline_keyboard[0][0]

    assert button.callback_data == CONTINUE_CALLBACK
    assert button.text == "📥 Ещё дайджест"


@pytest.mark.asyncio
async def test_send_digest_returns_the_message_that_needs_the_button():
    """A single-chunk digest edits the status message and reports its id."""
    bot = MagicMock()
    bot.edit_message_text = AsyncMock(return_value=SimpleNamespace(message_id=42))

    last_id = await _send_digest(bot, chat_id=1, text="hello", message_id=42)

    assert last_id == 42
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_digest_reports_the_last_chunk_of_a_long_digest():
    """The continue button must land on the final message, not the first one."""
    bot = MagicMock()
    bot.edit_message_text = AsyncMock(return_value=SimpleNamespace(message_id=42))
    ids = iter(range(43, 500))
    bot.send_message = AsyncMock(
        side_effect=lambda **_: SimpleNamespace(message_id=next(ids))
    )

    long_text = "word " * 4000
    last_id = await _send_digest(bot, chat_id=1, text=long_text, message_id=42)

    assert bot.send_message.await_count >= 2
    assert last_id == 42 + bot.send_message.await_count
