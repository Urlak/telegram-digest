from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import logging

import pytest

from src.contracts import SummaryResult
from src.summarizer import _format_id_ranges, _strip_message_id_refs, summarize_messages


def _response(text: str | None):
    response = MagicMock()
    response.text = text
    return response


def test_summarize_messages_empty():
    result = summarize_messages([], "Test Group", "fake_key", 100)
    assert isinstance(result, SummaryResult)
    assert result.text == ""
    assert result.api_duration == 0.0


def test_summarize_messages_with_data():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response(
            "This is a summary."
        )

        messages = [
            {
                "text": "Hello",
                "message_id": 1,
                "sender_name": "Alice",
                "date": "2024-03-19 12:00",
                "date_full": "2024-03-19 12:00:00 +03:00",
                "reply_to_id": None,
            },
            {
                "text": "Hi Alice",
                "message_id": 2,
                "sender_name": "Bob",
                "date": "2024-03-19 12:01",
                "date_full": "2024-03-19 12:01:00 +03:00",
                "reply_to_id": 1,
            },
        ]

        result = summarize_messages(messages, "Test Group", "fake_key", 100)

        assert "This is a summary." in result.text
        assert "Test Group" in result.text
        assert result.api_duration >= 0.0
        assert result.used_count == 2
        assert result.used_message_ids == {1, 2}

        call_args = mock_instance.models.generate_content.call_args
        assert call_args is not None
        contents = call_args[1]["contents"]
        config = call_args[1]["config"]

        assert "[2024-03-19 12:00:00 +03:00] [Msg: 1] Alice: Hello" in contents
        assert (
            "[2024-03-19 12:01:00 +03:00] [Msg: 2] Bob (In reply to 1): Hi Alice"
            in contents
        )
        assert "ПРАВИЛА" in config["system_instruction"]
        assert "Test Group" in config["system_instruction"]
        assert "Главное" in config["system_instruction"]
        assert config["temperature"] == 0.2
        # Message IDs are for threading/logs only, never part of the digest.
        assert "Msg: [ID]" not in config["system_instruction"]
        assert "ключевые ID" not in config["system_instruction"]
        # The topic template must not invite literal square brackets.
        assert "### [Название темы]" not in config["system_instruction"]
        assert "### Название темы" in config["system_instruction"]
        # Anti-duplication and anti-merging guidance is part of the contract.
        assert "Не пересказывай темы" in config["system_instruction"]
        assert "Не объединяй разные обсуждения" in config["system_instruction"]


def test_previous_digest_is_included_as_context():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response("ok")

        messages = [
            {
                "text": "Hello",
                "message_id": 1,
                "sender_name": "Alice",
                "date": "2024-03-19 12:00",
                "date_full": "2024-03-19 12:00:00 +03:00",
                "reply_to_id": None,
            }
        ]

        summarize_messages(
            messages, "Test Group", "fake_key", 100, previous_digest="Прошлый дайджест."
        )
        instruction = mock_instance.models.generate_content.call_args[1]["config"][
            "system_instruction"
        ]
        assert "Прошлый дайджест." in instruction
        assert "НАЧАЛО ПРЕДЫДУЩЕГО ДАЙДЖЕСТА" in instruction

        summarize_messages(messages, "Test Group", "fake_key", 100)
        instruction = mock_instance.models.generate_content.call_args[1]["config"][
            "system_instruction"
        ]
        assert "НАЧАЛО ПРЕДЫДУЩЕГО ДАЙДЖЕСТА" not in instruction


def test_format_id_ranges_compacts_consecutive_ids():
    assert _format_id_ranges({3195, 3196, 3197, 3220}) == "3195-3197, 3220"
    assert _format_id_ranges([3231, 3232, 3234]) == "3231-3232, 3234"
    assert _format_id_ranges([]) == ""


def test_strip_message_id_refs_removes_technical_suffix():
    text = "Обсудили релиз. (Иван, Пётр | Msg: 3195-3220, 3231-3232)"
    assert _strip_message_id_refs(text) == "Обсудили релиз. (Иван, Пётр)"

    assert _strip_message_id_refs("Тема (Msg: 1, 2)") == "Тема"
    assert _strip_message_id_refs("Без ID") == "Без ID"


