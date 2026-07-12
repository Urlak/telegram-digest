import pytest
from src.reporter import build_report

def test_build_report_no_messages():
    # Test with empty grouped_messages
    report = build_report([], {}, ["Group 1"])
    assert "No messages found" in report
    assert "Group 1" not in report # It shouldn't show group name if no digest

def test_build_report_with_summaries():
    # Test with new summaries
    new_summaries = ["### Summary for Group 1\n\nTest summary"]
    grouped_messages = {"123": {"name": "Group 1", "messages": []}}
    report = build_report(new_summaries, grouped_messages, ["123"])
    assert "Test summary" in report
    assert "Group 1" in report
