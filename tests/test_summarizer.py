import pytest
from unittest.mock import MagicMock, patch
from src.summarizer import summarize_messages

def test_summarize_messages_empty():
    summaries, duration = summarize_messages({}, "fake_key", 100)
    assert summaries == []
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
        
        grouped_messages = {
            "123": {
                "name": "Test Group",
                "messages": [{"text": "Hello", "message_id": 1, "date": "2024-03-19 12:00:00"}]
            }
        }
        
        summaries, duration = summarize_messages(grouped_messages, "fake_key", 100)
        
        assert len(summaries) == 1
        assert "This is a summary." in summaries[0]
        assert "Test Group" in summaries[0]
        assert duration >= 0.0

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
        grouped_messages = {
            "123": {
                "name": "Group",
                "messages": [
                    {"text": "1", "message_id": 1, "date": "2024-03-19 11:00:00"},
                    {"text": "2", "message_id": 2, "date": "2024-03-19 12:00:00"},
                    {"text": "3", "message_id": 3, "date": "2024-03-19 13:00:00"}
                ]
            }
        }
        
        summaries, _ = summarize_messages(grouped_messages, "fake_key", 2)
        
        # Check that genai was called with only 2 messages
        # full_prompt contains message text... difficult to check content without parsing
        # but we can check if the response includes the notice
        assert "TRUNCATED" in summaries[0] or "latest 2 messages" in summaries[0]
