"""
Tests for src/main.py pipeline logic.
All I/O (Telegram client, file system, summarizer) is mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main import run_pipeline, _export_messages
from src.config import AppConfig


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


SAMPLE_MESSAGES = [
    {"message_id": 1, "group_id": "-100123", "group_name": "Test Group",
     "sender_name": "Alice", "date": "2024-01-01 10:00", "text": "Hello", "reply_to_id": None},
    {"message_id": 2, "group_id": "-100123", "group_name": "Test Group",
     "sender_name": "Bob", "date": "2024-01-01 10:01", "text": "Hi Bob", "reply_to_id": 1},
]


@pytest.mark.asyncio
async def test_pipeline_aborts_on_client_failure():
    """_init_client returning None should cause early return."""
    config = make_config()
    with patch("src.main._init_client", new_callable=AsyncMock, return_value=None):
        await run_pipeline(config, is_auto_mode=True)  # should not raise


@pytest.mark.asyncio
async def test_auto_mode_aborts_without_target_group():
    """Auto mode with empty TARGET_GROUP should log error and abort."""
    config = make_config(target_group="")
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock) as mock_fetch,
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_auto_mode_no_messages_returns_early():
    """Empty message list should stop the pipeline before summarization."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, return_value=[]),
        patch("src.main.summarize_messages") as mock_sum,
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_sum.assert_not_called()


@pytest.mark.asyncio
async def test_auto_mode_full_happy_path():
    """Full pipeline in auto mode should call summarize and finalize_report."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, return_value=SAMPLE_MESSAGES),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", return_value=("## Summary", 1.5)) as mock_sum,
        patch("src.main.build_report", return_value="report text"),
        patch("src.main.finalize_report") as mock_finalize,
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_sum.assert_called_once()
        mock_finalize.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_does_not_mark_messages_read_when_summarization_fails():
    """A failed summarization should not acknowledge the dialog yet."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, return_value=SAMPLE_MESSAGES),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", side_effect=RuntimeError("boom")),
        patch("src.main.mark_target_messages_read", new_callable=AsyncMock) as mock_ack,
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_ack.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_marks_messages_read_after_successful_processing():
    """Successful processing should acknowledge only after the pipeline completes."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, return_value=SAMPLE_MESSAGES),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main.summarize_messages", return_value=("## Summary", 1.5)),
        patch("src.main.build_report", return_value="report text"),
        patch("src.main.finalize_report"),
        patch("src.main.mark_target_messages_read", new_callable=AsyncMock) as mock_ack,
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_ack.assert_awaited_once_with(mock_client, "test_group")


@pytest.mark.asyncio
async def test_pipeline_disconnects_client_on_failure():
    """The Telegram client should always disconnect when processing errors out."""
    config = make_config()
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_mode_export_only_skips_summarizer():
    """export_only=True should call _export_messages and skip summarization."""
    config = make_config(export_only=True)
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, return_value=SAMPLE_MESSAGES),
        patch("src.main.collapse_consecutive_messages", return_value=SAMPLE_MESSAGES),
        patch("src.main._export_messages") as mock_export,
        patch("src.main.summarize_messages") as mock_sum,
    ):
        await run_pipeline(config, is_auto_mode=True)
        mock_export.assert_called_once()
        mock_sum.assert_not_called()


@pytest.mark.asyncio
async def test_auto_mode_passes_force_fetch_fallback_true():
    """In auto mode, force_fetch_fallback must always be True."""
    config = make_config()
    mock_client = MagicMock()
    with (
        patch("src.main._init_client", new_callable=AsyncMock, return_value=mock_client),
        patch("src.main.fetch_target_messages", new_callable=AsyncMock, return_value=[]) as mock_fetch,
    ):
        await run_pipeline(config, is_auto_mode=True)
        _, call_kwargs = mock_fetch.call_args
        assert call_kwargs.get("force_fetch_fallback") is True
