import asyncio
import logging
import os
import re

from src.config import setup_logging, load_config, AppConfig
from src.db import init_db, mark_message_processed, save_latest_digest, cleanup_old_messages
from src.telegram_client import get_client, fetch_target_messages, print_available_groups
from src.summarizer import summarize_messages
from src.logic import group_messages_by_id, format_messages_to_markdown
from src.processor import filter_unprocessed_messages
from src.reporter import build_report, finalize_report

logger = logging.getLogger(__name__)

# Paths and Globals are now managed by AppConfig via load_config()

async def run_pipeline(config: AppConfig) -> None:
    """
    Main orchestration logic for the Telegram Digest pipeline.
    """
    # 1. Initialize Logging (already done in main)
    logger.info("Starting Telegram Digest Extraction...")
    
    # 2. Ensure Data folder exists and start SQLite
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    init_db(config.db_path)
    
    # 3. Connect to Telegram
    try:
        client = await get_client(
            config.session_path, 
            config.tg_api_id, 
            config.tg_api_hash, 
            config.tg_phone_number
        )
    except Exception as e:
        logger.error(f"Failed to initialize Telegram client. Error: {e}")
        return
        
    fetch_limit = min(config.message_limit, config.max_fetch_limit)
    if fetch_limit < config.message_limit:
        logger.warning(f"MESSAGE_LIMIT {config.message_limit} exceeds safety cap. Using {config.max_fetch_limit} instead.")
        
    groups_list = config.target_groups
    if not groups_list:
        await print_available_groups(client)
        return
        
    logger.info(f"Targeting {len(groups_list)} group(s): {groups_list}")
    all_messages = await fetch_target_messages(
        client, 
        groups_list, 
        limit_msgs=fetch_limit, 
        hours_back=config.hours_back
    )
    logger.info(f"Fetched {len(all_messages)} messages matching constraints.")
        
    # 5. Filter for Only New Unprocessed Messages
    new_messages = filter_unprocessed_messages(all_messages, config.db_path)
            
    if not new_messages:
        logger.info("No new messages to process. Checking for cached digests...")
    
    # 6. Group Messages by Group ID for Summarization
    grouped_messages = group_messages_by_id(all_messages)
    logger.info(f"Messages grouped into {len(grouped_messages)} unique groups.")
    
    # 6.5 Special EXPORT_ONLY Mode: Save clean messages to Markdown (.md) and exit
    if config.export_only:
        data_dir = os.path.dirname(config.db_path)
        for gid, group_info in grouped_messages.items():
            gname = group_info["name"]
            safe_name = re.sub(r'[^\w\s-]', '', gname).strip().replace(' ', '_')
            filename = f"clean_messages_{safe_name}.md"
            md_path = os.path.join(data_dir, filename)
            
            md_content = format_messages_to_markdown({gid: group_info})
            
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
                
            logger.info(f"EXPORT_ONLY is ON. Saved '{gname}' to {md_path}.")
            print(f"[EXPORT MODE] Saved messages from '{gname}' to {filename}.")
        return
    
    # 7. Summarize Messages
    new_summaries, api_duration = summarize_messages(
        grouped_messages, 
        api_key=config.gemini_api_key, 
        max_messages=config.max_llm_messages
    )
    
    # Save the newly generated summaries into the digest cache
    for gid, summary in zip(grouped_messages.keys(), new_summaries):
        save_latest_digest(config.db_path, gid, grouped_messages[gid]["name"], summary)
    
    # 8. Output Summaries and Metadata (Reporter)
    data_dir = os.path.dirname(config.db_path)
    for gid, summary in zip(grouped_messages.keys(), new_summaries):
        gname = grouped_messages[gid]["name"]
        safe_name = re.sub(r'[^\w\s-]', '', gname).strip().replace(' ', '_')
        report_filename = f"digest_{safe_name}.md"
        report_path = os.path.join(data_dir, report_filename)
        
        # Prepare individual group content for the file (includes metadata)
        # We pass ONLY this group's messages to finalize_report for accurate metadata
        group_messages = [m for m in all_messages if m.get('group_id') == gid or m.get('group_name') == gname]
        
        finalize_report(
            summary, 
            group_messages, 
            config.hours_back, 
            api_duration / len(new_summaries), 
            report_path
        )
    
    # Still build a combined report for the console output if multiple groups
    if len(new_summaries) > 1:
        combined_output = build_report(new_summaries, grouped_messages, groups_list, config.db_path)
        print("\n" + "="*60)
        print("COMBINED TELEGRAM DIGEST (CONSOLE ONLY)")
        print(combined_output)
        print("="*60 + "\n")
        
    # 9. Mark Messages as Processed and run basic maintenance
    for msg in new_messages:
        mark_message_processed(
            config.db_path, 
            msg["message_id"], 
            msg["group_id"],
            msg["group_name"], 
            msg["sender_name"], 
            msg["date"]
        )
    
    # Cleanup old message IDs to keep DB small
    cleanup_old_messages(config.db_path, days=30)
        
    logger.info("Script execution complete. Messages properly tracked.")

async def main() -> None:
    setup_logging()
    config = load_config()
    await run_pipeline(config)


if __name__ == "__main__":
    # Needed to allow async event loops to run gracefully
    asyncio.run(main())
