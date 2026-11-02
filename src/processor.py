import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _time_value(message: dict) -> float:
    timestamp = message.get("timestamp")
    if timestamp is not None:
        return float(timestamp)
    return datetime.strptime(message["date"], "%Y-%m-%d %H:%M").timestamp()


def collapse_consecutive_messages(
    messages: list[dict],
    max_gap_minutes: float = 5.0,
    max_block_chars: int | None = None,
) -> list[dict]:
    """Collapses consecutive messages from the same sender into blocks.

    Args:
        messages: Structured message dictionaries.
        max_gap_minutes: Maximum time gap for merging two messages.
        max_block_chars: Maximum combined text length of one block.  A new
            block is started instead of producing an unbounded prompt line.

    Notes:
        Messages from different reply targets are never merged.  Reply pointers
        are remapped to the primary block ID so thread links remain valid.
    """
    sorted_msgs = sorted(
        messages, key=lambda m: (_time_value(m), m.get("message_id", 0))
    )

    collapsed: list[dict] = []
    current: dict | None = None
    msg_id_mapping: dict[int, int] = {}

    for msg in sorted_msgs:
        msg_id = msg["message_id"]

        if current is not None:
            time_gap = (_time_value(msg) - _time_value(current)) / 60.0
            same_sender = current["sender_name"] == msg["sender_name"]
            within_time = time_gap <= max_gap_minutes
            same_thread = current.get("reply_to_id") == msg.get("reply_to_id")
            combined_text = f"{current['text']}\n\n{msg['text']}"
            within_size = (
                max_block_chars is None or len(combined_text) <= max_block_chars
            )

            if same_sender and within_time and same_thread and within_size:
                current["text"] = combined_text
                current["merged_ids"].append(msg_id)
                current["date"] = msg["date"]
                if "date_full" in msg:
                    current["date_full"] = msg["date_full"]
                if "timestamp" in msg:
                    current["timestamp"] = msg["timestamp"]
                msg_id_mapping[msg_id] = current["message_id"]
                continue

        current = dict(msg)
        current["merged_ids"] = [msg_id]
        collapsed.append(current)

    # Remap reply pointers to primary block IDs so thread links remain valid.
    for msg in collapsed:
        rep_id = msg.get("reply_to_id")
        if rep_id is not None:
            msg["reply_to_id"] = msg_id_mapping.get(rep_id, rep_id)

    logger.info(
        "Collapsed %s messages into %s conversational blocks.",
        len(messages),
        len(collapsed),
    )
    return collapsed
