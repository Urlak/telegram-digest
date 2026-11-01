"""Tests for src/main.py pipeline orchestration.

All I/O (Telegram client, filesystem, Gemini) is mocked.
"""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppConfig
from src.contracts import FetchOutcome, SummaryResult
from src.main import _export_messages, _run_interactive_setup, run_pipeline


def make_config(**overrides) -> AppConfig:
    base = AppConfig(
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
    return replace(base, **overrides)


def fake_dialog(unread_count: int = 0):
    return SimpleNamespace(
        name="Test Group",
        id=-100123,
        unread_count=unread_count,
        entity=object(),
        dialog=SimpleNamespace(read_inbox_max_id=0),
    )


SAMPLE_MESSAGES = [
    {
        "message_id": 1,
        "group_id": "-100123",
        "group_name": "Test Group",
        "sender_name": "Alice",
        "date": "2024-01-01 10:00",
        "date_full": "2024-01-01 10:00:00 +03:00",
        "timestamp": 1704092400.0,
        "text": "Hello",
        "raw_text": "Hello",
        "reply_to_id": None,
    },
    {
        "message_id": 2,
        "group_id": "-100123",
        "group_name": "Test Group",
        "sender_name": "Bob",
        "date": "2024-01-01 10:01",
        "date_full": "2024-01-01 10:01:00 +03:00",
        "timestamp": 1704092460.0,
        "text": "Hi Alice",
        "raw_text": "Hi Alice",
        "reply_to_id": 1,
    },
]


def fallback_outcome(messages=None) -> FetchOutcome:
    messages = SAMPLE_MESSAGES if messages is None else messages
    scanned_ids = [message["message_id"] for message in messages]
    return FetchOutcome(
        messages=messages,
        mode="fallback",
        scanned_count=len(scanned_ids),
        scanned_ids=scanned_ids,
        parsed_ids=set(scanned_ids),
        batch_max_id=max(scanned_ids) if scanned_ids else None,
    )


def unread_outcome(messages=None, **overrides) -> FetchOutcome:
    messages = SAMPLE_MESSAGES if messages is None else messages
    scanned_ids = [message["message_id"] for message in messages]
    data = dict(
        messages=messages,
        mode="unread",
        scanned_count=len(scanned_ids),
        unread_count=len(scanned_ids),
        scanned_ids=scanned_ids,
        parsed_ids=set(scanned_ids),
        batch_max_id=max(scanned_ids) if scanned_ids else None,
    )
    data.update(overrides)
    return FetchOutcome(**data)


def summary_result(**overrides) -> SummaryResult:
    data = dict(
        text="## Summary",
        api_duration=1.5,
        model="gemini-2.5-flash",
        used_count=2,
        used_chars=100,
        total_count=2,
        truncated=False,
        used_message_ids={1, 2},
    )
    data.update(overrides)
    return SummaryResult(**data)


@pytest.mark.asyncio
async def test_pipeline_aborts_on_client_failure():
    """_init_client returning None should produce a non-zero exit code."""
    config = make_config()
    with patch("src.main._init_client", new_callable=AsyncMock, return_value=None):
        code = await run_pipeline(config, is_auto_mode=True)
    assert code == 1


@pytest.mark.asyncio
async def test_auto_mode_aborts_without_target_group():
    """Auto mode with empty TARGET_GROUP should abort before fetching."""
    config = make_config(target_group="")
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages_with_stats", new_callable=AsyncMock) as mock_fetch,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_fetch.assert_not_called()
    assert code == 2


@pytest.mark.asyncio
async def test_auto_mode_no_messages_returns_early():
    """Empty message list should stop before summarization."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=fallback_outcome([]),
        ),
        patch("src.main.summarize_messages") as mock_sum,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_sum.assert_not_called()
    assert code == 0


@pytest.mark.asyncio
async def test_auto_mode_full_happy_path():
    """Full fallback pipeline should summarize and write a report."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=fallback_outcome(),
        ),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", return_value=summary_result()) as mock_sum,
        patch("src.main.build_report", return_value="report text"),
        patch("src.main.finalize_report") as mock_finalize,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_sum.assert_called_once()
        mock_finalize.assert_called_once()
    assert code == 0


@pytest.mark.asyncio
async def test_pipeline_does_not_mark_messages_read_when_summarization_fails():
    """A failed summarization must not acknowledge the dialog."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(unread_count=2),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=unread_outcome(),
        ),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", side_effect=RuntimeError("boom")),
        patch(
            "src.main.mark_target_messages_read", new_callable=AsyncMock
        ) as mock_ack,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_ack.assert_not_called()
    assert code == 1


@pytest.mark.asyncio
async def test_pipeline_marks_messages_read_after_successful_processing():
    """Successful unread processing acknowledges only the processed batch."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(unread_count=2),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=unread_outcome(),
        ),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", return_value=summary_result()),
        patch("src.main.build_report", return_value="report text"),
        patch("src.main.finalize_report"),
        patch(
            "src.main.mark_target_messages_read",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ack,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_ack.assert_awaited_once()
        _, kwargs = mock_ack.call_args
        assert kwargs["max_id"] == 2
    assert code == 0


@pytest.mark.asyncio
async def test_pipeline_disconnects_client_on_failure():
    """The Telegram client should always disconnect when processing errors out."""
    config = make_config()
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_client.disconnect.assert_awaited_once()
    assert code == 1


@pytest.mark.asyncio
async def test_auto_mode_export_only_skips_summarizer():
    """export_only=True exports original messages and skips Gemini."""
    config = make_config(export_only=True)
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=fallback_outcome(),
        ),
        patch("src.main._export_messages", return_value="/data/export.md") as mock_export,
        patch("src.main.summarize_messages") as mock_sum,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_export.assert_called_once()
        exported_messages = mock_export.call_args[0][1]
        assert exported_messages == SAMPLE_MESSAGES
        mock_sum.assert_not_called()
    assert code == 0


