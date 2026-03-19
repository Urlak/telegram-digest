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


async def get_client(session_name: str, api_id: int, api_hash: str, phone: str = None) -> TelegramClient:
    """Initializes and returns the Telethon TelegramClient."""
    logger.info(f"Connecting to Telegram with session file: {session_name}.session")
    client = TelegramClient(session_name, api_id, api_hash)
    
    # Automatically handles console input for auth code if needed
    if phone:
        await client.start(phone=phone)
    else:
        await client.start()
        
    return client

async def print_available_groups(client: TelegramClient, limit: int = 50):
    """
    Lists the names and IDs of available dialogs so the user can configure TARGET_GROUPS.
    """
    logger.info("TARGET_GROUPS not set. Listing available groups...")
    print("\n" + "="*60)
    print("AVAILABLE TELEGRAM GROUPS/CHATS (Top 50)")
    print("="*60)
    print(f"{'ID':<20} | {'NAME'}")
    print("-" * 60)
    
    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.is_group or dialog.is_channel:
            name = dialog.name or "Unknown"
            print(f"{dialog.id:<20} | {name}")
            
    print("\nTo summarize these, add their ID or exact name to TARGET_GROUPS in your .env file.")
    print("Example: TARGET_GROUPS=-10012345, -10098765, My Awesome Group\n")

async def fetch_target_messages(client: TelegramClient, target_groups: list[str], limit_msgs: int = 100, hours_back: int = 24):
    """
    Fetches messages from explicit target groups within the specified time limit.
    Returns a list of dictionaries with message data.
    """
    logger.info(f"Fetching max {limit_msgs} msgs from past {hours_back} hours.")
    results = []
    
    # Calculate timezone-aware UTC cutoff for the requested duration
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    
    try:
        # Iterate over all dialogs to find the target ones
        async for dialog in client.iter_dialogs():
            
            # Check if this dialog matches our target groups either by ID or Exact Name
            is_target = False
            for target in target_groups:
                target = target.strip()
                if not target: continue
                
                # Match by string name or integer ID
                if dialog.name == target or str(dialog.id) == target:
                    is_target = True
                    break
                    
            if not is_target:
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
                    
                # Clean and filter: skip photo-only (no text) and URL/noise-only messages
                raw_text = message.text or ''
                cleaned = _clean_text(raw_text)
                if len(cleaned) < MIN_TEXT_LEN:
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


    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        
    return results
