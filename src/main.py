import argparse
import asyncio
import logging
import os
import sys

from telethon import TelegramClient
from telethon.tl.custom.dialog import Dialog

from src.config import setup_logging, load_config, AppConfig
from src.telegram_client import get_client
from src.service import execute_digest_pipeline

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

async def _run_interactive_setup(client: TelegramClient, display_limit: int = 25) -> tuple[str, bool, Dialog | None]:
    """
    Interactive CLI to select a target group and determine unread fetching logic.
    Returns: (target_group_id_or_name, force_fetch_fallback, selected_dialog)
    """
    print("\n" + "="*50)
    print(" FETCHING RECENT GROUPS...")
    print("="*50)
    
    dialogs: list[Dialog] = []
    
    # Fetch a larger pool to ensure unread groups are captured before sorting
    async for dialog in client.iter_dialogs(limit=100):
        if dialog.is_group or dialog.is_channel:
            dialogs.append(dialog)

    if not dialogs:
        print("No groups found.")
        sys.exit(0)

    # Sort logic: Unreads first, then alphabetical
    dialogs.sort(key=lambda d: (d.unread_count == 0, str(d.name or "Unknown").lower()))
    
    # Apply the display limit AFTER sorting
    dialogs = dialogs[:display_limit]

    # Display numbered list
    for idx, dialog in enumerate(dialogs, 1):
        name = dialog.name or "Unknown"
        indicator = "•" if dialog.unread_count > 0 else " "
        print(f"[{idx:2}] {indicator} {name} (Unread: {dialog.unread_count})")

    print("-" * 50)
    
    selected_group = None
    selected_dialog = None
    while not selected_group:
        try:
            choice = input(f"Select a group [1-{len(dialogs)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(dialogs):
                selected_dialog = dialogs[idx]
                selected_group = str(selected_dialog.id)
            else:
                print("Invalid number. Try again.")
        except ValueError:
            print("Please enter a valid number.")

    force_fetch_fallback = False
    while True:
        unread_choice = input("\nFetch unread messages ONLY? (y/n): ").strip().lower()
        if unread_choice in ['y', 'yes']:
            force_fetch_fallback = False
            break
        elif unread_choice in ['n', 'no']:
            force_fetch_fallback = True
            break
        else:
            print("Please enter 'y' or 'n'.")

    return selected_group, force_fetch_fallback, selected_dialog

async def run_pipeline(config: AppConfig, is_auto_mode: bool) -> None:
    """Main orchestration logic for the Telegram Digest pipeline."""
    logger.info("Starting Telegram Digest Extraction...")
    
    client = await _init_client(config)
    if not client:
        return

    target_dialog = None
    try:
        if is_auto_mode:
            logger.info("Running in AUTO mode. Using .env configuration.")
            target_group = config.target_group
            force_fetch_fallback = True 
            if not target_group:
                logger.error("TARGET_GROUP must be set in .env for --auto mode.")
                return
        else:
            logger.info("Running in INTERACTIVE mode.")
            target_group, force_fetch_fallback, target_dialog = await _run_interactive_setup(client)

        logger.info(f"Targeting group: {target_group}")
        
        result = await execute_digest_pipeline(
            client=client,
            config=config,
            target_group=target_group,
            unread_only=not force_fetch_fallback,
            hours_back=config.hours_back,
            limit_msgs=config.message_limit,
            export_only=config.export_only,
            target_dialog=target_dialog
        )
        
        if result["status"] == "success":
            logger.info(f"Success! {result['message_count']} messages processed.")
            if result['report_path']:
                logger.info(f"Report saved to {result['report_path']}")
        elif result["status"] == "no_messages":
            logger.info("No messages to process.")
        else:
            logger.error(f"Pipeline error: {result['error']}")
            
        logger.info("Script execution complete.")
    finally:
        try:
            disconnect = getattr(client, "disconnect", None)
            if disconnect is None:
                return
            result = disconnect()
            if hasattr(result, "__await__"):
                await result
            logger.info("Telegram client disconnected.")
        except Exception as exc:
            logger.warning("Failed to disconnect Telegram client cleanly: %s", exc)

async def main() -> None:
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