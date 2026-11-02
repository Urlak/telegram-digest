import asyncio
import inspect
import logging
import os
import time
from typing import Callable

from telethon import TelegramClient

from src.config import AppConfig
from src.contracts import FetchOutcome, ReportMetadata, SummaryResult
from src.logic import format_messages_to_markdown
from src.processor import collapse_consecutive_messages
from src.reporter import (
    build_report,
    build_report_paths,
    finalize_report,
    write_text_atomic,
)
from src.summarizer import GEMINI_MODEL, summarize_messages
from src.telegram_client import (
    _find_target_dialog,
    fetch_target_messages_with_stats,
    mark_target_messages_read,
)
from src.timeutil import now_with_offset, resolve_timezone

logger = logging.getLogger(__name__)

_pipeline_lock = asyncio.Lock()


async def get_available_dialogs(client: TelegramClient, limit: int = 100) -> list[dict]:
    """Iterates active user dialogs and filters for channels and groups."""
    dialogs = []
    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.is_group or dialog.is_channel:
            dialogs.append(
                {
                    "id": str(dialog.id),
                    "name": dialog.name or "Unknown",
                    "unread_count": dialog.unread_count,
                }
            )

    dialogs.sort(key=lambda d: (d["unread_count"] == 0, str(d["name"]).lower()))
    return dialogs


def _export_messages(
    config: AppConfig, messages: list[dict], group_name: str, group_id: str
) -> str:
    """Exports the original messages to an archived Markdown file."""
    data_dir = os.path.dirname(config.session_path)
    report_path, latest_path = build_report_paths(
        data_dir, group_name, group_id, prefix="clean_messages"
    )

    content = format_messages_to_markdown(messages, group_name, group_id)
    write_text_atomic(report_path, content)
    write_text_atomic(latest_path, content)

    logger.info("EXPORT_ONLY is ON. Saved '%s' to %s.", group_name, report_path)
    return report_path


def _coerce_summary_result(result, blocks: list[dict]) -> SummaryResult:
    """Ensures a SummaryResult has defaulted metadata."""
    if not isinstance(result, SummaryResult):
        return SummaryResult(text="", model=GEMINI_MODEL, total_count=len(blocks))
    if not result.used_message_ids:
        result.used_message_ids = {
            mid
            for b in blocks
            for mid in (b.get("merged_ids") or [b.get("message_id")])
            if mid is not None
        }
    if not result.total_count:
        result.total_count = len(blocks)
    if not result.model:
        result.model = GEMINI_MODEL
    return result


def _compute_ack_max_id(
    outcome: FetchOutcome, summary: SummaryResult
) -> int | None:
    """Returns a safe high-water mark for a read acknowledgement.

    Only unread-mode batches are acknowledged.  Without truncation the whole
    scanned batch was either processed or intentionally filtered.  With
    truncation the acknowledgement stops at the last message of the contiguous
    prefix that was actually sent to the LLM (trailing filtered messages are
    still safe and are included).
    """
    if outcome.mode != "unread" or outcome.incomplete:
        return None
    if not outcome.scanned_ids:
        return None

    if not summary.truncated:
        return outcome.scanned_ids[-1]

    used_ids = summary.used_message_ids
    if not used_ids:
        # Nothing was sent to the LLM.  If every scanned message was filtered,
        # the whole batch is safe to acknowledge; otherwise stop.
        return None if outcome.parsed_ids else outcome.scanned_ids[-1]

    ack_max_id: int | None = None
    for message_id in outcome.scanned_ids:
        if message_id in used_ids or message_id not in outcome.parsed_ids:
            ack_max_id = message_id
        else:
            break
    return ack_max_id


def _remaining_after_ack(outcome: FetchOutcome, ack_max_id: int | None) -> int:
    if ack_max_id is None:
        return outcome.remaining_unread or outcome.unread_count
    acknowledged = sum(1 for message_id in outcome.scanned_ids if message_id <= ack_max_id)
    return max(0, outcome.unread_count - acknowledged)


