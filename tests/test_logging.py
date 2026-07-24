import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppConfig
from src.service import execute_digest_pipeline
from src.telegram_client import _parse_message, fetch_target_messages_with_stats


def make_config(**overrides) -> AppConfig:
    defaults = dict(
        tg_api_id=1,
        tg_api_hash="hash",
        tg_phone_number="+1",
        tg_bot_token="bot-token",
        gemini_api_key="key",
        target_group="test_group",
        message_limit=50,
        hours_back=24,
        export_only=False,
        max_llm_messages=100,
        max_fetch_limit=10000,
        session_path="/data/session",
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


@pytest.mark.asyncio
async def test_parse_message_logs_length_skip(caplog):
    message = SimpleNamespace(
        text="hi",
        caption="",
        id=10,
        reply_to=None,
        date=datetime.now(timezone.utc),
        sender=None,
        sender_id=None,
    )

    with caplog.at_level(logging.INFO, logger="src.telegram_client"):
        parsed = await _parse_message(message, "-100", "Group")

    assert parsed is None
    assert "[SKIP_LENGTH]" in caplog.text


@pytest.mark.asyncio
async def test_fetch_target_messages_logs_summary_and_age_skip(caplog):
    old_message = SimpleNamespace(
        id=1,
        text="old message",
        caption="",
        reply_to=None,
        date=datetime.now(timezone.utc) - timedelta(hours=48),
        sender=None,
        sender_id=None,
    )

    fake_dialog = SimpleNamespace(name="Test Group", id=-100123, unread_count=1, entity=object())
    class FakeAsyncIterator:
        def __init__(self, items):
            self._items = items
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self._items:
                raise StopAsyncIteration
            return self._items.pop(0)

    fake_client = MagicMock()
    fake_client.iter_messages = MagicMock(return_value=FakeAsyncIterator([old_message]))

    with (
        patch("src.telegram_client._find_target_dialog", new_callable=AsyncMock, return_value=fake_dialog),
        caplog.at_level(logging.INFO, logger="src.telegram_client"),
    ):
        results, _ = await fetch_target_messages_with_stats(fake_client, "test_group", limit_msgs=10, hours_back=24, dialog=fake_dialog)

    assert results == []
    assert "[SKIP_AGE]" in caplog.text
    assert "[FETCH_SUMMARY]" in caplog.text
    assert "Skipped by Age: 1" in caplog.text


@pytest.mark.asyncio
async def test_execute_digest_pipeline_logs_filtered_out_state(caplog):
    config = make_config()
    fake_dialog = SimpleNamespace(name="Test Group", id=-100123, unread_count=1, entity=object())

    with (
        patch("src.telegram_client._find_target_dialog", new_callable=AsyncMock, return_value=fake_dialog),
        patch("src.service.fetch_target_messages_with_stats", new_callable=AsyncMock, return_value=([], {"scanned_count": 0, "age_skipped": 0, "filter_skipped": 0})),
        caplog.at_level(logging.INFO, logger="src.service"),
    ):
        await execute_digest_pipeline(MagicMock(), config, "test_group", unread_only=True, hours_back=24, limit_msgs=10, target_dialog=fake_dialog)

    assert "all items were filtered out by text validators" in caplog.text.lower()
