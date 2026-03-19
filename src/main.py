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
    new_messages = []
    for msg in all_messages:
        if not is_message_processed(DB_PATH, msg["message_id"], msg["group_id"], msg["group_name"]):
            new_messages.append(msg)
            
    # 6. Group Messages by Group ID for Summarization (Removes redundancy)
    # New structure: { group_id: { "name": "...", "messages": [...] } }
    grouped_messages = {}
    for msg in all_messages:
        gid = msg['group_id']
        gname = msg['group_name']
        
        if gid not in grouped_messages:
            grouped_messages[gid] = {
                "name": gname,
                "messages": []
            }
            
        # Strip redundant group info from the message object itself
        clean_msg = {k: v for k, v in msg.items() if k not in ['group_id', 'group_name']}
        grouped_messages[gid]["messages"].append(clean_msg)
        
    logger.info(f"Messages grouped into {len(grouped_messages)} unique groups.")
    
    # 6.5 Special Debug Mode: Save clean messages to Markdown (.md) and exit
    from src.config import EXPORT_ONLY
    if EXPORT_ONLY:
        MD_PATH = os.path.join(DATA_DIR, 'clean_messages.md')
        md_content = ""
        
        for gid, group_info in grouped_messages.items():
            gname = group_info["name"]
            md_content += f"# SOURCE: {gname} (ID: {gid})\n---\n"
            
            # Sort messages chronologically by the full date string
            msgs = sorted(group_info["messages"], key=lambda x: x['date'])
            
            current_date = None
            for m in msgs:
                msg_date = m['date'][:10] # YYYY-MM-DD
                msg_time = m['date'][11:] # HH:MM
                
                if msg_date != current_date:
                    current_date = msg_date
                    md_content += f"\n## DATE: {current_date}\n\n"
                
                reply_info = f" (reply to {m['reply_to_id']})" if m.get('reply_to_id') else ""
                md_content += f"**[[{msg_time}]] [ID:[{m['message_id']}]] [{m['sender_name']}]**{reply_info}: {m['text']}\n"
            
            md_content += "\n\n"
            
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
    
    # 8. Output Summaries to stdout
    print("\n" + "="*60)
    print("TELEGRAM DIGEST OUTPUT")
    print("="*60 + "\n")
    
    # Also prepare content for the text file
    digest_output = "TELEGRAM DIGEST OUTPUT\n" + "="*40 + "\n\n"
    
    from src.db import get_latest_digest
    
    # Track which groups we already printed to avoid duplicates if ID and Name both match
    printed_groups = set()
    
    # 8.1. New Content First
    for gid, group_info in grouped_messages.items():
        gname = group_info["name"]
        idx = list(grouped_messages.keys()).index(gid)
        print(new_summaries[idx])
        print("-" * 40)
        digest_output += new_summaries[idx] + "\n" + "-"*40 + "\n"
        printed_groups.add(gid)
        printed_groups.add(gname) # Keep name for backwards compatibility/matching
        
    # Then for any OTHER configured targets, try to pull from the cache
    for target in groups_list:
        if target in printed_groups: continue
        
        # Note: We attempt to find the cached version. If target is an ID, 
        # get_latest_digest will now handle the name lookup correctly via JOIN.
        cached_digest = get_latest_digest(DB_PATH, target)
        if cached_digest:
            print(f"[CACHED DIGEST - NO NEW MESSAGES]\n{cached_digest}")
            print("-" * 40)
            digest_output += f"[CACHED DIGEST - NO NEW MESSAGES]\n{cached_digest}\n" + "-"*40 + "\n"
            printed_groups.add(target)
            
    if not printed_groups:
        no_msg = "### Summary\n\n*No messages found and no previous digests exist.*\n"
        print(no_msg)
        print("-" * 40)
        digest_output += no_msg + "-"*40 + "\n"
        
    # 8.5 Add Metadata at the bottom for context
    if all_messages:
        dates = [m['date'] for m in all_messages]
        first_msg = min(dates)
        last_msg = max(dates)
        time_range = f"{first_msg} to {last_msg}"
    else:
        time_range = "N/A"

    metadata = f"\n[METADATA]\n- Time Range: {time_range}\n- Config Window: last {HOURS_BACK} hours\n- Total messages processed: {len(all_messages)}\n- API Processing Time: {api_duration:.2f}s\n"
    print(metadata)
    digest_output += metadata
        
    # Save the accumulated output to file (override)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(digest_output)
    logger.info(f"Latest digest saved to {OUTPUT_FILE}")
        
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
