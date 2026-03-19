import re

def group_messages_by_id(messages: list[dict]) -> dict:
    """Groups a flat list of messages by group_id."""
    grouped = {}
    for msg in messages:
        gid = msg['group_id']
        gname = msg['group_name']
        
        if gid not in grouped:
            grouped[gid] = {
                "name": gname,
                "messages": []
            }
            
        # Strip group info from individual messages to save space
        clean_msg = {k: v for k, v in msg.items() if k not in ['group_id', 'group_name']}
        grouped[gid]["messages"].append(clean_msg)
    return grouped

def format_messages_to_markdown(grouped_messages: dict) -> str:
    """Formats grouped messages into the user's specific Markdown structure."""
    md_content = ""
    for gid, group_info in grouped_messages.items():
        gname = group_info["name"]
        md_content += f"# SOURCE: {gname} (ID: {gid})\n---\n"
        
        # Sort messages chronologically
        msgs = sorted(group_info["messages"], key=lambda x: x['date'])
        
        current_date = None
        for m in msgs:
            msg_date = m['date'][:10]
            msg_time = m['date'][11:]
            
            if msg_date != current_date:
                current_date = msg_date
                md_content += f"\n## DATE: {current_date}\n\n"
            
            reply_info = f" (reply to {m['reply_to_id']})" if m.get('reply_to_id') else ""
            md_content += f"**[[{msg_time}]] [ID:[{m['message_id']}]] [{m['sender_name']}]**{reply_info}: {m['text']}\n"
        
        md_content += "\n\n"
    return md_content

def clean_text_basic(text: str) -> str:
    """Collapses whitespace but KEEPS URLs."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()
