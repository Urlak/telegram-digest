import pytest
from unittest.mock import patch
from src.processor import filter_unprocessed_messages

def test_filter_unprocessed_messages():
    mock_messages = [
        {"message_id": 1, "group_id": 10, "group_name": "Test Group"},
        {"message_id": 2, "group_id": 10, "group_name": "Test Group"},
        {"message_id": 3, "group_id": 10, "group_name": "Test Group"},
    ]
    db_path = "mock.db"
    
    # Mock is_message_processed to return True for ID 1 and False for others
    with patch("src.processor.is_message_processed") as mock_check:
        mock_check.side_effect = lambda path, mid, gid, gname: mid == 1
        
        new_msgs = filter_unprocessed_messages(mock_messages, db_path)
        
        # mid == 1 returns True, so is_message_processed is True -> NOT is_message_processed is False -> Not added
        # others return False -> NOT is_message_processed is True -> Added
        assert len(new_msgs) == 2
        assert new_msgs[0]["message_id"] == 2
        assert new_msgs[1]["message_id"] == 3
        
        # Verify call count
        assert mock_check.call_count == 3
