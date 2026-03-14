import asyncio
import logging
import os

from src.config import setup_logging
from src.config import TG_API_ID, TG_API_HASH, TG_PHONE_NUMBER
from src.config import TARGET_GROUPS, MESSAGE_LIMIT, HOURS_BACK
from src.db import init_db, is_message_processed, mark_message_processed
from src.telegram_client import get_client, fetch_target_messages, print_available_groups
from src.summarizer import summarize_messages

logger = logging.getLogger(__name__)

# Standardize path routing for Docker Volume compatibility
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'digest.db')
SESSION_PATH = os.path.join(DATA_DIR, 'session')

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
    groups_list = [g.strip() for g in TARGET_GROUPS.split(",") if g.strip()]
    if not groups_list:
        # If no groups configured, list all available groups so the user can easily configure them
        await print_available_groups(client)
        return
        
    logger.info(f"Targeting {len(groups_list)} group(s): {groups_list}")
    all_messages = await fetch_target_messages(client, groups_list, limit_msgs=MESSAGE_LIMIT, hours_back=HOURS_BACK)
    logger.info(f"Fetched {len(all_messages)} messages matching constraints.")
        
    # 5. Filter for Only New Unprocessed Messages (Using our SQLite Tracker)
    new_messages = []
    for msg in all_messages:
        if not is_message_processed(DB_PATH, msg["message_id"], msg["group_name"]):
            new_messages.append(msg)
            
    if not new_messages:
        logger.info("No new, unprocessed messages to aggregate. Exiting.")
        return
        
    # 6. Group New Messages by Chat to keep Gemini contexts clean and isolated
    grouped_messages = {}
    for msg in new_messages:
        gname = msg["group_name"]
        if gname not in grouped_messages:
            grouped_messages[gname] = []
        grouped_messages[gname].append(msg)
        
    logger.info(f"Messages grouped into {len(grouped_messages)} unique groups.")
        
    # 7. Summarize Messages
    summaries = summarize_messages(grouped_messages)
    
    # 8. Output Summaries to stdout cleanly formatted with Markdown Checkmarks
    print("\n" + "="*60)
    print("TELEGRAM DIGEST OUTPUT")
    print("="*60 + "\n")
    for summary in summaries:
        print(summary)
        print("-" * 40)
        
    # 9. Mark Messages as Processed to prevent re-processing later
    for msg in new_messages:
        mark_message_processed(
            DB_PATH, 
            msg["message_id"], 
            msg["group_name"], 
            msg["sender_name"], 
            msg["date"]
        )
        
    logger.info("Script execution complete. Messages properly tracked.")

if __name__ == "__main__":
    # Needed to allow async event loops to run gracefully
    asyncio.run(main())