@pytest.mark.asyncio
async def test_auto_mode_passes_force_fetch_fallback_true():
    """In auto mode, force_fetch_fallback must always be True."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=fallback_outcome([]),
        ) as mock_fetch,
    ):
        await run_pipeline(config, is_auto_mode=True)
        _, call_kwargs = mock_fetch.call_args
        assert call_kwargs.get("force_fetch_fallback") is True


@pytest.mark.asyncio
async def test_incomplete_fetch_is_not_acknowledged():
    """A partial fetch returns status=incomplete and never acknowledges."""
    config = make_config()
    mock_client = MagicMock()
    outcome = unread_outcome(
        incomplete=True,
        error="connection reset",
        remaining_unread=2,
    )
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(unread_count=2),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=outcome,
        ),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", return_value=summary_result()),
        patch("src.main.build_report", return_value="report text"),
        patch("src.main.finalize_report"),
        patch(
            "src.main.mark_target_messages_read", new_callable=AsyncMock
        ) as mock_ack,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        mock_ack.assert_not_called()
    assert code == 1


@pytest.mark.asyncio
async def test_truncated_summary_acknowledges_only_processed_prefix():
    """With LLM truncation, only the contiguous used prefix is acknowledged."""
    config = make_config()
    mock_client = MagicMock()
    messages = SAMPLE_MESSAGES + [
        {
            "message_id": 3,
            "group_id": "-100123",
            "group_name": "Test Group",
            "sender_name": "Carol",
            "date": "2024-01-01 10:02",
            "date_full": "2024-01-01 10:02:00 +03:00",
            "timestamp": 1704092520.0,
            "text": "Third",
            "raw_text": "Third",
            "reply_to_id": None,
        }
    ]
    outcome = unread_outcome(messages=messages)
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(unread_count=3),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=outcome,
        ),
        patch("src.main.collapse_consecutive_messages", return_value=messages),
        patch(
            "src.main.summarize_messages",
            return_value=summary_result(
                used_count=2,
                total_count=3,
                truncated=True,
                used_message_ids={1, 2},
            ),
        ),
        patch("src.main.build_report", return_value="report text"),
        patch("src.main.finalize_report"),
        patch(
            "src.main.mark_target_messages_read",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ack,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        _, kwargs = mock_ack.call_args
        assert kwargs["max_id"] == 2
    assert code == 0


@pytest.mark.asyncio
async def test_all_filtered_unread_batch_is_acknowledged():
    """A batch consisting only of intentionally filtered messages is acknowledged."""
    config = make_config()
    mock_client = MagicMock()
    outcome = FetchOutcome(
        messages=[],
        mode="unread",
        scanned_count=2,
        unread_count=2,
        scanned_ids=[1, 2],
        parsed_ids=set(),
        batch_max_id=2,
    )
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch(
            "src.service._find_target_dialog",
            new_callable=AsyncMock,
            return_value=fake_dialog(unread_count=2),
        ),
        patch(
            "src.main.fetch_target_messages_with_stats",
            new_callable=AsyncMock,
            return_value=outcome,
        ),
        patch(
            "src.main.mark_target_messages_read",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ack,
    ):
        code = await run_pipeline(config, is_auto_mode=True)
        _, kwargs = mock_ack.call_args
        assert kwargs["max_id"] == 2
    assert code == 0


def test_export_messages_uses_original_messages(tmp_path):
    """EXPORT_ONLY must write original messages, not collapsed blocks."""
    config = make_config(session_path=str(tmp_path / "session"))
    path = _export_messages(
        config, SAMPLE_MESSAGES, "Test Group", "-100123"
    )
    content = open(path, encoding="utf-8").read()
    assert "[ID:[1]]" in content
    assert "[ID:[2]]" in content
    assert "Hi Alice" in content


class _DialogListClient:
    """Client stub whose iter_dialogs yields the given dialogs."""

    def __init__(self, dialogs):
        self._dialogs = dialogs

    def iter_dialogs(self, limit=100):
        async def generator():
            for dialog in self._dialogs:
                yield dialog

        return generator()


def _dialog(unread_count: int):
    return SimpleNamespace(
        name="Test Group",
        id=-100123,
        unread_count=unread_count,
        is_group=True,
        is_channel=False,
    )


@pytest.mark.asyncio
async def test_interactive_unread_batch_skips_fetch_mode_prompt():
    """Variant A: unread messages win, so no fallback question is asked."""
    client = _DialogListClient([_dialog(unread_count=3)])
    with patch("builtins.input", side_effect=["1"]) as mock_input:
        target, force_fallback, _ = await _run_interactive_setup(client)

    assert target == "-100123"
    assert force_fallback is False
    assert mock_input.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("answer, expected", [("y", True), ("n", False)])
async def test_interactive_fallback_prompt_only_without_unread(answer, expected):
    """The fallback question is asked only when nothing is unread."""
    client = _DialogListClient([_dialog(unread_count=0)])
    with patch("builtins.input", side_effect=["1", answer]) as mock_input:
        _, force_fallback, _ = await _run_interactive_setup(client)

    assert force_fallback is expected
    assert mock_input.call_count == 2
