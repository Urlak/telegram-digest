import re

def format_messages_to_markdown(messages: list[dict], group_name: str, group_id: str) -> str:
    """Formats a list of messages into the user's specific Markdown structure."""
    md_content = f"# SOURCE: {group_name} (ID: {group_id})\n---\n"
    
    # Sort messages chronologically
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
    """
    Removes URLs (links) and collapses whitespace.
    Collapses horizontal spaces into a single space.
    Collapses consecutive newlines into a maximum of a double newline (\n\n) to preserve paragraphs.
    """
    if not text:
        return ""
    
    # Normalize line endings and remove URLs
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.compile(r'https?://\S+|www\.\S+|t\.me/\S+', re.IGNORECASE).sub('', text)
    
    # Collapse horizontal spaces on each line
    lines = []
    for line in text.split('\n'):
        clean_line = re.sub(r'[^\S\r\n]+', ' ', line).strip()
        lines.append(clean_line)
        
    # Collapse consecutive empty lines to a maximum of one empty line (results in \n\n)
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
