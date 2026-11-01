import argparse
import asyncio
import logging
import os
import sys

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from telethon import TelegramClient
from telethon.tl.custom.dialog import Dialog

from src.config import AppConfig, ConfigError, load_config, setup_logging, validate_config
from src.processor import collapse_consecutive_messages
from src.reporter import build_report, finalize_report
from src.service import _export_messages, execute_digest_pipeline
from src.summarizer import summarize_messages
from src.telegram_client import (
    fetch_target_messages_with_stats,
    get_client,
    mark_target_messages_read,
)

logger = logging.getLogger(__name__)


async def _init_client(config: AppConfig) -> TelegramClient | None:
    """Initializes Telethon Telegram client using the configured session path."""
    os.makedirs(os.path.dirname(config.session_path), exist_ok=True)
    try:
        return await get_client(
            config.session_path,
            config.tg_api_id,
            config.tg_api_hash,
            config.tg_phone_number,
        )
    except Exception as exc:
        logger.error("Failed to initialize Telegram client. Error: %s", exc)
        return None


async def _run_interactive_setup(
    client: TelegramClient, display_limit: int = 25
) -> tuple[str, bool, Dialog | None]:
    """Interactive CLI menu to select a target group and fetch mode."""
    print("\n" + "=" * 50)
    print(" FETCHING RECENT GROUPS...")
    print("=" * 50)

    dialogs: list[Dialog] = []

    async for dialog in client.iter_dialogs(limit=100):
        if dialog.is_group or dialog.is_channel:
            dialogs.append(dialog)

    if not dialogs:
        print("No groups found.")
        sys.exit(0)

    dialogs.sort(key=lambda d: (d.unread_count == 0, str(d.name or "Unknown").lower()))
    dialogs = dialogs[:display_limit]

    for index, dialog in enumerate(dialogs, 1):
        name = dialog.name or "Unknown"
        indicator = "•" if dialog.unread_count > 0 else " "
        print(f"[{index:2}] {indicator} {name} (Unread: {dialog.unread_count})")

    print("-" * 50)

    selected_group = None
    selected_dialog = None
    while not selected_group:
        try:
            choice = input(f"Select a group [1-{len(dialogs)}]: ").strip()
            index = int(choice) - 1
            if 0 <= index < len(dialogs):
                selected_dialog = dialogs[index]
                selected_group = str(selected_dialog.id)
            else:
                print("Invalid number. Try again.")
        except ValueError:
            print("Please enter a valid number.")

    force_fetch_fallback = False
    while True:
        unread_choice = input("\nFetch unread messages ONLY? (y/n): ").strip().lower()
        if unread_choice in {"y", "yes"}:
            force_fetch_fallback = False
            break
        if unread_choice in {"n", "no"}:
            force_fetch_fallback = True
            break
        print("Please enter 'y' or 'n'.")

    return selected_group, force_fetch_fallback, selected_dialog


async def run_pipeline(config: AppConfig, is_auto_mode: bool) -> int:
    """Runs the CLI pipeline and returns a process exit code."""
    logger.info("Starting Telegram Digest Extraction...")

    client = await _init_client(config)
    if not client:
        return 1

    target_dialog = None
    try:
        if is_auto_mode:
            logger.info("Running in AUTO mode. Using .env configuration.")
            target_group = config.target_group
            force_fetch_fallback = True
            if not target_group:
                logger.error("TARGET_GROUP must be set in .env for --auto mode.")
                return 2
        else:
            logger.info("Running in INTERACTIVE mode.")
            target_group, force_fetch_fallback, target_dialog = (
                await _run_interactive_setup(client)
            )

        logger.info("Targeting group: %s", target_group)

        result = await execute_digest_pipeline(
            client=client,
            config=config,
            target_group=target_group,
            unread_only=not force_fetch_fallback,
            hours_back=config.hours_back,
            limit_msgs=config.message_limit,
            export_only=config.export_only,
            target_dialog=target_dialog,
            fetch_messages_fn=fetch_target_messages_with_stats,
            collapse_messages_fn=collapse_consecutive_messages,
            summarize_messages_fn=summarize_messages,
            export_messages_fn=_export_messages,
            build_report_fn=build_report,
            finalize_report_fn=finalize_report,
            mark_messages_read_fn=mark_target_messages_read,
        )

        status = result["status"]

        if status == "success":
            logger.info(
                "Success! %s messages processed. Acknowledged: %s. Remaining unread: %s.",
                result["message_count"],
                result.get("acknowledged", False),
                result.get("remaining_unread", 0),
            )
            if result["report_path"]:
                logger.info("Report saved to %s", result["report_path"])
            return 0

        if status == "no_messages":
            logger.info(
                "No messages to process. Acknowledged: %s. Remaining unread: %s.",
                result.get("acknowledged", False),
                result.get("remaining_unread", 0),
            )
            return 0

        if status == "incomplete":
            logger.error(
                "Pipeline finished with an incomplete load: %s. Nothing was acknowledged.",
                result.get("error"),
            )
            return 1

        logger.error("Pipeline error: %s", result.get("error"))
        return 1

    finally:
        try:
            disconnect = getattr(client, "disconnect", None)
            if disconnect is not None:
                result = disconnect()
                if hasattr(result, "__await__"):
                    await result
                logger.info("Telegram client disconnected.")
        except Exception as exc:
            logger.warning("Failed to disconnect Telegram client cleanly: %s", exc)


async def main() -> int:
    """CLI entrypoint parsing arguments and initiating execution."""
    parser = argparse.ArgumentParser(description="Telegram Group Summarizer")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run non-interactively using strictly .env properties",
    )
    args = parser.parse_args()

    setup_logging()

    try:
        config = load_config()
        validate_config(
            config,
            require_bot=False,
            require_gemini=not config.export_only,
        )
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    return await run_pipeline(config, is_auto_mode=args.auto)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
