import pytest
from src.reporter import build_report

def test_build_report_no_messages():
    # Test with empty summary
    report = build_report("", "Group 1")
    assert "No messages found" in report

def test_build_report_with_summaries():
    # Test with new summary
    summary_text = "### Summary for Group 1\n\nTest summary"
    report = build_report(summary_text, "Group 1")
    assert "Test summary" in report
    assert "Group 1" in report
