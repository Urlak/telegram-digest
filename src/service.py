import asyncio
import logging
import os
import re

from telethon import TelegramClient

from src.config import AppConfig
from src.telegram_client import fetch_target_messages, mark_target_messages_read
from src.processor import collapse_consecutive_messages
from src.summarizer import summarize_messages
from src.logic import format_messages_to_markdown
from src.reporter import build_report, finalize_report

logger = logging.getLogger(__name__)

_pipeline_lock = asyncio.Lock()

async def get_available_dialogs(client: TelegramClient, limit: int = 100) -> list[dict]:
    """
    Iterates dialogs and filters for groups/channels.
    Returns: [{"id": str, "name": str, "unread_count": int}, ...]
    """
    dialogs = []
    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.is_group or dialog.is_channel:
            dialogs.append({
                "id": str(dialog.id),
                "name": dialog.name or "Unknown",
                "unread_count": dialog.unread_count
            })
            
    # Sort unreads first, then by name
    dialogs.sort(key=lambda d: (d["unread_count"] == 0, str(d["name"]).lower()))
    return dialogs

def _export_messages(config: AppConfig, messages: list[dict], group_name: str, group_id: str) -> str:
    """Saves clean messages to a Markdown file in export-only mode."""
    data_dir = os.path.dirname(config.session_path)
    safe_name = re.sub(r'[^\w\s-]', '', group_name).strip().replace(' ', '_')
    filename = f"clean_messages_{safe_name}.md"
    md_path = os.path.join(data_dir, filename)
    
    md_content = format_messages_to_markdown(messages, group_name, group_id)
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
        
    logger.info(f"EXPORT_ONLY is ON. Saved '{group_name}' to {md_path}.")
    return md_path

async def execute_digest_pipeline(
    client: TelegramClient, 
    config: AppConfig, 
    target_group: str, 
    unread_only: bool = True, 
    hours_back: int | None = None, 
    limit_msgs: int | None = None, 
    export_only: bool = False,
    target_dialog=None
) -> dict:
    """
    Executes the digest pipeline for a target group.
    """
    effective_hours = hours_back if hours_back is not None else config.hours_back
    effective_limit = limit_msgs if limit_msgs is not None else config.message_limit
    
    # fetch_limit safety
    fetch_limit = min(effective_limit, config.max_fetch_limit)

    async with _pipeline_lock:
        try:
            force_fetch_fallback = not unread_only

            all_messages = await fetch_target_messages(
                client, 
                target_group, 
                limit_msgs=fetch_limit, 
                hours_back=effective_hours,
                force_fetch_fallback=force_fetch_fallback,
                dialog=target_dialog
            )

            if not all_messages:
                return {
                    "status": "no_messages",
                    "group_name": target_group,
                    "group_id": target_group,
                    "summary": "No matching messages found.",
                    "message_count": 0,
                    "api_duration": 0.0,
                    "report_path": None,
                    "error": None
                }

            group_name = all_messages[0]['group_name']
            group_id = all_messages[0]['group_id']

            collapsed_messages = collapse_consecutive_messages(all_messages)

            if export_only:
                report_path = _export_messages(config, collapsed_messages, group_name, group_id)
                if target_dialog is None:
                    await mark_target_messages_read(client, target_group)
                else:
                    await mark_target_messages_read(client, target_group, dialog=target_dialog)
                return {
                    "status": "success",
                    "group_name": group_name,
                    "group_id": group_id,
                    "summary": f"Messages exported to {os.path.basename(report_path)}",
                    "message_count": len(collapsed_messages),
                    "api_duration": 0.0,
                    "report_path": report_path,
                    "error": None
                }

            summary, api_duration = summarize_messages(
                collapsed_messages, 
                group_name,
                api_key=config.gemini_api_key, 
                max_messages=config.max_llm_messages
            )

            data_dir = os.path.dirname(config.session_path)
            safe_name = re.sub(r'[^\w\s-]', '', group_name).strip().replace(' ', '_')
            report_path = os.path.join(data_dir, f"digest_{safe_name}.md")

            report_output = build_report(summary, group_name)
            finalize_report(report_output, all_messages, effective_hours, api_duration, report_path)
            if target_dialog is None:
                await mark_target_messages_read(client, target_group)
            else:
                await mark_target_messages_read(client, target_group, dialog=target_dialog)

            return {
                "status": "success",
                "group_name": group_name,
                "group_id": group_id,
                "summary": summary,
                "message_count": len(all_messages),
                "api_duration": api_duration,
                "report_path": report_path,
                "error": None
            }

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return {
                "status": "error",
                "group_name": target_group,
                "group_id": target_group,
                "summary": "",
                "message_count": 0,
                "api_duration": 0.0,
                "report_path": None,
                "error": str(e)
            }
