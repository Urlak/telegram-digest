import logging
from datetime import datetime
logger = logging.getLogger(__name__)

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def collapse_consecutive_messages(messages: list[dict], max_gap_minutes: float = 5.0) -> list[dict]:
    """Collapses consecutive messages from the same sender into combined block summaries.

    Args:
        messages: List of structured message dictionaries.
        max_gap_minutes: Maximum time difference threshold between messages to merge.

    Returns:
        List of collapsed message block dictionaries with updated reply mapping.

    Notes:
        Prevents merging across different thread reply targets to preserve context integrity.
        Remaps reply_to_id attributes of downstream messages to point to primary block IDs.
    """
    if not messages:
        return []
        
    sorted_msgs = sorted(messages, key=lambda x: x['date'])
    
    collapsed = []
    current = None
    msg_id_mapping = {}
    
    for msg in sorted_msgs:
        msg_id = msg["message_id"]
        msg_id_mapping[msg_id] = msg_id
        
        if current is None:
            current = dict(msg)
            current["merged_ids"] = [msg_id]
            collapsed.append(current)
            continue
            
        try:
            curr_time = datetime.strptime(current["date"], "%Y-%m-%d %H:%M")
            msg_time = datetime.strptime(msg["date"], "%Y-%m-%d %H:%M")
            time_gap = (msg_time - curr_time).total_seconds() / 60.0
        except Exception:
            time_gap = 999.0  # Fallback large gap on unparseable date formats
            
        same_sender = (current["sender_name"] == msg["sender_name"])
        within_time = (time_gap <= max_gap_minutes)
        same_thread = (current.get("reply_to_id") == msg.get("reply_to_id"))
        
        if same_sender and within_time and same_thread:
            current["text"] += "\n\n" + msg["text"]
            current["merged_ids"].append(msg_id)
            current["date"] = msg["date"]
            msg_id_mapping[msg_id] = current["message_id"]
        else:
            current = dict(msg)
            current["merged_ids"] = [msg_id]
            collapsed.append(current)
            
    # Remap reply pointers to primary block IDs so thread links remain valid
    for msg in collapsed:
        rep_id = msg.get("reply_to_id")
        if rep_id is not None:
            msg["reply_to_id"] = msg_id_mapping.get(rep_id, rep_id)
            
    logger.info(f"Collapsed {len(messages)} messages into {len(collapsed)} conversational blocks.")
    return collapsed
