import logging
import re
from src.logic import clean_text_basic
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient

logger = logging.getLogger(__name__)

# Matches bare URLs: http(s)/t.me/www links
_URL_RE = re.compile(r'https?://\S+|www\.\S+|t\.me/\S+', re.IGNORECASE)

MIN_TEXT_LEN = 10  # characters after cleaning; below this the message is skipped
MAX_TEXT_LEN = 500  # characters sent to Gemini per message to cap token cost

def _clean_text(text: str) -> str:
    """Uses centralized logic to collapse whitespace but KEEP URLs."""
    return clean_text_basic(text)


async def get_client(session_name: str, api_id: int, api_hash: str, phone: str | None = None) -> TelegramClient:
    """Initializes and returns the Telethon TelegramClient."""
    logger.info(f"Connecting to Telegram with session file: {session_name}.session")
    client = TelegramClient(session_name, api_id, api_hash)
    
    # Automatically handles console input for auth code if needed
    if phone:
        await client.start(phone=phone)
    else:
        await client.start()
        
    return client

async def print_available_groups(client: TelegramClient, limit: int = 50) -> None:
    """
    Lists the names and IDs of available dialogs so the user can configure TARGET_GROUP.
    """
    logger.info("TARGET_GROUP not set. Listing available groups...")
    print("\n" + "="*60)
    print("AVAILABLE TELEGRAM GROUPS/CHATS (Top 50)")
    print("="*60)
    print(f"{'ID':<20} | {'NAME'}")
    print("-" * 60)
    
    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.is_group or dialog.is_channel:
            name = dialog.name or "Unknown"
            print(f"{dialog.id:<20} | {name}")
            
    print("\nTo summarize one of these, add its ID or exact name to TARGET_GROUP in your .env file.")
    print("Example: TARGET_GROUP=-10012345\n")

async def fetch_target_messages(
    client: TelegramClient, 
    target_group: str, 
    limit_msgs: int = 100, 
    hours_back: int = 24
) -> list[dict]:
    """
    Fetches messages from the target group within the specified time limit.
    Returns a list of dictionaries with message data.
    """
    logger.info(f"Fetching max {limit_msgs} msgs from past {hours_back} hours.")
    results = []
    
    # Calculate timezone-aware UTC cutoff for the requested duration
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    
    try:
        # Iterate over all dialogs to find the target ones
        async for dialog in client.iter_dialogs():
            
            target_group = target_group.strip()
            if not target_group: continue
            
            if dialog.name != target_group and str(dialog.id) != target_group:
                continue
                
            group_name = dialog.name
            logger.info(f"Found target group: {group_name}. Fetching messages...")
            
            # Fetch messages chronologically backwards
            messages_fetched = 0
            messages_skipped = 0
            async for message in client.iter_messages(dialog.entity, limit=limit_msgs):
                # Only grab messages within our time horizon
                if message.date and message.date < time_threshold:
                    break
                    
                # Merge message text and caption prior to cleaning
                raw_text = message.text or ''
                caption = getattr(message, 'caption', '') or ''
                if caption and caption not in raw_text:
                    raw_text = f"{raw_text}\n{caption}".strip()
                
                cleaned = _clean_text(raw_text)
                
                # Check for replies and captions for smart preservation
                has_caption = bool(caption)
                is_reply = bool(message.reply_to and hasattr(message.reply_to, 'reply_to_msg_id'))
                
                if not cleaned:
                    messages_skipped += 1
                    continue
                    
                # Skip messages shorter than MIN_TEXT_LEN only if not a reply and no caption
                if len(cleaned) < MIN_TEXT_LEN and not is_reply and not has_caption:
                    messages_skipped += 1
                    continue
                
                # Truncate long messages to cap token cost
                if len(cleaned) > MAX_TEXT_LEN:
                    cleaned = cleaned[:MAX_TEXT_LEN] + '…'
                    
                # Extract sender info explicitly
                sender = await message.get_sender()
                
                # Filter out bots
                if sender and getattr(sender, 'bot', False):
                    messages_skipped += 1
                    continue
                    
                sender_name = "Channel Content"
                if sender:
                    first = getattr(sender, 'first_name', '') or ''
                    last = getattr(sender, 'last_name', '') or ''
                    title = getattr(sender, 'title', '') or ''
                    sender_name = f"{first} {last}".strip() or title or "Unknown"
                    
                # Extract reply info if present
                reply_to_id = None
                if message.reply_to and hasattr(message.reply_to, 'reply_to_msg_id'):
                    reply_to_id = message.reply_to.reply_to_msg_id
                    
                results.append({
                    "message_id": message.id,
                    "reply_to_id": reply_to_id,
                    "group_id": str(dialog.id),
                    "group_name": group_name,
                    "sender_name": sender_name,
                    "date": message.date.strftime("%Y-%m-%d %H:%M"),
                    "text": cleaned
                })
                messages_fetched += 1
                
            logger.info(f"Retrieved {messages_fetched} valid messages from '{group_name}' (skipped {messages_skipped} photo/URL-only).")
            break # Stop after finding the single target group


    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        
    # Reverse the results to return them in chronological (oldest-first) order
    results.reverse()
    return results
