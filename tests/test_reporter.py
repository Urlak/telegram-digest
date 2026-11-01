from datetime import datetime

from src.contracts import ReportMetadata
from src.reporter import build_report, build_report_paths, finalize_report


def test_build_report_no_messages():
    report = build_report("", "Group 1")
    assert "No messages found" in report


def test_build_report_with_summaries():
    summary_text = "### Summary for Group 1\n\nTest summary"
    report = build_report(summary_text, "Group 1")
    assert "Test summary" in report
    assert "Group 1" in report


def test_build_report_paths_include_group_id_and_latest(tmp_path):
    archived, latest = build_report_paths(
        str(tmp_path), "Group 1", "-100123", timestamp=datetime(2024, 3, 19, 12, 0, 0)
    )

    assert archived.endswith("digest_Group_1_-100123_2024-03-19_120000.md")
    assert latest.endswith("digest_Group_1_-100123_latest.md")
    assert archived != latest


def test_build_report_paths_keep_cyrillic_names(tmp_path):
    archived, _ = build_report_paths(str(tmp_path), "Рабочий чат", "-1009")

    assert "Рабочий_чат" in archived


def test_finalize_report_writes_metadata_and_latest(tmp_path):
    archived, latest = build_report_paths(
        str(tmp_path), "Group 1", "-100123", timestamp=datetime(2024, 3, 19, 12, 0, 0)
    )
    metadata = ReportMetadata(
        group_name="Group 1",
        group_id="-100123",
        generated_at="2024-03-19 12:00 (UTC+00:00)",
        period_start="2024-03-19 10:00",
        period_end="2024-03-19 11:00",
        model="gemini-2.5-flash",
        timezone="UTC",
        source_message_count=10,
        collapsed_block_count=7,
        llm_message_count=5,
        llm_char_count=1234,
        truncated=True,
        api_duration=2.5,
        unread_count=10,
        remaining_unread=3,
        fetch_mode="unread",
        acknowledged=True,
        acknowledged_max_id=42,
    )

    finalize_report("DIGEST BODY\n", metadata, archived, latest_file=latest)

    content = open(archived, encoding="utf-8").read()
    assert "DIGEST BODY" in content
    assert "- Group: Group 1 (ID: -100123)" in content
    assert "- Gemini model: gemini-2.5-flash" in content
    assert "- Input truncated: yes" in content
    assert "- Read acknowledged: yes (max_id=42)" in content

    assert open(latest, encoding="utf-8").read() == content
