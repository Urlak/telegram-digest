import logging
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient

logger = logging.getLogger(__name__)

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
            async for message in client.iter_messages(dialog.entity, limit=limit_msgs):
                # Only grab messages within our time horizon
                if message.date and message.date < time_threshold:
                    # We have gone back far enough in this chat's history, break the inner loop
                    break
                    
                if not message.text:
                    # Skip media-only messages without captions for simplicity
                    continue
                    
                # Extract sender info explicitly
                # Identify sender name (Channels vs Users)
                sender = await message.get_sender()
                sender_name = "Channel Content"
                if sender:
                    # For users, first_name is typical. For channels/chats, 'title' is used.
                    first = getattr(sender, 'first_name', '') or ''
                    last = getattr(sender, 'last_name', '') or ''
                    title = getattr(sender, 'title', '') or ''
                    sender_name = f"{first} {last}".strip() or title or "Unknown"
                    
                # Build and add our message payload
                results.append({
                    "message_id": message.id,
                    "group_id": str(dialog.id),
                    "group_name": group_name,
                    "sender_name": sender_name,
                    "date": message.date.strftime("%Y-%m-%d %H:%M"),
                    "text": message.text
                })
                
                messages_fetched += 1
                
            logger.info(f"Retrieved {messages_fetched} valid messages from '{group_name}'.")

    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        
    return results
