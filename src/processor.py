import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _sort_key(message: dict) -> tuple[float, int]:
    timestamp = message.get("timestamp")
    try:
        time_value = float(timestamp)
    except (TypeError, ValueError):
        time_value = 0.0
    try:
        id_value = int(message.get("message_id") or 0)
    except (TypeError, ValueError):
        id_value = 0
    return time_value, id_value


def _time_value(message: dict) -> float | None:
    timestamp = message.get("timestamp")
    if timestamp is not None:
        try:
            return float(timestamp)
        except (TypeError, ValueError):
            return None
    try:
        return datetime.strptime(message["date"], "%Y-%m-%d %H:%M").timestamp()
    except (KeyError, TypeError, ValueError):
        return None


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
    if not messages:
        return []

    sorted_msgs = sorted(messages, key=_sort_key)

    collapsed: list[dict] = []
    current: dict | None = None
    msg_id_mapping: dict[int, int] = {}

    for msg in sorted_msgs:
        msg_id = msg["message_id"]
        msg_id_mapping[msg_id] = msg_id

        if current is None:
            current = dict(msg)
            current["merged_ids"] = [msg_id]
            collapsed.append(current)
            continue

        current_time = _time_value(current)
        msg_time = _time_value(msg)
        if current_time is None or msg_time is None:
            time_gap = 999.0
        else:
            time_gap = (msg_time - current_time) / 60.0

        same_sender = current["sender_name"] == msg["sender_name"]
        within_time = time_gap <= max_gap_minutes
        same_thread = current.get("reply_to_id") == msg.get("reply_to_id")

        combined_text = f"{current.get('text', '')}\n\n{msg.get('text', '')}"
        within_size = (
            max_block_chars is None or len(combined_text) <= max_block_chars
        )

        if same_sender and within_time and same_thread and within_size:
            current["text"] = combined_text
            current["merged_ids"].append(msg_id)
            current["date"] = msg["date"]
            current["date_full"] = msg.get("date_full", current.get("date_full"))
            current["timestamp"] = msg.get("timestamp", current.get("timestamp"))
            msg_id_mapping[msg_id] = current["message_id"]
        else:
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
