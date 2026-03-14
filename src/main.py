import asyncio
import logging
import os
import sqlite3

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
        
    # 5. Filter for Only New Unprocessed Messages
    new_messages = []
    for msg in all_messages:
        if not is_message_processed(DB_PATH, msg["message_id"], msg["group_name"]):
            new_messages.append(msg)
            
    # 6. Group New Messages by Chat to keep Gemini contexts clean and isolated
    grouped_messages = {}
    for msg in new_messages:
        gname = msg["group_name"]
        if gname not in grouped_messages:
            grouped_messages[gname] = []
        grouped_messages[gname].append(msg)
        
    logger.info(f"Messages grouped into {len(grouped_messages)} unique groups with new content.")
        
    # 7. Summarize Messages
    new_summaries = summarize_messages(grouped_messages)
    
    # Save the newly generated summaries into the digest cache
    for gname, summary in zip(grouped_messages.keys(), new_summaries):
        from src.db import save_latest_digest
        save_latest_digest(DB_PATH, gname, summary)
    
    # 8. Output Summaries to stdout
    print("\n" + "="*60)
    print("TELEGRAM DIGEST OUTPUT")
    print("="*60 + "\n")
    
    # We need a list of actual group names to check the cache for.
    # If we fetched new messages, we know the names from `grouped_messages`.
    # If we didn't fetch new messages, we need to map the raw IDs to names.
    # For simplicity, we can just get the names from the DB digests table for the targeted groups.
    
    # We will iterate through target groups. If they have a new summary, print it.
    # If not, try to fetch the latest cached summary for whatever names they resolve to.
    from src.db import get_latest_digest
    
    # Track which groups we already printed to avoid duplicates if ID and Name both match
    printed_groups = set()
    
    for gname in grouped_messages.keys():
        idx = list(grouped_messages.keys()).index(gname)
        print(new_summaries[idx])
        print("-" * 40)
        printed_groups.add(gname)
        
    # For any configured targets we DID NOT get new messages for today, try fetching cache
    # Since config might be an ID (-100123) we attempt to fetch by config string directly, 
    # but we ALSO rely on the fact that if it was an ID, the previous run would have saved it 
    # under the resolved name. 
    for config_target in groups_list:
        # If we didn't print a new summary matching this configuration string
        if config_target not in printed_groups:
            # We try to find ANY cached digest that might match this target from our DB history
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            # If target was an ID, we might have saved it under the actual group name in the past.
            # We can just fetch all digests and print them if we didn't generate new ones.
            # Simplest approach for the user: iterate all cached digests and print.
            c.execute("SELECT group_name, digest_text FROM digests")
            rows = c.fetchall()
            conn.close()
            
            for row in rows:
                cached_gname, cached_text = row
                if cached_gname not in printed_groups:
                    print(f"[CACHED DIGEST - NO NEW MESSAGES]\n{cached_text}")
                    print("-" * 40)
                    printed_groups.add(cached_gname)
                    
            if not rows and not printed_groups:
                print(f"### Summary for {config_target}\n\n*No messages found and no previous digest exists.*\n")
                print("-" * 40)
                break # Only print this generic fallback once if nothing exists
        
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
