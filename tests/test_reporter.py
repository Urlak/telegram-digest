import pytest
from unittest.mock import patch
from src.reporter import build_report

def test_build_report_no_messages():
    # Test with empty grouped_messages and no cached digests
    # We mock get_latest_digest to return None
    with patch("src.reporter.get_latest_digest", return_value=None):
        report = build_report([], {}, ["Group 1"], "fake_db.db")
        assert "No messages found" in report
        assert "Group 1" not in report # It shouldn't show group name if no digest

def test_build_report_with_summaries():
    # Test with new summaries
    new_summaries = ["### Summary for Group 1\n\nTest summary"]
    grouped_messages = {"123": {"name": "Group 1", "messages": []}}
    report = build_report(new_summaries, grouped_messages, ["123"], "fake_db.db")
    assert "Test summary" in report
    assert "Group 1" in report

def test_build_report_with_cached_digest():
    # Test with cached digest
    with patch("src.reporter.get_latest_digest", return_value="Cached summary text"):
        report = build_report([], {}, ["Group 1"], "fake_db.db")
        assert "CACHED DIGEST" in report
        assert "Cached summary text" in report
