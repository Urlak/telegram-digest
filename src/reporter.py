import logging
import os
import re
import tempfile
from datetime import datetime

from src.contracts import ReportMetadata

logger = logging.getLogger(__name__)


def _safe_name(value: str, fallback: str = "chat") -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", value or "").strip()
    cleaned = re.sub(r"[\s]+", "_", cleaned)
    return cleaned or fallback


def build_report_paths(
    data_dir: str,
    group_name: str,
    group_id: str,
    prefix: str = "digest",
    timestamp: datetime | None = None,
) -> tuple[str, str]:
    """Builds archived and ``latest`` output paths.

    The group ID is part of the filename so two chats with the same title do not
    overwrite each other.  Each run gets its own timestamped file; ``latest`` is
    an additional convenience copy.
    """
    safe_group = _safe_name(group_name)
    safe_id = re.sub(r"[^\w.-]", "", str(group_id or "")) or "unknown"
    stamp = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    base = f"{prefix}_{safe_group}_{safe_id}"

    archived = os.path.join(data_dir, f"{base}_{stamp}.md")
    latest = os.path.join(data_dir, f"{base}_latest.md")
    return archived, latest


def _metadata_block(metadata: ReportMetadata) -> str:
    lines = [
        "",
        "[METADATA]",
        f"- Group: {metadata.group_name} (ID: {metadata.group_id})",
        f"- Generated at: {metadata.generated_at or 'N/A'}",
        f"- Message period: {metadata.period_start or 'N/A'} — {metadata.period_end or 'N/A'}",
        f"- Timezone: {metadata.timezone or 'system local'}",
        f"- Gemini model: {metadata.model or 'N/A'}",
        f"- Fetch mode: {metadata.fetch_mode or 'N/A'}",
        f"- Source messages: {metadata.source_message_count}",
        f"- Collapsed blocks: {metadata.collapsed_block_count}",
        f"- Blocks sent to LLM: {metadata.llm_message_count}",
        f"- Characters sent to LLM: {metadata.llm_char_count}",
        f"- Input truncated: {'yes' if metadata.truncated else 'no'}",
        f"- API processing time: {metadata.api_duration:.2f}s",
    ]

    if metadata.config_hours_back is not None:
        lines.append(f"- Config lookback window: {metadata.config_hours_back}h")
    if metadata.unread_count:
        lines.append(f"- Unread count at fetch: {metadata.unread_count}")
    if metadata.remaining_unread:
        lines.append(f"- Remaining unread after run: {metadata.remaining_unread}")
    if metadata.incomplete:
        lines.append("- Fetch incomplete: yes (nothing acknowledged)")
    if metadata.acknowledged:
        suffix = (
            f" (max_id={metadata.acknowledged_max_id})"
            if metadata.acknowledged_max_id is not None
            else ""
        )
        lines.append(f"- Read acknowledged: yes{suffix}")
    else:
        lines.append("- Read acknowledged: no")

    return "\n".join(lines) + "\n"


def build_report(
    summary: str,
    group_name: str,
    group_id: str | None = None,
    metadata: ReportMetadata | None = None,
) -> str:
    """Combines summary text into the standard digest report header."""
    title = f"# Дайджест: {group_name}"
    if group_id:
        title += f" (ID: {group_id})"

    digest_output = (
        "TELEGRAM DIGEST OUTPUT\n"
        + "=" * 40
        + "\n\n"
        + title
        + "\n\n"
    )

    if summary:
        digest_output += summary + "\n" + "-" * 40 + "\n"
    else:
        digest_output += "### Summary\n\n*No messages found.*\n" + "-" * 40 + "\n"

    return digest_output


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=".tmp_", suffix=".md", dir=directory, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def write_text_atomic(path: str, content: str) -> None:
    """Public atomic text writer used by report and export paths."""
    _atomic_write(path, content)


def finalize_report(
    digest_output: str,
    metadata: ReportMetadata,
    output_file: str,
    latest_file: str | None = None,
) -> None:
    """Appends execution metadata and writes the report atomically.

    Both the timestamped archive file and the optional ``latest`` copy are
    written.  Previous reports are never overwritten.
    """
    final_content = digest_output + _metadata_block(metadata)

    _atomic_write(output_file, final_content)
    if latest_file and latest_file != output_file:
        _atomic_write(latest_file, final_content)

    logger.info("Report saved to %s", output_file)
