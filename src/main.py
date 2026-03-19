import asyncio
import logging
import os

from src.config import setup_logging
from src.config import TG_API_ID, TG_API_HASH, TG_PHONE_NUMBER
from src.config import TARGET_GROUPS, MESSAGE_LIMIT, HOURS_BACK
from src.db import init_db, mark_message_processed
from src.telegram_client import get_client, fetch_target_messages, print_available_groups
from src.summarizer import summarize_messages
from src.logic import group_messages_by_id, format_messages_to_markdown
from src.processor import filter_unprocessed_messages
from src.reporter import generate_report, save_and_print_metadata

logger = logging.getLogger(__name__)

# Standardize path routing for Docker Volume compatibility
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'digest.db')
SESSION_PATH = os.path.join(DATA_DIR, 'session')
OUTPUT_FILE = os.path.join(DATA_DIR, 'latest_digest.txt')

async def main():
    # 1. Initialize Logging
    setup_logging()
    logger.info("Starting Telegram Digest Extraction...")
    
    # 2. Ensure Data folder exists and start SQLite
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db(DB_PATH)
    
    # 3. Connect to Telegram
    try:
        # Require integers for api_id
        api_id = int(TG_API_ID) if TG_API_ID else 0
        client = await get_client(SESSION_PATH, api_id, TG_API_HASH, TG_PHONE_NUMBER)
    except Exception as e:
        logger.error(f"Failed to initialize Telegram client. Please check your .env variables. Error: {e}")
        return
        
    # 4. Fetch Telegram Messages constraints
    from src.config import MAX_FETCH_LIMIT
    fetch_limit = min(MESSAGE_LIMIT, MAX_FETCH_LIMIT)
    if fetch_limit < MESSAGE_LIMIT:
        logger.warning(f"MESSAGE_LIMIT {MESSAGE_LIMIT} exceeds safety cap. Using {MAX_FETCH_LIMIT} instead.")
        
    groups_list = TARGET_GROUPS
    if not groups_list:
        # If no groups configured, list all available groups so the user can easily configure them
        await print_available_groups(client)
        return
        
    logger.info(f"Targeting {len(groups_list)} group(s): {groups_list}")
    all_messages = await fetch_target_messages(client, groups_list, limit_msgs=fetch_limit, hours_back=HOURS_BACK)
    logger.info(f"Fetched {len(all_messages)} messages matching constraints.")
        
    # 5. Filter for Only New Unprocessed Messages
    new_messages = filter_unprocessed_messages(all_messages, DB_PATH)
            
    if not new_messages:
        logger.info("No new messages to process. Checking for cached digests...")
    
    # 6. Group Messages by Group ID for Summarization
    # We group ALL messages fetched to provide context, but summarizer should prioritize NEW ones?
    # Actually, the user's logic was to group all_messages.
    grouped_messages = group_messages_by_id(all_messages)
    logger.info(f"Messages grouped into {len(grouped_messages)} unique groups.")
    
    # 6.5 Special EXPORT_ONLY Mode: Save clean messages to Markdown (.md) and exit
    from src.config import EXPORT_ONLY
    if EXPORT_ONLY:
        MD_PATH = os.path.join(DATA_DIR, 'clean_messages.md')
        md_content = format_messages_to_markdown(grouped_messages)
        
        with open(MD_PATH, 'w', encoding='utf-8') as f:
            f.write(md_content)
            
        logger.info(f"EXPORT_ONLY is ON. Saved grouped messages to {MD_PATH}. Skipping summary.")
        print(f"\n[EXPORT MODE] Saved grouped messages to {MD_PATH}. Summarization skipped.\n")
        return
    
    # 7. Summarize Messages
    new_summaries, api_duration = summarize_messages(grouped_messages)
    
    # Save the newly generated summaries into the digest cache
    from src.db import save_latest_digest as save_digest
    for gid, summary in zip(grouped_messages.keys(), new_summaries):
        save_digest(DB_PATH, gid, grouped_messages[gid]["name"], summary)
    
    # 8. Output Summaries and Metadata (Reporter)
    digest_output = generate_report(new_summaries, grouped_messages, groups_list, DB_PATH)
    save_and_print_metadata(digest_output, all_messages, HOURS_BACK, api_duration, OUTPUT_FILE)
        
    # 9. Mark Messages as Processed and run basic maintenance
    for msg in new_messages:
        mark_message_processed(
            DB_PATH, 
            msg["message_id"], 
            msg["group_id"],
            msg["group_name"], 
            msg["sender_name"], 
            msg["date"]
        )
    
    # Cleanup old message IDs to keep DB small
    from src.db import cleanup_old_messages
    cleanup_old_messages(DB_PATH, days=30)
        
    logger.info("Script execution complete. Messages properly tracked.")


if __name__ == "__main__":
    # Needed to allow async event loops to run gracefully
    asyncio.run(main())
