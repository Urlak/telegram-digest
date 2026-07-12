import logging
import time
from google import genai

logger = logging.getLogger(__name__)

def summarize_messages(
    messages: list[dict],
    group_name: str,
    api_key: str, 
    max_messages: int
) -> tuple[str, float]:
    """
    Summarizes messages using Gemini AI.
    Returns a tuple: (Markdown summary string, total_api_duration_seconds).
    """
    if not messages:
        return "", 0.0

    # Initialize the new genai client
    client = genai.Client(api_key=api_key)
    
    # Truncate to most recent N messages for LLM safety
    raw_messages = messages
    messages = raw_messages[-max_messages:]
    is_truncated = len(raw_messages) > max_messages
    
    logger.info(f"Summarizing {len(messages)} messages for group: {group_name}" + 
                (f" [TRUNCATED from {len(raw_messages)}]" if is_truncated else ""))
    
    notice = ""
    if is_truncated:
        notice = f"*(Note: Only the latest {max_messages} messages were used for this summary)*\n\n"

    prompt = f"""
Проанализируй хронологический лог чата '{group_name}'. Составь краткий и информативный дайджест основных обсуждений. 
Сообщения содержат разметку ID `[Msg: ID]` и связей `(In reply to ID)`. Используй их, чтобы точно отслеживать цепочки ответов и не смешивать параллельные темы.

ТРЕБОВАНИЯ:
1. ДИНАМИЧЕСКИЕ ТЕМЫ: Выдели все самостоятельные обсуждения, сюжетные линии или инфоповоды. Игнорируй чистый флуд, мимолетные реплики, приветствия и смайлы, не несущие смысловой нагрузки. Не ограничивай количество тем искусственно.
2. ФОРМАТ: Жирный заголовок темы и один плотный, связный абзац (3–5 предложений). Никаких маркированных списков внутри абзаца. 
3. СТИЛЬ: Емкий, фактологический и объективный. Вместо механического перечисления фраз связывай их логически: что послужило триггером -> какие мнения/варианты высказывались -> к чему в итоге пришли (или на чем остановилось обсуждение).
4. МЕТАДАННЫЕ: В конце каждого абзаца в скобках укажи активных участников дискуссии и диапазон или ключевые ID сообщений.
5. ЯЗЫК: Строго русский. Выдавай только результат. Никаких вступлений, пояснений и мета-комментариев от ИИ.

СТРУКТУРА КАЖДОГО ТОПИКА:
**[Название темы / Предмет обсуждения]**
[Текст абзаца: суть разговора, ключевые факты, аргументы сторон, планы, новости или принятые решения]. ([Имена] | Msg: {{диапазон_или_ключевые_ID}})

Сообщения для анализа:
"""
    # Format messages with IDs and reply context for Gemini
    message_lines = []
    for msg in messages:
        msg_id = msg.get("message_id", "???")
        reply_id = msg.get("reply_to_id")
        sender = msg.get("sender_name", "Unknown")
        text = msg.get("text", "")
        
        if reply_id:
            line = f"[Msg: {msg_id}] {sender} (In reply to {reply_id}): {text}"
        else:
            line = f"[Msg: {msg_id}] {sender}: {text}"
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
        
        # Add a clear Markdown header pointing out which group this is for
        group_summary = f"### Summary for {group_name}\n\n{notice}{response.text.strip()}\n"
        return group_summary, duration
    except Exception as e:
        logger.error(f"Error calling Gemini API for group {group_name}: {e}")
        return f"### Summary for {group_name}\n\n*Error summarizing messages: {e}*\n", 0.0
