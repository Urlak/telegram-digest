import pytest
from src.logic import (
    clean_text_basic,
    format_duration,
    format_messages_to_markdown,
    normalize_links,
)


def test_format_messages_to_markdown():
    messages = [
        {"message_id": 1, "date": "2026-03-18 12:00", "sender_name": "User", "text": "Msg 1", "reply_to_id": None},
        {"message_id": 2, "date": "2026-03-18 12:01", "sender_name": "User", "text": "Msg 2", "reply_to_id": 1},
    ]
    
    md = format_messages_to_markdown(messages, "Test Group", "1")
    
    assert "# SOURCE: Test Group (ID: 1)" in md
    assert "## DATE: 2026-03-18" in md
    assert "**[[12:00]] [ID:[1]] [User]**: Msg 1" in md
    assert "(reply to 1)" in md

def test_clean_text_basic():
    text = "  Hello    world! \n Visit https://google.com   for more.  "
    cleaned = clean_text_basic(text)
    
    # Check that URLs are preserved while whitespace is collapsed
    assert cleaned == "Hello world!\nVisit https://google.com for more."
    
    # Check multiple newlines are collapsed to maximum double newlines (\n\n)
    text_with_newlines = "Line 1\n\n\n\nLine 2\n\nLine 3"
    assert clean_text_basic(text_with_newlines) == "Line 1\n\nLine 2\n\nLine 3"
    
    # Check empty input
    assert clean_text_basic("") == ""
    assert clean_text_basic(None) == ""

def test_collapse_consecutive_messages():
    from src.processor import collapse_consecutive_messages
    
    messages = [
        {"message_id": 101, "reply_to_id": None, "sender_name": "Alice", "date": "2026-03-18 10:00", "text": "Hi all"},
        {"message_id": 102, "reply_to_id": None, "sender_name": "Alice", "date": "2026-03-18 10:03", "text": "How is it going?"},
        {"message_id": 103, "reply_to_id": 101, "sender_name": "Bob", "date": "2026-03-18 10:04", "text": "Good!"},
        {"message_id": 104, "reply_to_id": None, "sender_name": "Bob", "date": "2026-03-18 10:05", "text": "How about you?"},
        {"message_id": 105, "reply_to_id": 102, "sender_name": "Charlie", "date": "2026-03-18 10:06", "text": "Agree with Alice"},
        {"message_id": 106, "reply_to_id": None, "sender_name": "Alice", "date": "2026-03-18 10:12", "text": "Long time no see"}  # 9 minutes gap from 102
    ]
    
    collapsed = collapse_consecutive_messages(messages, max_gap_minutes=5.0)
    
    # Let's check results:
    # 1. 101 and 102 should collapse since same sender, 3 mins gap, both None reply_to_id.
    #    Text should be "Hi all\n\nHow is it going?"
    # 2. 103: Bob, reply to 101.
    # 3. 104: Bob, reply to None. Different thread context than 103, so should NOT collapse.
    # 4. 105: Charlie, reply to 102.
    #    Since 102 collapsed into 101, 105's reply_to_id should be rewritten to 101!
    # 5. 106: Alice, 9 mins gap. Should not collapse.
    
    assert len(collapsed) == 5
    
    # Check Alice's collapsed block (101 & 102)
    assert collapsed[0]["message_id"] == 101
    assert collapsed[0]["text"] == "Hi all\n\nHow is it going?"
    assert collapsed[0]["merged_ids"] == [101, 102]
    
    # Check Bob's reply block (103)
    assert collapsed[1]["message_id"] == 103
    assert collapsed[1]["reply_to_id"] == 101  # stays 101
    
    # Check Bob's top-level block (104)
    assert collapsed[2]["message_id"] == 104
    assert collapsed[2]["reply_to_id"] is None
    
    # Check Charlie's reply block (105)
    assert collapsed[3]["message_id"] == 105
    # Important: reply_to_id was 102, which got merged into 101. So it must be rewritten to 101!
    assert collapsed[3]["reply_to_id"] == 101
    
    # Check Alice's late block (106)
    assert collapsed[4]["message_id"] == 106
    assert collapsed[4]["text"] == "Long time no see"
    assert collapsed[0]["date"] == "2026-03-18 10:03"


def test_clean_text_preserves_code_blocks_and_indentation():
    text = (
        "Example:\n\n"
        "```python\n"
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "```\n\n"
        "1. First\n"
        "   continuation with   spaces\n"
        "- Second\n"
    )

    cleaned = clean_text_basic(text)

    assert "```python" in cleaned
    assert "    if x:" in cleaned
    assert "        return 1" in cleaned
    assert "   continuation with   spaces" in cleaned
    assert "- Second" in cleaned


def test_normalize_links_counts_platforms_and_keeps_code():
    text = (
        "See https://youtu.be/a and https://youtube.com/watch?v=b, "
        "plus https://example.com/x and t.me/channel. "
        "Code `https://youtu.be/keep` stays."
    )

    normalized = normalize_links(text)

    assert "[YT ×2]" in normalized
    assert "[Web: example.com]" in normalized
    assert "[TG]" in normalized
    assert "https://youtu.be/a" not in normalized
    assert "`https://youtu.be/keep`" in normalized


def test_format_duration():
    assert format_duration(42) == "0:42"
    assert format_duration(195) == "3:15"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(None) == "0:00"


def test_collapse_respects_max_block_chars():
    from src.processor import collapse_consecutive_messages

    messages = [
        {"message_id": 1, "reply_to_id": None, "sender_name": "Alice", "date": "2026-03-18 10:00", "text": "a" * 40},
        {"message_id": 2, "reply_to_id": None, "sender_name": "Alice", "date": "2026-03-18 10:01", "text": "b" * 40},
    ]

    collapsed = collapse_consecutive_messages(messages, max_block_chars=50)

    assert len(collapsed) == 2

