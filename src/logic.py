import re


def format_messages_to_markdown(messages: list[dict], group_name: str, group_id: str) -> str:
    """Formats structured Telegram messages into a human-readable Markdown log.

    Args:
        messages: List of structured message dictionaries.
        group_name: Human readable name of the Telegram group.
        group_id: Unique Telegram group identifier string.

    Returns:
        Formatted Markdown text string grouped by date headings.
    """
    md_content = f"# SOURCE: {group_name} (ID: {group_id})\n---\n"
    
    msgs = sorted(messages, key=lambda x: x['date'])
    
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
    """Normalizes message text whitespace while keeping embedded URLs intact.

    Args:
        text: Raw input text from Telegram message.

    Returns:
        Cleaned text string with collapsed whitespace and preserved paragraph breaks.

    Notes:
        Limits consecutive blank lines to one (\n\n) to preserve LLM paragraph comprehension.
    """
    if not text:
        return ""
    
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    lines = []
    for line in text.split('\n'):
        clean_line = re.sub(r'[^\S\r\n]+', ' ', line).strip()
        lines.append(clean_line)
        
    result_lines = []
    consecutive_empty = 0
    for line in lines:
        if line == '':
            consecutive_empty += 1
            if consecutive_empty <= 1:
                result_lines.append(line)
        else:
            consecutive_empty = 0
            result_lines.append(line)
            
    return '\n'.join(result_lines).strip()
