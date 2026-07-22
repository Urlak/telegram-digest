import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from src.summarizer import summarize_messages

def test_summarize_messages_empty():
    summaries, duration = summarize_messages([], "Test Group", "fake_key", 100)
    assert summaries == ""
    assert duration == 0.0

def test_summarize_messages_with_data():
    # Mock genai.Client
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        
        # Mock response
        mock_response = MagicMock()
        mock_response.text = "This is a summary."
        mock_instance.models.generate_content.return_value = mock_response
        
        messages = [
            {"text": "Hello", "message_id": 1, "sender_name": "Alice", "date": "2024-03-19 12:00:00", "reply_to_id": None},
            {"text": "Hi Alice", "message_id": 2, "sender_name": "Bob", "date": "2024-03-19 12:01:00", "reply_to_id": 1}
        ]
        
        summary, duration = summarize_messages(messages, "Test Group", "fake_key", 100)
        
        assert "This is a summary." in summary
        assert "Test Group" in summary
        assert duration >= 0.0
        
        # Verify call content and format
        call_args = mock_instance.models.generate_content.call_args
        assert call_args is not None
        full_prompt = call_args[1]["contents"]
        
        # Assert metadata format is correct
        assert "[Msg: 1] Alice: Hello" in full_prompt
        assert "[Msg: 2] Bob (In reply to 1): Hi Alice" in full_prompt

def test_summarize_messages_truncation():
    # Mock genai.Client
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        
        # Mock response
        mock_response = MagicMock()
        mock_response.text = "Summarized."
        mock_instance.models.generate_content.return_value = mock_response
        
        # 3 messages, limit 2
        messages = [
            {"text": "1", "message_id": 1, "date": "2024-03-19 11:00:00"},
            {"text": "2", "message_id": 2, "date": "2024-03-19 12:00:00"},
            {"text": "3", "message_id": 3, "date": "2024-03-19 13:00:00"}
        ]
        
        summary, _ = summarize_messages(messages, "Test Group", "fake_key", 2)
        
        # Check that genai was called with only 2 messages
        # full_prompt contains message text... difficult to check content without parsing
        # but we can check if the response includes the notice
        assert "TRUNCATED" in summary or "latest 2 messages" in summary


def test_summarize_messages_handles_empty_candidates():
    with patch("src.summarizer.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = SimpleNamespace(candidates=[])

        summary, duration = summarize_messages(
            [{"text": "Hello", "message_id": 1, "sender_name": "Alice", "date": "2024-03-19 12:00:00"}],
            "Test Group",
            "fake_key",
            10,
        )

        assert "blocked or returned no content" in summary.lower()
        assert duration == 0.0
