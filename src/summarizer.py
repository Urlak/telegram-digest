import logging
import time
from google import genai
from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

def summarize_messages(grouped_messages: dict) -> tuple[list[str], float]:
    """
    Summarizes messages using Gemini AI.
    grouped_messages structure: { gid: { "name": "...", "messages": [...] } }
    Returns a tuple: (list of Markdown summaries, total_api_duration_seconds).
    """
    if not grouped_messages:
        return [], 0.0

    # Initialize the new genai client
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    summaries = []
    total_duration = 0.0
    
    from src.config import MAX_LLM_MESSAGES
    
    for gid, group_info in grouped_messages.items():
        group_name = group_info["name"]
        raw_messages = group_info["messages"]
        
        # Truncate to most recent N messages for LLM safety
        messages = raw_messages[-MAX_LLM_MESSAGES:]
        is_truncated = len(raw_messages) > MAX_LLM_MESSAGES
        
        logger.info(f"Summarizing {len(messages)} messages for group: {group_name} ({gid})" + 
                    (f" [TRUNCATED from {len(raw_messages)}]" if is_truncated else ""))
        
        notice = ""
        if is_truncated:
            notice = f"*(Note: Only the latest {MAX_LLM_MESSAGES} messages were used for this summary)*\n\n"

        prompt = f"""Analyze Telegram messages from '{group_name}'.
Your task: Create a 'Skimmable Briefing' for a user who missed the discussion.

STRICT FORMATTING RULES:
1. **Top Headline**: Start with a single sentence (TL;DR) summarizing the overall mood and main event.
2. **Key Discussions (The "What")**: 3-5 bullet points. Group related messages. Do NOT list individual opinions; summarize the consensus or the main points of debate.
3. **Decisions & Tasks (The "Action")**: List only specific agreements, bot commands, or plans. Use names here.
4. **Resources & Tech**: Only links, specific numbers (prices, specs), or software mentions.

STYLE:
- Language: Russian.
- Tone: Extremely concise, "Executive Summary" style.
- No "filler" sentences (e.g., "In this chat, users talked about...").
- Use bold text only for keywords or names in 'Decisions'.

MESSAGES TO PROCESS:
"""
        for msg in reversed(messages):
            short_time = msg['date'][-5:]
            prompt += f"[{short_time}] {msg['sender_name']}: {msg['text']}\n"
            
        try:
            start_time = time.time()
            # Call Gemini using the new syntax and `gemini-2.5-flash`
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={
                    'temperature': 0.3,
                    'top_p': 0.95,
                }
            )
            duration = time.time() - start_time
            total_duration += duration
            
            # Add a clear Markdown header pointing out which group this is for
            group_summary = f"### Summary for {group_name}\n\n{notice}{response.text.strip()}\n"
            summaries.append(group_summary)
        except Exception as e:
            logger.error(f"Error calling Gemini API for group {group_name}: {e}")
            summaries.append(f"### Summary for {group_name}\n\n*Error summarizing messages: {e}*\n")
            
    return summaries, total_duration
