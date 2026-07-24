import logging
import re
from src.logic import clean_text_basic
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'https?://\S+|www\.\S+|t\.me/\S+', re.IGNORECASE)

MIN_TEXT_LEN = 10
MAX_TEXT_LEN = 4000

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
        logger.info(f"[SKIP_EMPTY] msg_id={message.id}")
        return None
        
    has_caption = bool(caption)
    is_reply = bool(message.reply_to and hasattr(message.reply_to, 'reply_to_msg_id'))
    
    if len(cleaned) < MIN_TEXT_LEN and not is_reply and not has_caption:
        logger.info(f"[SKIP_LENGTH] msg_id={message.id} len={len(cleaned)} < MIN_TEXT_LEN")
        return None
    
    if len(cleaned) > MAX_TEXT_LEN:
        cleaned = cleaned[:MAX_TEXT_LEN] + '…'
        
    sender = getattr(message, 'sender', None)
    if not sender and hasattr(message, 'sender_id') and getattr(message, 'sender_id', None) is not None:
        sender_name = f"User_{message.sender_id}"
    else:
        sender_name = "Channel Content"

    if sender and getattr(sender, 'bot', False):
        sender_name = getattr(sender, 'username', None) or getattr(sender, 'first_name', '') or 'bot'
        logger.info(f"[SKIP_BOT] msg_id={message.id} sender={sender_name}")
        return None
    
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

async def mark_target_messages_read(client: TelegramClient, target_group: str, dialog=None) -> bool:
    """Marks the target dialog as read after successful processing."""
    target_group = target_group.strip()
    if not target_group:
        return False

    if dialog is None:
        dialog = await _find_target_dialog(client, target_group)
    if not dialog:
        logger.warning(f"Target group '{target_group}' not found for read acknowledgement.")
        return False

    await client.send_read_acknowledge(dialog.entity)
    logger.info(f"Acknowledged messages for '{dialog.name or target_group}'.")
    return True


async def fetch_target_messages_with_stats(
    client: TelegramClient, 
    target_group: str, 
    limit_msgs: int = 100, 
    hours_back: int = 24,
    force_fetch_fallback: bool = False,
    dialog=None,
) -> tuple[list[dict], dict]:
    """
    Fetches messages from the target group within the specified time limit.
    Returns a tuple of (message list, stats dict).
    """
    target_group = target_group.strip()
    if not target_group:
        return [], {"scanned_count": 0, "age_skipped": 0, "filter_skipped": 0}

    if dialog is None:
        dialog = await _find_target_dialog(client, target_group)
    if not dialog:
        logger.warning(f"Target group '{target_group}' not found.")
        return [], {"scanned_count": 0, "age_skipped": 0, "filter_skipped": 0}
        
    group_name = dialog.name
    unread = dialog.unread_count
    
    if unread > 0:
        fetch_limit = min(unread, limit_msgs)
        logger.info(f"[{group_name}] Unread mode: Fetching {fetch_limit} unread messages (Cap: {limit_msgs}).")
    elif force_fetch_fallback:
        fetch_limit = limit_msgs
        logger.info(f"[{group_name}] Fallback mode: 0 unreads. Fetching up to {limit_msgs} msgs from past {hours_back} hours.")
    else:
        logger.info(f"[{group_name}] Auto mode: 0 unreads. Skipping fetch (Fallback disabled).")
        return [], {"scanned_count": 0, "age_skipped": 0, "filter_skipped": 0}
        
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_text = time_threshold.strftime("%Y-%m-%d %H:%M:%S")
    results = []
    scanned_count = 0
    count_age = 0
    count_filter = 0
    
    try:
        async for message in client.iter_messages(dialog.entity, limit=fetch_limit):
            scanned_count += 1
            message_date = getattr(message, 'date', None)
            if message_date and message_date < time_threshold:
                count_age += 1
                logger.info(
                    "[SKIP_AGE] msg_id=%s date=%s is older than cutoff %s",
                    message.id,
                    message_date.strftime("%Y-%m-%d %H:%M:%S"),
                    cutoff_text,
                )
                break
                
            parsed = await _parse_message(message, str(dialog.id), group_name)
            if parsed:
                results.append(parsed)
            else:
                count_filter += 1
                
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        
    results.reverse()
    logger.info(
        '[FETCH_SUMMARY] Group: "%s" | Total Scanned: %s | Valid: %s | Skipped by Age: %s | Skipped by Filter: %s',
        group_name,
        scanned_count,
        len(results),
        count_age,
        count_filter,
    )
    return results, {"scanned_count": scanned_count, "age_skipped": count_age, "filter_skipped": count_filter}


async def fetch_target_messages(
    client: TelegramClient,
    target_group: str,
    limit_msgs: int = 100,
    hours_back: int = 24,
    force_fetch_fallback: bool = False,
    dialog=None,
) -> list[dict]:
    """Fetches messages from the target group within the specified time limit."""
    results, _ = await fetch_target_messages_with_stats(
        client,
        target_group,
        limit_msgs=limit_msgs,
        hours_back=hours_back,
        force_fetch_fallback=force_fetch_fallback,
        dialog=dialog,
    )
    return results