def _result(
    status: str,
    *,
    group_name: str,
    group_id: str,
    summary: str | None = None,
    message_count: int = 0,
    api_duration: float = 0.0,
    report_path: str | None = None,
    error: str | None = None,
    incomplete: bool = False,
    acknowledged: bool = False,
    acknowledged_max_id: int | None = None,
    remaining_unread: int = 0,
    truncated: bool = False,
    model: str = "",
    collapsed_block_count: int = 0,
    llm_message_count: int = 0,
    llm_char_count: int = 0,
) -> dict:
    return {
        "status": status,
        "group_name": group_name,
        "group_id": group_id,
        "summary": summary,
        "message_count": message_count,
        "api_duration": api_duration,
        "report_path": report_path,
        "error": error,
        "incomplete": incomplete,
        "acknowledged": acknowledged,
        "acknowledged_max_id": acknowledged_max_id,
        "remaining_unread": remaining_unread,
        "truncated": truncated,
        "model": model,
        "collapsed_block_count": collapsed_block_count,
        "llm_message_count": llm_message_count,
        "llm_char_count": llm_char_count,
    }


def _message_range(messages: list[dict]) -> str:
    """Describes the batch as ``12:40 -> 18:35 (5h55m)``."""
    first = messages[0].get("date") or "?"
    last = messages[-1].get("date") or "?"
    start = messages[0].get("timestamp")
    end = messages[-1].get("timestamp")
    span = ""
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        minutes = int((end - start) // 60)
        if minutes < 60:
            formatted = f"{minutes}m"
        else:
            hours, mins = divmod(minutes, 60)
            formatted = f"{hours}h{mins:02d}m" if hours < 24 else f"{hours // 24}d{hours % 24}h"
        span = f" ({formatted})"
    if len(first) >= 16 and len(last) >= 16 and first[:10] == last[:10]:
        return f"{first[11:16]} -> {last[11:16]}{span}"
    return f"{first} -> {last}{span}"


def _report_size(path: str | None) -> str:
    """Human readable size of a written report, or ``n/a`` when it is missing."""
    try:
        return f"{os.path.getsize(path) / 1024:.1f} KB"
    except (OSError, TypeError):
        return "n/a"


async def execute_digest_pipeline(
    client: TelegramClient,
    config: AppConfig,
    target_group: str,
    unread_only: bool = True,
    hours_back: int | None = None,
    limit_msgs: int | None = None,
    export_only: bool = False,
    target_dialog=None,
    fetch_messages_fn: Callable | None = None,
    collapse_messages_fn: Callable | None = None,
    summarize_messages_fn: Callable | None = None,
    export_messages_fn: Callable | None = None,
    build_report_fn: Callable | None = None,
    finalize_report_fn: Callable | None = None,
    mark_messages_read_fn: Callable | None = None,
) -> dict:
    """Executes extraction, collapsing, summarization, reporting and ack.

    The returned dictionary always contains ``status`` (``success``,
    ``no_messages``, ``incomplete`` or ``error``), ``incomplete``,
    ``acknowledged`` and ``remaining_unread``.  Read receipts are only sent
    after a successful summary/export and only for a contiguous, fully
    processed/filtered unread batch.
    """
    effective_hours = hours_back if hours_back is not None else config.hours_back
    effective_limit = limit_msgs if limit_msgs is not None else config.message_limit
    fetch_limit = min(effective_limit, config.max_fetch_limit)

    started = time.perf_counter()
    async with _pipeline_lock:
        waited = time.perf_counter() - started
        try:
            force_fetch_fallback = not unread_only

            current_dialog = target_dialog
            if current_dialog is None:
                current_dialog = await _find_target_dialog(client, target_group)

            group_name = current_dialog.name if current_dialog else target_group
            group_id = str(current_dialog.id) if current_dialog else target_group

            fetch_messages = fetch_messages_fn or fetch_target_messages_with_stats
            collapse_messages = collapse_messages_fn or collapse_consecutive_messages
            summarize_fn = summarize_messages_fn or summarize_messages
            export_messages = export_messages_fn or _export_messages
            build_report_func = build_report_fn or build_report
            finalize_report_func = finalize_report_fn or finalize_report
            mark_read = mark_messages_read_fn or mark_target_messages_read

            fetch_result = await fetch_messages(
                client,
                target_group,
                limit_msgs=fetch_limit,
                hours_back=effective_hours,
                force_fetch_fallback=force_fetch_fallback,
                dialog=current_dialog,
                timezone_name=config.timezone,
                timeout_seconds=config.telegram_timeout_seconds,
                retries=config.request_retries,
                max_flood_wait=config.max_flood_wait_seconds,
            )
            outcome = (
                fetch_result
                if isinstance(fetch_result, FetchOutcome)
                else FetchOutcome()
            )

            if outcome.messages:
                group_name = outcome.messages[0].get("group_name") or group_name
                group_id = outcome.messages[0].get("group_id") or group_id

            if outcome.incomplete and not outcome.messages:
                logger.error(
                    'Fetch incomplete for "%s": %s', group_name, outcome.error
                )
                return _result(
                    "incomplete",
                    group_name=group_name,
                    group_id=group_id,
                    error=outcome.error or "Message fetch failed.",
                    incomplete=True,
                    remaining_unread=outcome.remaining_unread,
                )

            all_messages = outcome.messages

            if not all_messages:
                ack_max_id = None
                if outcome.mode == "unread" and not outcome.incomplete and outcome.scanned_ids:
                    ack_max_id = outcome.batch_max_id

                acknowledged = False
                if ack_max_id:
                    acknowledged = await mark_read(
                        client,
                        target_group,
                        dialog=current_dialog,
                        max_id=ack_max_id,
                    )

                remaining = _remaining_after_ack(
                    outcome, ack_max_id if acknowledged else None
                )
                if outcome.scanned_count and not outcome.parsed_ids:
                    logger.info(
                        "No messages processed because all %s scanned items "
                        "were filtered out by text validators.",
                        outcome.scanned_count,
                    )
                elif outcome.mode == "none":
                    logger.info(
                        "No messages processed because there are no unread "
                        "messages and fallback mode is disabled."
                    )
                else:
                    logger.info("No messages processed because no valid items were found.")

                logger.info(
                    '[FETCH] Group: "%s" | Mode: %s | Unread: %s | '
                    "Messages fetched: 0 | Acknowledged: %s | Remaining unread: %s",
                    group_name,
                    outcome.mode,
                    outcome.unread_count,
                    acknowledged,
                    remaining,
                )
                return _result(
                    "no_messages",
                    group_name=group_name,
                    group_id=group_id,
                    summary="No matching messages found.",
                    acknowledged=acknowledged,
                    acknowledged_max_id=ack_max_id if acknowledged else None,
                    remaining_unread=remaining,
                    incomplete=False,
                )

            collapsed_messages = collapse_messages(
                all_messages, max_block_chars=config.max_block_chars
            )

            if export_only:
                report_path = export_messages(config, all_messages, group_name, group_id)

                predicted_ack = _compute_ack_max_id(
                    outcome, SummaryResult(text="", truncated=False)
                )
                acknowledged = False
                if predicted_ack:
                    acknowledged = await mark_read(
                        client,
                        target_group,
                        dialog=current_dialog,
                        max_id=predicted_ack,
                    )

                remaining = _remaining_after_ack(
                    outcome, predicted_ack if acknowledged else None
                )
                status = "incomplete" if outcome.incomplete else "success"
                logger.info(
                    '[PIPELINE_COMPLETE] Group: "%s" (%s) | Exported: %s msgs | '
                    "Mode: %s | Unread: %s->%s | Range: %s | Wait: %.2fs | "
                    "Total: %.2fs | Ack: max_id=%s | Status: %s | Report: %s (%s)",
                    group_name,
                    group_id,
                    len(all_messages),
                    outcome.mode,
                    outcome.unread_count,
                    remaining,
                    _message_range(all_messages),
                    waited,
                    time.perf_counter() - started,
                    predicted_ack if acknowledged else "no",
                    status.upper(),
                    report_path,
                    _report_size(report_path),
                )
                return _result(
                    status,
                    group_name=group_name,
                    group_id=group_id,
                    summary=f"Messages exported to {os.path.basename(report_path)}",
                    message_count=len(all_messages),
                    report_path=report_path,
                    error=outcome.error if outcome.incomplete else None,
                    incomplete=outcome.incomplete,
                    acknowledged=acknowledged,
                    acknowledged_max_id=predicted_ack if acknowledged else None,
                    remaining_unread=remaining,
                    collapsed_block_count=len(collapsed_messages),
                )

            summary_kwargs = {
                "messages": collapsed_messages,
                "group_name": group_name,
                "api_key": config.gemini_api_key,
                "max_messages": config.max_llm_messages,
                "max_chars": config.max_llm_chars,
                "max_block_chars": config.max_block_chars,
                "timezone_name": config.timezone,
                "prefer_oldest": outcome.mode == "unread",
                "timeout_seconds": config.gemini_timeout_seconds,
                "retries": config.request_retries,
            }
            summarize_coro = (
                summarize_fn(**summary_kwargs)
                if inspect.iscoroutinefunction(summarize_fn)
                else asyncio.to_thread(summarize_fn, **summary_kwargs)
            )
            raw_summary = await asyncio.wait_for(
                summarize_coro, timeout=config.gemini_timeout_seconds + 5
            )
            summary = _coerce_summary_result(raw_summary, collapsed_messages)

            tz, tz_label = resolve_timezone(config.timezone)
            period_start = all_messages[0].get("date_full") or all_messages[0].get("date")
            period_end = all_messages[-1].get("date_full") or all_messages[-1].get("date")

            data_dir = os.path.dirname(config.session_path)
            report_path, latest_path = build_report_paths(
                data_dir, group_name, group_id
            )

            predicted_ack = _compute_ack_max_id(outcome, summary)
            metadata = ReportMetadata(
                group_name=group_name,
                group_id=group_id,
                generated_at=f"{now_with_offset(tz)} ({tz_label})",
                period_start=period_start,
                period_end=period_end,
                model=summary.model or GEMINI_MODEL,
                timezone=tz_label,
                source_message_count=len(all_messages),
                collapsed_block_count=len(collapsed_messages),
                llm_message_count=summary.used_count,
                llm_char_count=summary.used_chars,
                truncated=summary.truncated,
                api_duration=summary.api_duration,
                unread_count=outcome.unread_count,
                remaining_unread=_remaining_after_ack(outcome, predicted_ack),
                fetch_mode=outcome.mode,
                incomplete=outcome.incomplete,
                acknowledged=predicted_ack is not None,
                acknowledged_max_id=predicted_ack,
                config_hours_back=effective_hours,
            )

            report_output = build_report_func(
                summary.text, group_name, group_id, metadata
            )
            finalize_report_func(
                report_output, metadata, report_path, latest_file=latest_path
            )

            acknowledged = False
            if predicted_ack:
                acknowledged = await mark_read(
                    client,
                    target_group,
                    dialog=current_dialog,
                    max_id=predicted_ack,
                )

            remaining = _remaining_after_ack(
                outcome, predicted_ack if acknowledged else None
            )

            if acknowledged != metadata.acknowledged:
                metadata.acknowledged = acknowledged
                metadata.acknowledged_max_id = predicted_ack if acknowledged else None
                metadata.remaining_unread = remaining
                finalize_report_func(
                    report_output, metadata, report_path, latest_file=latest_path
                )

            status = "incomplete" if outcome.incomplete else "success"
            logger.info(
                '[PIPELINE_COMPLETE] Group: "%s" (%s) | Mode: %s | Unread: %s->%s | '
                "Range: %s | Msgs: %s | Senders: %s | Skipped: %s (age %s, filter %s) | "
                "Blocks: %s->%s | LLM: %s blocks / %s chars / %.2fs | Wait: %.2fs | "
                "Total: %.2fs | Truncated: %s | Ack: max_id=%s | Status: %s | "
                "Report: %s (%s)",
                group_name,
                group_id,
                outcome.mode,
                outcome.unread_count,
                remaining,
                _message_range(all_messages),
                len(all_messages),
                len({m.get("sender_name") for m in all_messages if m.get("sender_name")}),
                outcome.age_skipped + outcome.filter_skipped,
                outcome.age_skipped,
                outcome.filter_skipped,
                len(all_messages),
                len(collapsed_messages),
                summary.used_count,
                summary.used_chars,
                summary.api_duration,
                waited,
                time.perf_counter() - started,
                summary.truncated,
                predicted_ack if acknowledged else "no",
                status.upper(),
                report_path,
                _report_size(report_path),
            )

            if summary.truncated:
                logger.warning(
                    '[DIGEST_TRUNCATED] Group: "%s" | LLM got %s of %s blocks '
                    "(%s chars) | raise MAX_LLM_MESSAGES or MAX_LLM_CHARS",
                    group_name,
                    summary.used_count,
                    len(collapsed_messages),
                    summary.used_chars,
                )

            return _result(
                status,
                group_name=group_name,
                group_id=group_id,
                summary=summary.text,
                message_count=len(all_messages),
                api_duration=summary.api_duration,
                report_path=report_path,
                error=outcome.error if outcome.incomplete else None,
                incomplete=outcome.incomplete,
                acknowledged=acknowledged,
                acknowledged_max_id=predicted_ack if acknowledged else None,
                remaining_unread=remaining,
                truncated=summary.truncated,
                model=summary.model,
                collapsed_block_count=len(collapsed_messages),
                llm_message_count=summary.used_count,
                llm_char_count=summary.used_chars,
            )

        except Exception as exc:
            logger.error("Pipeline error: %s", exc, exc_info=True)
            return _result(
                "error",
                group_name=target_group,
                group_id=target_group,
                error=str(exc),
            )
