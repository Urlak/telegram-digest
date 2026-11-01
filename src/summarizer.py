import logging
import re
import time
from datetime import datetime

from google import genai
from google.genai import types

from src.contracts import SummaryResult
from src.timeutil import now_with_offset, resolve_timezone

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"

# Safety net for models that ignore the "no IDs" instruction.  Matches
# trailing technical metadata such as "(Иван, Пётр | Msg: 3195-3220)".
_MSG_ID_SUFFIX_RE = re.compile(r"\s*\|\s*Msg:\s*[^)\n]*", re.IGNORECASE)
_MSG_ID_ONLY_RE = re.compile(r"\(\s*Msg:[^)\n]*\)", re.IGNORECASE)


def _strip_message_id_refs(text: str) -> str:
    """Removes technical ``| Msg: <ids>`` fragments from the generated digest."""
    if not text:
        return text
    cleaned = _MSG_ID_SUFFIX_RE.sub("", text)
    cleaned = _MSG_ID_ONLY_RE.sub("", cleaned)
    return "\n".join(line.rstrip() for line in cleaned.split("\n"))


def _block_text(block: dict, max_block_chars: int) -> str:
    text = block.get("text")
    if text is None:
        text = block.get("raw_text") or ""
    if max_block_chars and len(text) > max_block_chars:
        text = text[:max_block_chars].rstrip() + "…"
    return text


def _block_ids(block: dict) -> set[int]:
    merged = block.get("merged_ids") or []
    ids = {int(item) for item in merged if item is not None}
    if not ids and block.get("message_id") is not None:
        ids.add(int(block["message_id"]))
    return ids


def _format_id_ranges(ids: set[int] | list[int]) -> str:
    """Formats message IDs as compact ranges (``3195-3220, 3231``).

    The digest shown to the user must stay free of technical IDs; this helper
    keeps them available in DEBUG logs where they are actually useful.
    """
    values = sorted({int(item) for item in ids})
    if not values:
        return ""

    parts: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(f"{start}-{previous}" if start != previous else str(start))
        start = previous = value
    parts.append(f"{start}-{previous}" if start != previous else str(start))
    return ", ".join(parts)


def _format_block_line(block: dict, max_block_chars: int) -> str:
    message_id = block.get("message_id", "???")
    merged = block.get("merged_ids") or [message_id]
    id_label = ",".join(str(item) for item in merged)

    date_display = block.get("date_full") or block.get("date") or ""
    sender = block.get("sender_name") or "Unknown"
    reply_id = block.get("reply_to_id")
    reply_part = f" (In reply to {reply_id})" if reply_id else ""
    text = _block_text(block, max_block_chars)

    return f"[{date_display}] [Msg: {id_label}] {sender}{reply_part}: {text}"


def _select_blocks(
    blocks: list[dict],
    max_messages: int,
    max_chars: int,
    prefer_oldest: bool,
    max_block_chars: int,
) -> tuple[list[int], str, bool]:
    """Selects a contiguous block window within the prompt budget.

    Returns ``(selected_indices, messages_text, truncated)``.  At least one
    block is always included so a too-small budget cannot stall the pipeline.
    """
    lines = [_format_block_line(block, max_block_chars) for block in blocks]
    total = len(lines)

    selected: list[int] = []
    used_chars = 0

    order = range(total) if prefer_oldest else range(total - 1, -1, -1)
    for index in order:
        line = lines[index]
        additional = len(line) + (1 if selected else 0)
        if selected and (
            len(selected) >= max_messages or used_chars + additional > max_chars
        ):
            break
        selected.append(index)
        used_chars += additional

    if not prefer_oldest:
        selected.reverse()

    messages_text = "\n".join(lines[index] for index in selected)
    return selected, messages_text, len(selected) < total


