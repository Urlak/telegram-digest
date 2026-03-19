import logging
from src.db import is_message_processed

logger = logging.getLogger(__name__)

def filter_unprocessed_messages(all_messages: list[dict], db_path: str) -> list[dict]:
    """
    Filters out messages that have already been processed and stored in the database.
    Returns a list of messages that are new.
    """
    new_messages = []
    for msg in all_messages:
        # We need to pass the individual fields as required by is_message_processed
        if not is_message_processed(
            db_path, 
            msg["message_id"], 
            msg["group_id"], 
            msg["group_name"]
        ):
            new_messages.append(msg)
            
    logger.info(f"Filtered {len(all_messages)} total messages. Found {len(new_messages)} new messages.")
    return new_messages
