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
    """Summarizes Telegram chat messages using Gemini AI.

    Args:
        messages: List of structured message dictionaries.
        group_name: Title of the Telegram group chat.
        api_key: Gemini API key authentication token.
        max_messages: Maximum recent messages to include to avoid token limits.

    Returns:
        Tuple of (Markdown formatted summary string, API call duration in seconds).

    Raises:
        RuntimeError: If LLM output is empty or blocked by safety filters.
        Exception: On upstream Gemini API network or server errors.

    Notes:
        Exceptions bubble up so the pipeline skips marking messages as read on failure.
    """
    if not messages:
        return "", 0.0

    client = genai.Client(api_key=api_key)
    
    # Enforce input ceiling to prevent context window overflow and rate limit spikes
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
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=full_prompt,
            config={
                'temperature': 0.3,
                'top_p': 0.95,
            }
        )
        duration = time.time() - start_time

        summary_text = _extract_response_text(response)
        if not summary_text:
            logger.warning(f"LLM generated empty response or was blocked for group: {group_name}")
            raise RuntimeError(f"Summary generation was blocked or returned no content for group {group_name}.")
        
        group_summary = f"### Summary for {group_name}\n\n{notice}{summary_text.strip()}\n"
        return group_summary, duration
    except Exception as e:
        logger.error(f"Error calling Gemini API for group {group_name}: {e}")
        raise


def _extract_response_text(response) -> str | None:
    """Safely extracts text from Gemini responses, supporting both direct text and candidate parts.

    Args:
        response: Response object returned by google.genai client.

    Returns:
        Extracted text string if present and non-empty, otherwise None.
    """
    direct_text = getattr(response, "text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    # Fallback to traversing candidate parts if response.text raises or is unpopulated
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None

    first_candidate = candidates[0]
    content = getattr(first_candidate, "content", None)
    parts = getattr(content, "parts", None) or []
    if not parts:
        return None

    texts = []
    for part in parts:
        part_text = getattr(part, "text", None)
        if isinstance(part_text, str) and part_text.strip():
            texts.append(part_text.strip())

    return "\n".join(texts).strip() if texts else None