def summarize_messages(
    messages: list[dict],
    group_name: str,
    api_key: str,
    max_messages: int,
    max_chars: int = 60000,
    max_block_chars: int = 4000,
    timezone_name: str | None = None,
    prefer_oldest: bool = False,
    timeout_seconds: float = 120.0,
    retries: int = 2,
    now: datetime | None = None,
) -> SummaryResult:
    """Summarizes Telegram chat messages using Gemini AI.

    Args:
        messages: Collapsed conversational blocks in chronological order.
        group_name: Title of the Telegram group chat.
        api_key: Gemini API key authentication token.
        max_messages: Maximum number of blocks to include.
        max_chars: Maximum total prompt characters.
        max_block_chars: Maximum characters taken from one block.
        timezone_name: IANA timezone used for timestamps in the prompt.
        prefer_oldest: Keep the oldest prefix (unread mode) instead of the
            newest suffix (fallback mode).
        timeout_seconds: Network timeout passed to the Gemini client.
        retries: Limited retries for transient 429/503-style failures.
        now: Injectable current datetime for tests.

    Returns:
        ``SummaryResult`` with the Markdown text and honest input statistics.

    Raises:
        RuntimeError: If the model returns no usable content.
        Exception: Upstream network/server errors after retries are exhausted.
    """
    if not messages:
        return SummaryResult(text="", api_duration=0.0, model=GEMINI_MODEL)

    tz, tz_label = resolve_timezone(timezone_name)
    current_time = now_with_offset(tz, now=now)

    selected_indices, messages_text, is_truncated = _select_blocks(
        messages,
        max_messages=max(1, max_messages),
        max_chars=max(1, max_chars),
        prefer_oldest=prefer_oldest,
        max_block_chars=max_block_chars,
    )

    used_ids: set[int] = set()
    for index in selected_indices:
        used_ids.update(_block_ids(messages[index]))

    logger.info(
        "Summarizing %s of %s blocks for group '%s' (%s chars)%s",
        len(selected_indices),
        len(messages),
        group_name,
        len(messages_text),
        " [TRUNCATED]" if is_truncated else "",
    )
    logger.info(
        "[LLM_INPUT_IDS] group='%s' ids=%s",
        group_name,
        _format_id_ranges(used_ids),
    )

    notice = ""
    if is_truncated:
        if prefer_oldest:
            notice = (
                f"*(Внимание: обработана только часть переписки — "
                f"{len(selected_indices)} из {len(messages)} блоков, начиная с самых старых. "
                f"Не вошло блоков: {len(messages) - len(selected_indices)}.)*\n\n"
            )
        else:
            notice = (
                f"*(Внимание: в дайджест вошли только последние "
                f"{len(selected_indices)} из {len(messages)} блоков. "
                f"Не вошло блоков: {len(messages) - len(selected_indices)}.)*\n\n"
            )

    system_instruction = f"""
Ты аналитик переписки. Дан хронологический лог чата «{group_name}».
Текущие дата и время: {current_time} ({tz_label}).

Формат строки лога:
[дата время UTC-смещение] [Msg: ID] Автор (In reply to ID): текст
ID и reply-связи нужны только для понимания цепочек ответов. Медиа заменены
маркерами [Фото], [Голосовое, 0:42], [Документ: file.pdf]; ссылки — маркерами
[YT], [TG], [GitHub], [Web: example.com].

ПРАВИЛА:
1. Начни с раздела «## Главное»: 3–5 пунктов с выводами, решениями и главными
   новостями. Не пересказывай темы — только суть.
2. Затем «## Темы»: каждое самостоятельное обсуждение — отдельная тема.
   Не объединяй разные обсуждения в одну тему. Короткое обсуждение — короткий
   абзац на 1–2 предложения.
3. Формат темы: заголовок третьего уровня без квадратных скобок, затем один
   связный абзац на 3–5 предложений: триггер, аргументы и варианты, к чему
   пришли. Не используй списки внутри абзаца.
4. В конце абзаца в скобках перечисли только имена активных участников.
   Не выводи ID сообщений, номера строк и технические ссылки.
5. Сохраняй имена, числа, даты, суммы, адреса и названия без искажений.
   Даты и время указывай, только если они важны для смысла. Соблюдай
   хронологию внутри темы.
6. Не выдумывай участников, цитаты, мнения и факты; не приписывай участникам
   того, чего нет в тексте. Если содержательных тем нет — прямо напиши об этом.
7. Если есть решения, поручения или следующие шаги, добавь раздел
   «## Решения и действия»; если остались нерешённые вопросы — раздел
   «## Открытые вопросы». Не создавай пустые разделы.

Отвечай только на русском, только Markdown, без вступлений и мета-комментариев.

СТРУКТУРА:
## Главное
- ...

## Темы
### Название темы
Плотный абзац по правилам выше.
(Имена)

## Решения и действия
- ...

## Открытые вопросы
- ...
""".strip()

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
    )

    last_error: Exception | None = None

    for attempt in range(max(0, retries) + 1):
        try:
            start_time = time.monotonic()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=messages_text,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.2,
                    "top_p": 0.95,
                },
            )
            duration = time.monotonic() - start_time

            summary_text = _extract_response_text(response)
            if not summary_text:
                logger.warning(
                    "LLM generated empty response or was blocked for group: %s",
                    group_name,
                )
                raise RuntimeError(
                    f"Summary generation was blocked or returned no content for group {group_name}."
                )

            summary_text = _strip_message_id_refs(summary_text).strip()
            if not summary_text:
                raise RuntimeError(
                    f"Summary for group {group_name} contained only technical IDs."
                )

            group_summary = (
                f"### Summary for {group_name}\n\n{notice}{summary_text.strip()}\n"
            )
            return SummaryResult(
                text=group_summary,
                api_duration=duration,
                model=GEMINI_MODEL,
                used_count=len(selected_indices),
                used_chars=len(messages_text),
                total_count=len(messages),
                truncated=is_truncated,
                used_message_ids=used_ids,
            )
        except Exception as exc:
            last_error = exc
            if attempt < retries and _is_transient_error(exc):
                delay = min(2**attempt, 10)
                logger.warning(
                    "Transient Gemini error for group %s (attempt %s/%s): %s. Retrying in %ss.",
                    group_name,
                    attempt + 1,
                    retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
                continue
            break

    logger.error(f"Error calling Gemini API for group {group_name}: {last_error}")
    assert last_error is not None
    raise last_error


def _is_transient_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "503",
            "rate limit",
            "resource_exhausted",
            "unavailable",
            "timeout",
            "temporarily",
            "overloaded",
        )
    )


def _extract_response_text(response) -> str | None:
    """Safely extracts text from Gemini responses, supporting candidate parts."""
    direct_text = getattr(response, "text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

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
