import argparse
import asyncio
import logging
import os
import re
import sys

from telethon import TelegramClient
from telethon.tl.custom.dialog import Dialog

from src.config import setup_logging, load_config, AppConfig
from src.telegram_client import get_client, fetch_target_messages
from src.summarizer import summarize_messages
from src.logic import format_messages_to_markdown
from src.processor import collapse_consecutive_messages
from src.reporter import build_report, finalize_report

logger = logging.getLogger(__name__)

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

async def _run_interactive_setup(client: TelegramClient, display_limit: int = 15) -> tuple[str, bool]:
    """
    Interactive CLI to select a target group and determine unread fetching logic.
    Returns: (target_group_id_or_name, force_fetch_fallback)
    """
    print("\n" + "="*50)
    print(" FETCHING RECENT GROUPS...")
    print("="*50)
    
    dialogs: list[Dialog] = []
    
    # Fetch dialogs dynamically
    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            dialogs.append(dialog)
            if len(dialogs) >= display_limit:
                break

    if not dialogs:
        print("No groups found.")
        sys.exit(0)

    # Display numbered list
    for idx, dialog in enumerate(dialogs, 1):
        name = dialog.name or "Unknown"
        print(f"[{idx}] {name} (Unread: {dialog.unread_count})")

    print("-" * 50)
    
    # 1. Group Selection Loop
    selected_group = None
    while not selected_group:
        try:
            choice = input(f"Select a group [1-{len(dialogs)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(dialogs):
                selected_group = str(dialogs[idx].id)
            else:
                print("Invalid number. Try again.")
        except ValueError:
            print("Please enter a valid number.")

    # 2. Unread Logic Loop
    force_fetch_fallback = False
    while True:
        unread_choice = input("\nFetch unread messages ONLY? (y/n): ").strip().lower()
        if unread_choice in ['y', 'yes']:
            force_fetch_fallback = False  # Strictly unreads; skips if 0
            break
        elif unread_choice in ['n', 'no']:
            force_fetch_fallback = True   # Fall back to config limit if 0 unreads
            break
        else:
            print("Please enter 'y' or 'n'.")

    return selected_group, force_fetch_fallback

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

async def run_pipeline(config: AppConfig, is_auto_mode: bool) -> None:
    """Main orchestration logic for the Telegram Digest pipeline."""
    logger.info("Starting Telegram Digest Extraction...")
    
    client = await _init_client(config)
    if not client:
        return

    # Determine execution parameters based on mode
    if is_auto_mode:
        logger.info("Running in AUTO mode. Using .env configuration.")
        target_group = config.target_group
        force_fetch_fallback = True # Default behavior for automated runs
        if not target_group:
            logger.error("TARGET_GROUP must be set in .env for --auto mode.")
            return
    else:
        logger.info("Running in INTERACTIVE mode.")
        target_group, force_fetch_fallback = await _run_interactive_setup(client)

    fetch_limit = min(config.message_limit, config.max_fetch_limit)
    if fetch_limit < config.message_limit:
        logger.warning(f"MESSAGE_LIMIT {config.message_limit} exceeds safety cap. Using {config.max_fetch_limit} instead.")

    logger.info(f"Targeting group: {target_group}")
    
    # Fetch messages using the updated parameters
    all_messages = await fetch_target_messages(
        client, 
        target_group, 
        limit_msgs=fetch_limit, 
        hours_back=config.hours_back,
        force_fetch_fallback=force_fetch_fallback
    )
    
    logger.info(f"Fetched {len(all_messages)} messages matching constraints.")
    if not all_messages:
        logger.info("No messages to process.")
        return
    
    # Extract metadata
    group_name = all_messages[0]['group_name']
    group_id = all_messages[0]['group_id']
    
    collapsed_messages = collapse_consecutive_messages(all_messages)
    
    if config.export_only:
        _export_messages(config, collapsed_messages, group_name, group_id)
        return
    
    # Summarization
    summary, api_duration = summarize_messages(
        collapsed_messages, 
        group_name,
        api_key=config.gemini_api_key, 
        max_messages=config.max_llm_messages
    )
    
    # Reporting
    data_dir = os.path.dirname(config.session_path)
    safe_name = re.sub(r'[^\w\s-]', '', group_name).strip().replace(' ', '_')
    report_path = os.path.join(data_dir, f"digest_{safe_name}.md")
    
    report_output = build_report(summary, group_name)
    finalize_report(report_output, all_messages, config.hours_back, api_duration, report_path)
        
    logger.info("Script execution complete.")

async def main() -> None:
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Telegram Group Summarizer")
    parser.add_argument(
        "--auto", 
        action="store_true", 
        help="Run non-interactively using strictly .env properties"
    )
    args = parser.parse_args()

    setup_logging()
    config = load_config()
    
    await run_pipeline(config, is_auto_mode=args.auto)

if __name__ == "__main__":
    asyncio.run(main())