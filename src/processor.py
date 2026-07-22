import logging
from datetime import datetime
logger = logging.getLogger(__name__)

def collapse_consecutive_messages(messages: list[dict], max_gap_minutes: float = 5.0) -> list[dict]:
    """
    Collapses consecutive messages from the same sender within a time window.
    Separates combined messages internally with a double newline (\\n\\n) to maintain readability.
    Exception: Do not merge messages if they contain different explicit reply_to_id contexts.
    Track merged message IDs and route any subsequent replies pointing to a merged block directly
    to the primary (first) message ID of that block to safeguard conversation graph integrity.
    """
    if not messages:
        return []
        
    # Ensure they are sorted chronologically (oldest-first)
    sorted_msgs = sorted(messages, key=lambda x: x['date'])
    
    collapsed = []
    current = None
    
    # Map original_message_id -> primary_message_id of the burst
    msg_id_mapping = {}
    
    for msg in sorted_msgs:
        msg_id = msg["message_id"]
        # By default, map every message to itself
        msg_id_mapping[msg_id] = msg_id
        
        if current is None:
            current = dict(msg)
            # Store list of message IDs that have been merged into this block
            current["merged_ids"] = [msg_id]
            collapsed.append(current)
            continue
            
        # Parse dates to calculate gap
        try:
            curr_time = datetime.strptime(current["date"], "%Y-%m-%d %H:%M")
            msg_time = datetime.strptime(msg["date"], "%Y-%m-%d %H:%M")
            time_gap = (msg_time - curr_time).total_seconds() / 60.0
        except Exception:
            time_gap = 999.0  # Fallback if date parsing fails
            
        # Check merge conditions:
        # 1. Same sender
        # 2. Time gap <= max_gap_minutes
        # 3. Same reply/thread context
        same_sender = (current["sender_name"] == msg["sender_name"])
        within_time = (time_gap <= max_gap_minutes)
        same_thread = (current.get("reply_to_id") == msg.get("reply_to_id"))
        
        if same_sender and within_time and same_thread:
            # Merge! Separate text with a double newline
            current["text"] += "\n\n" + msg["text"]
            current["merged_ids"].append(msg_id)
            current["date"] = msg["date"]
            # Map this message's ID to the primary message ID
            msg_id_mapping[msg_id] = current["message_id"]
        else:
            # Start a new block
            current = dict(msg)
            current["merged_ids"] = [msg_id]
            collapsed.append(current)
            
    # Rewrite the reply_to_id of the collapsed messages to point to the primary IDs of the bursts they reply to
    for msg in collapsed:
        rep_id = msg.get("reply_to_id")
        if rep_id is not None:
            msg["reply_to_id"] = msg_id_mapping.get(rep_id, rep_id)
            
    logger.info(f"Collapsed {len(messages)} messages into {len(collapsed)} conversational blocks.")
    return collapsed
