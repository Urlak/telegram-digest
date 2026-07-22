import logging
import re
from src.logic import clean_text_basic
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'https?://\S+|www\.\S+|t\.me/\S+', re.IGNORECASE)

MIN_TEXT_LEN = 10
MAX_TEXT_LEN = 500

def _clean_text(text: str) -> str:
    """Uses centralized logic to collapse whitespace but KEEP URLs."""
    return clean_text_basic(text)

async def get_client(session_name: str, api_id: int, api_hash: str, phone: str | None = None) -> TelegramClient:
    """Initializes and returns the Telethon TelegramClient."""
    logger.info(f"Connecting to Telegram with session file: {session_name}.session")
    client = TelegramClient(session_name, api_id, api_hash)
    
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

async def _find_target_dialog(client: TelegramClient, target_group: str):
    """Iterates dialogs to find a match by exact name or ID string."""
    async for dialog in client.iter_dialogs():
        if dialog.name == target_group or str(dialog.id) == target_group:
            return dialog
    return None

async def _parse_message(message, group_id: str, group_name: str) -> dict | None:
    """
    Parses a single Telethon message, applying cleaning and validation filters.
    Returns the message dict if valid, or None if skipped/invalid.
    """
    raw_text = message.text or ''
    caption = getattr(message, 'caption', '') or ''
    if caption and caption not in raw_text:
        raw_text = f"{raw_text}\n{caption}".strip()
    
    cleaned = _clean_text(raw_text)
    if not cleaned:
        return None
        
    has_caption = bool(caption)
    is_reply = bool(message.reply_to and hasattr(message.reply_to, 'reply_to_msg_id'))
    
    if len(cleaned) < MIN_TEXT_LEN and not is_reply and not has_caption:
        return None
    
    if len(cleaned) > MAX_TEXT_LEN:
        cleaned = cleaned[:MAX_TEXT_LEN] + '…'
        
    sender = await message.get_sender()
    
    if sender and getattr(sender, 'bot', False):
        return None
        
    sender_name = "Channel Content"
    if sender:
        first = getattr(sender, 'first_name', '') or ''
        last = getattr(sender, 'last_name', '') or ''
        title = getattr(sender, 'title', '') or ''
        sender_name = f"{first} {last}".strip() or title or "Unknown"
        
    reply_to_id = None
    if message.reply_to and hasattr(message.reply_to, 'reply_to_msg_id'):
        reply_to_id = message.reply_to.reply_to_msg_id
        
    return {
        "message_id": message.id,
        "reply_to_id": reply_to_id,
        "group_id": group_id,
        "group_name": group_name,
        "sender_name": sender_name,
        "date": message.date.strftime("%Y-%m-%d %H:%M"),
        "text": cleaned
    }

async def mark_target_messages_read(client: TelegramClient, target_group: str) -> bool:
    """Marks the target dialog as read after successful processing."""
    target_group = target_group.strip()
    if not target_group:
        return False

    dialog = await _find_target_dialog(client, target_group)
    if not dialog:
        logger.warning(f"Target group '{target_group}' not found for read acknowledgement.")
        return False

    await client.send_read_acknowledge(dialog.entity)
    logger.info(f"Acknowledged messages for '{dialog.name or target_group}'.")
    return True


async def fetch_target_messages(
    client: TelegramClient, 
    target_group: str, 
    limit_msgs: int = 100, 
    hours_back: int = 24,
    force_fetch_fallback: bool = False
) -> list[dict]:
    """
    Fetches messages from the target group within the specified time limit.
    Returns a list of dictionaries with message data.
    """
    target_group = target_group.strip()
    if not target_group:
        return []

    dialog = await _find_target_dialog(client, target_group)
    if not dialog:
        logger.warning(f"Target group '{target_group}' not found.")
        return []
        
    group_name = dialog.name
    unread = dialog.unread_count
    
    # Evaluate execution mode dynamically before logging
    is_fetching_unread = False
    if unread > 0:
        fetch_limit = min(unread, limit_msgs)
        is_fetching_unread = True
        logger.info(f"[{group_name}] Unread mode: Fetching {fetch_limit} unread messages (Cap: {limit_msgs}).")
    elif force_fetch_fallback:
        fetch_limit = limit_msgs
        logger.info(f"[{group_name}] Fallback mode: 0 unreads. Fetching up to {limit_msgs} msgs from past {hours_back} hours.")
    else:
        logger.info(f"[{group_name}] Auto mode: 0 unreads. Skipping fetch (Fallback disabled).")
        return []
        
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    results = []
    messages_skipped = 0
    
    try:
        async for message in client.iter_messages(dialog.entity, limit=fetch_limit):
            # Enforce time threshold ONLY in fallback mode
            if not is_fetching_unread and message.date and message.date < time_threshold:
                break
                
            parsed = await _parse_message(message, str(dialog.id), group_name)
            if parsed:
                results.append(parsed)
            else:
                messages_skipped += 1
                
        logger.info(f"Retrieved {len(results)} valid messages from '{group_name}' (skipped {messages_skipped} photo/URL-only/bot).")
            
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        
    results.reverse()
    return results