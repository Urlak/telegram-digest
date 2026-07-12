import asyncio
import logging
import os
import re

from src.config import setup_logging, load_config, AppConfig
from src.telegram_client import get_client, fetch_target_messages, print_available_groups
from src.summarizer import summarize_messages
from src.logic import format_messages_to_markdown
from src.processor import collapse_consecutive_messages
from src.reporter import build_report, finalize_report

logger = logging.getLogger(__name__)

# Paths and Globals are now managed by AppConfig via load_config()

async def _init_client(config: AppConfig) -> TelegramClient | None:
    """Initializes and connects the Telegram client."""
    os.makedirs(os.path.dirname(config.session_path), exist_ok=True)
    try:
        return await get_client(
            config.session_path, 
            config.tg_api_id, 
            config.tg_api_hash, 
            config.tg_phone_number
        )
    except Exception as e:
        logger.error(f"Failed to initialize Telegram client. Error: {e}")
        return None


def _export_messages(config: AppConfig, messages: list[dict], group_name: str, group_id: str) -> None:
    """Saves clean messages to a Markdown file in export-only mode."""
    data_dir = os.path.dirname(config.session_path)
    safe_name = re.sub(r'[^\w\s-]', '', group_name).strip().replace(' ', '_')
    filename = f"clean_messages_{safe_name}.md"
    md_path = os.path.join(data_dir, filename)
    
    md_content = format_messages_to_markdown(messages, group_name, group_id)
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
        
    logger.info(f"EXPORT_ONLY is ON. Saved '{group_name}' to {md_path}.")
    print(f"[EXPORT MODE] Saved messages from '{group_name}' to {filename}.")


async def run_pipeline(config: AppConfig) -> None:
    """
    Main orchestration logic for the Telegram Digest pipeline.
    """
    logger.info("Starting Telegram Digest Extraction...")
    
    client = await _init_client(config)
    if not client:
        return
        
    fetch_limit = min(config.message_limit, config.max_fetch_limit)
    if fetch_limit < config.message_limit:
        logger.warning(f"MESSAGE_LIMIT {config.message_limit} exceeds safety cap. Using {config.max_fetch_limit} instead.")
        
    target_group = config.target_group
    if not target_group:
        await print_available_groups(client)
        return
        
    logger.info(f"Targeting group: {target_group}")
    all_messages = await fetch_target_messages(
        client, 
        target_group, 
        limit_msgs=fetch_limit, 
        hours_back=config.hours_back
    )
    logger.info(f"Fetched {len(all_messages)} messages matching constraints.")
        
    if not all_messages:
        logger.info("No messages to process.")
        return
    
    # Extract real group name and ID from the first message
    group_name = all_messages[0]['group_name']
    group_id = all_messages[0]['group_id']
    
    # Collapse consecutive messages
    collapsed_messages = collapse_consecutive_messages(all_messages)
    
    # Special EXPORT_ONLY Mode
    if config.export_only:
        _export_messages(config, collapsed_messages, group_name, group_id)
        return
    
    # Summarize Messages
    summary, api_duration = summarize_messages(
        collapsed_messages, 
        group_name,
        api_key=config.gemini_api_key, 
        max_messages=config.max_llm_messages
    )
    
    # Output Summaries and Metadata (Reporter)
    data_dir = os.path.dirname(config.session_path)
    safe_name = re.sub(r'[^\w\s-]', '', group_name).strip().replace(' ', '_')
    report_filename = f"digest_{safe_name}.md"
    report_path = os.path.join(data_dir, report_filename)
    
    report_output = build_report(summary, group_name)
    finalize_report(
        report_output, 
        all_messages, 
        config.hours_back, 
        api_duration, 
        report_path
    )
        
    logger.info("Script execution complete.")

async def main() -> None:
    setup_logging()
    config = load_config()
    await run_pipeline(config)


if __name__ == "__main__":
    # Needed to allow async event loops to run gracefully
    asyncio.run(main())