def test_summarizer_strips_ids_echoed_by_model():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response(
            "## Темы\n\n### Релиз\n\nВыпустили версию. (Иван | Msg: 3195-3220)\n"
        )

        result = summarize_messages(
            [{"text": "hi", "message_id": 3195, "date": "2024-03-19 12:00"}],
            "Test Group",
            "fake_key",
            10,
        )

    assert "Msg:" not in result.text
    assert "(Иван)" in result.text


def test_summarizer_logs_used_ids_in_ranges(caplog):
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response("Summary.")

        messages = [
            {"text": "a", "message_id": 1, "date": "2024-03-19 11:00"},
            {"text": "b", "message_id": 2, "date": "2024-03-19 11:01"},
            {"text": "c", "message_id": 4, "date": "2024-03-19 11:02"},
        ]

        with caplog.at_level(logging.DEBUG, logger="src.summarizer"):
            summarize_messages(messages, "Test Group", "fake_key", 100)

    assert "[LLM_INPUT_IDS]" in caplog.text
    assert "1-2, 4" in caplog.text


def test_summarize_messages_truncation_keeps_latest_by_default():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response("Summarized.")

        messages = [
            {"text": "first", "message_id": 1, "date": "2024-03-19 11:00"},
            {"text": "second", "message_id": 2, "date": "2024-03-19 12:00"},
            {"text": "third", "message_id": 3, "date": "2024-03-19 13:00"},
        ]

        result = summarize_messages(messages, "Test Group", "fake_key", 2)

        assert result.truncated is True
        assert result.used_count == 2
        assert result.used_message_ids == {2, 3}
        assert "Внимание" in result.text
        assert "последние 2" in result.text

        contents = mock_instance.models.generate_content.call_args[1]["contents"]
        assert "second" in contents
        assert "third" in contents
        assert "first" not in contents


def test_summarize_messages_truncation_can_keep_oldest():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response("Summarized.")

        messages = [
            {"text": "first", "message_id": 1, "date": "2024-03-19 11:00"},
            {"text": "second", "message_id": 2, "date": "2024-03-19 12:00"},
            {"text": "third", "message_id": 3, "date": "2024-03-19 13:00"},
        ]

        result = summarize_messages(
            messages, "Test Group", "fake_key", 2, prefer_oldest=True
        )

        assert result.truncated is True
        assert result.used_message_ids == {1, 2}
        contents = mock_instance.models.generate_content.call_args[1]["contents"]
        assert "first" in contents
        assert "second" in contents
        assert "third" not in contents


def test_summarize_messages_char_budget_always_includes_one_block():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _response("Summarized.")

        messages = [
            {"text": "a" * 500, "message_id": 1, "date": "2024-03-19 11:00"},
            {"text": "b" * 500, "message_id": 2, "date": "2024-03-19 12:00"},
        ]

        result = summarize_messages(
            messages, "Test Group", "fake_key", 100, max_chars=10
        )

        assert result.used_count == 1
        assert result.truncated is True


def test_summarize_messages_handles_empty_candidates():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = SimpleNamespace(
            candidates=[]
        )

        with pytest.raises(RuntimeError, match="blocked or returned no content"):
            summarize_messages(
                [
                    {
                        "text": "Hello",
                        "message_id": 1,
                        "sender_name": "Alice",
                        "date": "2024-03-19 12:00",
                    }
                ],
                "Test Group",
                "fake_key",
                10,
            )


def test_summarize_messages_raises_on_api_error():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.side_effect = Exception(
            "503 UNAVAILABLE: High demand"
        )

        with pytest.raises(Exception, match="503 UNAVAILABLE"):
            summarize_messages(
                [
                    {
                        "text": "Hello",
                        "message_id": 1,
                        "sender_name": "Alice",
                        "date": "2024-03-19 12:00",
                    }
                ],
                "Test Group",
                "fake_key",
                10,
                retries=0,
            )
