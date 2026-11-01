from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.contracts import FetchOutcome
from src.telegram_client import (
    _parse_message,
    fetch_target_messages_with_stats,
    mark_target_messages_read,
)


class FakeAsyncIterator:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class RaisingAsyncIterator:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise RuntimeError("connection reset")


def make_message(message_id: int, text: str = "hello", date=None):
    return SimpleNamespace(
        id=message_id,
        text=text,
        caption="",
        reply_to=None,
        date=date or datetime.now(timezone.utc),
        sender=None,
        sender_id=message_id,
    )


def make_dialog(unread_count: int = 0, read_inbox_max_id: int = 0):
    return SimpleNamespace(
        name="Test Group",
        id=-100123,
        unread_count=unread_count,
        entity=object(),
        dialog=SimpleNamespace(read_inbox_max_id=read_inbox_max_id),
    )


@pytest.mark.asyncio
async def test_parse_message_adds_media_and_link_markers():
    message = SimpleNamespace(
        id=5,
        text="Look https://youtu.be/a and https://youtu.be/b plus https://example.com/page",
        caption="",
        photo=object(),
        reply_to=None,
        date=datetime(2024, 3, 19, 9, 0, tzinfo=timezone.utc),
        sender=None,
        sender_id=5,
    )

    parsed = await _parse_message(message, "-100", "Group", timezone_name="UTC")

    assert parsed is not None
    assert parsed["media"] == "[Фото]"
    assert "[Фото]" in parsed["text"]
    assert "[YT ×2]" in parsed["text"]
    assert "[Web: example.com]" in parsed["text"]
    assert "https://youtu.be/a" in parsed["raw_text"]
    assert parsed["date"] == "2024-03-19 09:00"
    assert parsed["date_full"].endswith("+00:00")


@pytest.mark.asyncio
async def test_parse_message_keeps_media_only_message():
    voice = SimpleNamespace(duration=42)
    message = SimpleNamespace(
        id=6,
        text="",
        caption="",
        voice=voice,
        reply_to=None,
        date=datetime(2024, 3, 19, 9, 0, tzinfo=timezone.utc),
        sender=None,
        sender_id=6,
    )

    parsed = await _parse_message(message, "-100", "Group")

    assert parsed is not None
    assert parsed["text"] == "[Голосовое, 0:42]"
    assert parsed["has_media"] is True


@pytest.mark.asyncio
async def test_fetch_unread_uses_oldest_batch_and_min_id():
    dialog = make_dialog(unread_count=3, read_inbox_max_id=10)
    messages = [make_message(11), make_message(12), make_message(13)]

    client = MagicMock()
    recorded = {}

    def fake_iter_messages(entity, **kwargs):
        recorded.update(kwargs)
        return FakeAsyncIterator(messages)

    client.iter_messages = fake_iter_messages

    outcome = await fetch_target_messages_with_stats(
        client,
        "test_group",
        limit_msgs=3,
        hours_back=1,
        dialog=dialog,
    )

    assert isinstance(outcome, FetchOutcome)
    assert outcome.mode == "unread"
    assert recorded["min_id"] == 10
    assert recorded["reverse"] is True
    assert recorded["limit"] == 3
    assert outcome.scanned_ids == [11, 12, 13]
    assert outcome.batch_max_id == 13
    assert outcome.remaining_unread == 0


@pytest.mark.asyncio
async def test_fetch_unread_ignores_hours_back():
    old_date = datetime.now(timezone.utc) - timedelta(days=100)
    dialog = make_dialog(unread_count=1, read_inbox_max_id=0)
    client = MagicMock()
    client.iter_messages = lambda entity, **kwargs: FakeAsyncIterator(
        [make_message(1, "old but unread", old_date)]
    )

    outcome = await fetch_target_messages_with_stats(
        client, "test_group", limit_msgs=10, hours_back=1, dialog=dialog
    )

    assert len(outcome.messages) == 1
    assert outcome.age_skipped == 0


@pytest.mark.asyncio
async def test_fetch_returns_incomplete_on_error():
    dialog = make_dialog(unread_count=1, read_inbox_max_id=0)
    client = MagicMock()
    client.iter_messages = lambda entity, **kwargs: RaisingAsyncIterator()

    outcome = await fetch_target_messages_with_stats(
        client,
        "test_group",
        limit_msgs=10,
        hours_back=24,
        dialog=dialog,
        retries=0,
    )

    assert outcome.incomplete is True
    assert "connection reset" in (outcome.error or "")
    assert outcome.messages == []


@pytest.mark.asyncio
async def test_fetch_reports_remaining_unread_for_partial_batch():
    dialog = make_dialog(unread_count=10, read_inbox_max_id=0)
    client = MagicMock()
    client.iter_messages = lambda entity, **kwargs: FakeAsyncIterator(
        [make_message(1), make_message(2), make_message(3)]
    )

    outcome = await fetch_target_messages_with_stats(
        client, "test_group", limit_msgs=3, hours_back=24, dialog=dialog
    )

    assert outcome.remaining_unread == 7


@pytest.mark.asyncio
async def test_mark_read_requires_explicit_max_id():
    client = MagicMock()
    client.send_read_acknowledge = AsyncMock(return_value=True)
    dialog = make_dialog()

    acknowledged = await mark_target_messages_read(
        client, "test_group", dialog=dialog, max_id=None
    )

    assert acknowledged is False
    client.send_read_acknowledge.assert_not_called()


@pytest.mark.asyncio
async def test_mark_read_passes_max_id():
    client = MagicMock()
    client.send_read_acknowledge = AsyncMock(return_value=True)
    dialog = make_dialog()

    acknowledged = await mark_target_messages_read(
        client, "test_group", dialog=dialog, max_id=42
    )

    assert acknowledged is True
    client.send_read_acknowledge.assert_awaited_once_with(
        dialog.entity, max_id=42
    )
