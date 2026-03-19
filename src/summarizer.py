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

        prompt = f"""
Проанализируй последние сообщения из чата '{group_name}'.
Твоя задача — составить краткий отчет для человека, который все пропустил.

Сгруппируй сообщения в 5-7 основных тем. Для каждой темы напиши один плотный абзац: суть обсуждения, ключевые аргументы, важные технические детали и итоговое решение (если оно есть). Упомяни активных участников обсуждения.

Игнорируй любой шум: приветствия, благодарности, флуд и неинформативные реплики. Пиши техническим, лаконичным языком, без вводных слов и лишних пояснений.

Важно: пиши строго на русском языке.

Сообщения для анализа:
"""
        # Format messages with IDs and reply context for Gemini
        message_lines = []
        for msg in messages:
            msg_id = msg.get("message_id", "???")
            reply_id = msg.get("reply_to_id")
            sender = msg.get("sender_name", "Unknown")
            text = msg.get("text", "")
            
            reply_info = f" (reply to {reply_id})" if reply_id else ""
            line = f"[{msg_id}] {sender}{reply_info}: {text}"
            message_lines.append(line)
            
        messages_text = "\n".join(message_lines)
        
        full_prompt = f"{prompt}\n{messages_text}"
            
        try:
            start_time = time.time()
            # Call Gemini using the new syntax and `gemini-2.5-flash`
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=full_prompt,
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
