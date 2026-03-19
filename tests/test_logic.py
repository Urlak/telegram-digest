import pytest
from src.logic import group_messages_by_id, format_messages_to_markdown, clean_text_basic

def test_group_messages_by_id():
    messages = [
        {"group_id": 1, "group_name": "Group A", "message_id": 101, "date": "2026-03-18 10:00", "sender_name": "Alice", "text": "Hello"},
        {"group_id": 1, "group_name": "Group A", "message_id": 102, "date": "2026-03-18 10:05", "sender_name": "Bob", "text": "Hi"},
        {"group_id": 2, "group_name": "Group B", "message_id": 201, "date": "2026-03-18 11:00", "sender_name": "Charlie", "text": "Hey"},
    ]
    
    grouped = group_messages_by_id(messages)
    
    assert len(grouped) == 2
    assert grouped[1]["name"] == "Group A"
    assert len(grouped[1]["messages"]) == 2
    assert "group_id" not in grouped[1]["messages"][0]
    assert grouped[2]["name"] == "Group B"

def test_format_messages_to_markdown():
    grouped = {
        1: {
            "name": "Test Group",
            "messages": [
                {"message_id": 1, "date": "2026-03-18 12:00", "sender_name": "User", "text": "Msg 1", "reply_to_id": None},
                {"message_id": 2, "date": "2026-03-18 12:01", "sender_name": "User", "text": "Msg 2", "reply_to_id": 1},
            ]
        }
    }
    
    md = format_messages_to_markdown(grouped)
    
    assert "# SOURCE: Test Group (ID: 1)" in md
    assert "## DATE: 2026-03-18" in md
    assert "**[[12:00]] [ID:[1]] [User]**: Msg 1" in md
    assert "(reply to 1)" in md

def test_clean_text_basic():
    text = "  Hello    world! \n Visit https://google.com   for more.  "
    cleaned = clean_text_basic(text)
    
    # Check that whitespace is collapsed but URL is intact
    assert cleaned == "Hello world! Visit https://google.com for more."
    # Check empty input
    assert clean_text_basic("") == ""
    assert clean_text_basic(None) == ""
