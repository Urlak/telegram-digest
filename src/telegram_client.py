import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from src.contracts import FetchOutcome
from src.logic import clean_text_basic, format_duration, normalize_links
from src.timeutil import ensure_utc, format_local, format_local_full, resolve_timezone

logger = logging.getLogger(__name__)

MIN_TEXT_LEN = 2
MAX_LLM_TEXT_LEN = 8000
MAX_RAW_TEXT_LEN = 20000


def _media_marker(message) -> str | None:
    """Returns a compact marker for a media-only message, or ``None``."""
    if getattr(message, "photo", None):
        return "[Фото]"

    if getattr(message, "video", None) or getattr(message, "video_note", None):
        return "[Видео]"

    voice = getattr(message, "voice", None)
    if voice:
        return f"[Голосовое, {format_duration(getattr(voice, 'duration', 0))}]"

    audio = getattr(message, "audio", None)
    if audio:
        return f"[Аудио, {format_duration(getattr(audio, 'duration', 0))}]"

    if getattr(message, "sticker", None):
        return "[Стикер]"

    document = getattr(message, "document", None)
    if document:
        attributes = getattr(document, "attributes", []) or []
        if any(type(attr).__name__ == "DocumentAttributeAnimated" for attr in attributes):
            return "[GIF]"

        filename = None
        for attr in attributes:
            filename = getattr(attr, "file_name", None) or filename
        return f"[Документ: {filename}]" if filename else "[Документ]"

    if getattr(message, "poll", None):
        return "[Опрос]"
    if getattr(message, "contact", None):
        return "[Контакт]"
    if getattr(message, "geo", None):
        return "[Геолокация]"
    return None


def _sender_name(message) -> str:
    sender = getattr(message, "sender", None)

    if not sender and getattr(message, "sender_id", None) is not None:
        return f"User_{message.sender_id}"

    if sender:
        if getattr(sender, "bot", False):
            return getattr(sender, "username", None) or getattr(sender, "first_name", "") or "bot"
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        title = getattr(sender, "title", "") or ""
        return f"{first} {last}".strip() or title or "Unknown"

    return "Channel Content"


async def get_client(
    session_name: str, api_id: int, api_hash: str, phone: str | None = None
) -> TelegramClient:
    """Initializes and authenticates a Telethon ``TelegramClient`` instance."""
    logger.info(f"Connecting to Telegram with session file: {session_name}.session")
    client = TelegramClient(session_name, api_id, api_hash)

    if phone:
        await client.start(phone=phone)
    else:
        await client.start()

    return client


async def print_available_groups(client: TelegramClient, limit: int = 50) -> None:
    """Prints available group names and IDs to stdout for setup reference."""
    logger.info("TARGET_GROUP not set. Listing available groups...")
    print("\n" + "=" * 60)
    print("AVAILABLE TELEGRAM GROUPS/CHATS (Top 50)")
    print("=" * 60)
    print(f"{'ID':<20} | {'NAME'}")
    print("-" * 60)

    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.is_group or dialog.is_channel:
            name = dialog.name or "Unknown"
            print(f"{dialog.id:<20} | {name}")

    print("\nTo summarize one of these, add its ID or exact name to TARGET_GROUP in your .env file.")
    print("Example: TARGET_GROUP=-10012345\n")


async def _find_target_dialog(client: TelegramClient, target_group: str):
    """Searches user dialogs for a target matching exact title or Telegram ID."""
    async for dialog in client.iter_dialogs():
        if dialog.name == target_group or str(dialog.id) == target_group:
            return dialog
    return None


async def _parse_message(
    message,
    group_id: str,
    group_name: str,
    timezone_name: str | None = None,
) -> dict | None:
    """Parses a Telethon message into a clean dictionary payload.

    The returned dictionary contains two text variants:

    * ``text``     -- compact text for the LLM (links replaced by markers),
    * ``raw_text`` -- original text with full URLs, used by ``EXPORT_ONLY``.

    Media-only messages are kept with a human-readable marker such as
    ``[Фото]`` or ``[Голосовое, 0:42]``.  Bots and empty non-reply messages are
    still filtered out.
    """
    raw_text = message.text or ""
    caption = getattr(message, "caption", "") or ""
    if caption and caption not in raw_text:
        raw_text = f"{raw_text}\n{caption}".strip()

    media = _media_marker(message)
    cleaned = clean_text_basic(raw_text)

    is_reply = bool(message.reply_to and hasattr(message.reply_to, "reply_to_msg_id"))
    has_caption = bool(caption)

    if not cleaned and not media:
        logger.debug("[SKIP_EMPTY] msg_id=%s", message.id)
        return None

    if len(cleaned) < MIN_TEXT_LEN and not is_reply and not has_caption and not media:
        logger.debug(
            "[SKIP_LENGTH] msg_id=%s len=%s < MIN_TEXT_LEN",
            message.id,
            len(cleaned),
        )
        return None

    sender = getattr(message, "sender", None)
    if sender and getattr(sender, "bot", False):
        logger.debug(
            "[SKIP_BOT] msg_id=%s sender=%s",
            message.id,
            getattr(sender, "username", None) or getattr(sender, "first_name", "bot"),
        )
        return None

    sender_name = _sender_name(message)

    reply_to_id = None
    if message.reply_to and hasattr(message.reply_to, "reply_to_msg_id"):
        reply_to_id = message.reply_to.reply_to_msg_id

    message_date = getattr(message, "date", None) or datetime.now(timezone.utc)
    tz, tz_label = resolve_timezone(timezone_name)
    utc_date = ensure_utc(message_date)

    raw_clean = cleaned
    if len(raw_clean) > MAX_RAW_TEXT_LEN:
        raw_clean = raw_clean[:MAX_RAW_TEXT_LEN].rstrip() + "…"

    llm_text = normalize_links(raw_clean)
    if len(llm_text) > MAX_LLM_TEXT_LEN:
        llm_text = llm_text[:MAX_LLM_TEXT_LEN].rstrip() + "…"

    if media:
        raw_clean = f"{media}\n{raw_clean}".strip()
        llm_text = f"{media}\n{llm_text}".strip()

    return {
        "message_id": message.id,
        "reply_to_id": reply_to_id,
        "group_id": group_id,
        "group_name": group_name,
        "sender_name": sender_name,
        "date": format_local(utc_date, tz),
        "date_full": format_local_full(utc_date, tz),
        "date_utc": utc_date.isoformat(),
        "timestamp": utc_date.timestamp(),
        "timezone": tz_label,
        "media": media,
        "has_media": bool(media),
        "text": llm_text,
        "raw_text": raw_clean,
    }


async def mark_target_messages_read(
    client: TelegramClient,
    target_group: str,
    dialog=None,
    max_id: int | None = None,
    timeout_seconds: float = 30.0,
    retries: int = 2,
    max_flood_wait: int = 300,
) -> bool:
    """Acknowledges messages up to an explicit ``max_id``.

    Telegram read state is a high-water mark: acknowledging a newer message also
    marks every older message as read.  Therefore this function refuses to run
    without an explicit boundary, and the pipeline only passes an ID that
    belongs to a contiguous, fully processed/filtered prefix.
    """
    target_group = (target_group or "").strip()
    if not target_group:
        return False

    if max_id is None or int(max_id) <= 0:
        logger.warning("Refusing to acknowledge without an explicit max_id.")
        return False

    max_id = int(max_id)

    if dialog is None:
        dialog = await _find_target_dialog(client, target_group)
    if not dialog:
        logger.warning(f"Target group '{target_group}' not found for read acknowledgement.")
        return False

    last_error: Exception | None = None

    for attempt in range(max(0, retries) + 1):
        try:
            async with asyncio.timeout(timeout_seconds):
                acknowledged = await client.send_read_acknowledge(
                    dialog.entity, max_id=max_id
                )
            if acknowledged is False:
                logger.warning(
                    "Telegram did not confirm read receipt for '%s' up to max_id=%s.",
                    dialog.name or target_group,
                    max_id,
                )
                return False
            logger.info(
                "Acknowledged messages for '%s' up to max_id=%s.",
                dialog.name or target_group,
                max_id,
            )
            return True
        except FloodWaitError as exc:
            last_error = exc
            wait = min(int(getattr(exc, "seconds", 0) or 1) + 1, max_flood_wait)
            logger.warning(
                "Telegram FloodWait while acknowledging '%s': %ss.",
                dialog.name or target_group,
                wait,
            )
            if wait >= max_flood_wait or attempt >= retries:
                break
            await asyncio.sleep(wait)
        except (asyncio.TimeoutError, RPCError, OSError, ConnectionError) as exc:
            last_error = exc
            logger.warning(
                "Transient error while acknowledging '%s' (attempt %s/%s): %s",
                dialog.name or target_group,
                attempt + 1,
                retries + 1,
                exc,
            )
            if attempt >= retries:
                break
            await asyncio.sleep(min(2**attempt, 10))
        except Exception as exc:
            last_error = exc
            logger.exception("Unexpected error while acknowledging messages.")
            break

    logger.error(
        "Failed to acknowledge messages for '%s' up to max_id=%s: %s",
        target_group,
        max_id,
        last_error,
    )
    return False


async def _collect_once(
    client: TelegramClient,
    dialog,
    *,
    mode: str,
    fetch_limit: int,
    min_id: int,
    hours_back: int,
    timezone_name: str | None,
) -> tuple[list[dict], list[int], set[int], int, int, int]:
    results: list[dict] = []
    scanned_ids: list[int] = []
    parsed_ids: set[int] = set()
    scanned_count = 0
    age_skipped = 0
    filter_skipped = 0

    iter_kwargs: dict = {"limit": fetch_limit}
    if mode == "unread":
        iter_kwargs.update({"min_id": min_id, "reverse": True})

    time_threshold = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    async for message in client.iter_messages(dialog.entity, **iter_kwargs):
        message_date = getattr(message, "date", None)

        if mode == "fallback" and message_date is not None:
            try:
                if ensure_utc(message_date) < time_threshold:
                    age_skipped += 1
                    logger.debug(
                        "[SKIP_AGE] msg_id=%s older than %s hours",
                        message.id,
                        hours_back,
                    )
                    break
            except (TypeError, ValueError):
                pass

        scanned_count += 1
        scanned_ids.append(message.id)

        parsed = await _parse_message(
            message,
            str(dialog.id),
            dialog.name,
            timezone_name=timezone_name,
        )
        if parsed:
            results.append(parsed)
            parsed_ids.add(message.id)
        else:
            filter_skipped += 1

    if mode == "fallback":
        results.reverse()
        scanned_ids.reverse()

    return results, scanned_ids, parsed_ids, scanned_count, age_skipped, filter_skipped


async def fetch_target_messages_with_stats(
    client: TelegramClient,
    target_group: str,
    limit_msgs: int = 100,
    hours_back: int = 24,
    force_fetch_fallback: bool = False,
    dialog=None,
    timezone_name: str | None = None,
    timeout_seconds: float = 60.0,
    retries: int = 2,
    max_flood_wait: int = 300,
) -> FetchOutcome:
    """Fetches messages from a Telegram chat with an honest outcome object.

    In unread mode the *oldest* unread batch is fetched (``min_id`` from the
    dialog's read high-water mark, ascending order).  ``hours_back`` is applied
    only in fallback mode, so old unread messages are never silently stranded.

    On an exhausted retry budget the function returns an outcome with
    ``incomplete=True``.  The pipeline must not acknowledge anything in that
    case.
    """
    target_group = (target_group or "").strip()
    if not target_group:
        return FetchOutcome()

    if dialog is None:
        dialog = await _find_target_dialog(client, target_group)
    if not dialog:
        logger.warning(f"Target group '{target_group}' not found.")
        return FetchOutcome(error=f"Target group '{target_group}' not found.")

    group_name = dialog.name or target_group
    unread = int(getattr(dialog, "unread_count", 0) or 0)

    if unread > 0:
        mode = "unread"
        fetch_limit = min(unread, limit_msgs)
        raw_dialog = getattr(dialog, "dialog", None)
        read_inbox_max_id = int(getattr(raw_dialog, "read_inbox_max_id", 0) or 0)
        logger.info(
            '[%s] Unread mode: fetching oldest %s of %s unread messages '
            "(read high-water mark: %s).",
            group_name,
            fetch_limit,
            unread,
            read_inbox_max_id,
        )
    elif force_fetch_fallback:
        mode = "fallback"
        fetch_limit = limit_msgs
        read_inbox_max_id = 0
        logger.info(
            '[%s] Fallback mode: 0 unread. Fetching up to %s messages '
            "from the past %s hours.",
            group_name,
            fetch_limit,
            hours_back,
        )
    else:
        logger.info(
            '[%s] Auto mode: 0 unread. Skipping fetch (fallback disabled).',
            group_name,
        )
        return FetchOutcome(mode="none", unread_count=0, remaining_unread=0)

    if fetch_limit <= 0:
        return FetchOutcome(mode=mode, unread_count=unread, remaining_unread=unread)

    last_error: Exception | None = None

    for attempt in range(max(0, retries) + 1):
        try:
            async with asyncio.timeout(timeout_seconds):
                (
                    results,
                    scanned_ids,
                    parsed_ids,
                    scanned_count,
                    age_skipped,
                    filter_skipped,
                ) = await _collect_once(
                    client,
                    dialog,
                    mode=mode,
                    fetch_limit=fetch_limit,
                    min_id=read_inbox_max_id,
                    hours_back=hours_back,
                    timezone_name=timezone_name,
                )

            outcome = FetchOutcome(
                messages=results,
                mode=mode,
                scanned_count=scanned_count,
                age_skipped=age_skipped,
                filter_skipped=filter_skipped,
                unread_count=unread,
                remaining_unread=max(0, unread - len(scanned_ids))
                if mode == "unread"
                else 0,
                scanned_ids=scanned_ids,
                parsed_ids=parsed_ids,
                batch_max_id=max(scanned_ids) if scanned_ids else None,
                oldest_unread_id=min(scanned_ids) if scanned_ids else None,
            )

            logger.info(
                '[FETCH_SUMMARY] Group: "%s" | Mode: %s | Scanned: %s | '
                "Valid: %s | Skipped by Age: %s | Skipped by Filter: %s | "
                "Remaining unread: %s",
                group_name,
                mode,
                scanned_count,
                len(results),
                age_skipped,
                filter_skipped,
                outcome.remaining_unread,
            )
            return outcome

        except FloodWaitError as exc:
            last_error = exc
            wait = int(getattr(exc, "seconds", 0) or 1) + 1
            logger.warning(
                "[%s] Telegram FloodWait during fetch: %ss.", group_name, wait
            )
            if wait > max_flood_wait or attempt >= retries:
                break
            await asyncio.sleep(wait)
        except (asyncio.TimeoutError, RPCError, OSError, ConnectionError) as exc:
            last_error = exc
            logger.warning(
                "[%s] Transient fetch error (attempt %s/%s): %s",
                group_name,
                attempt + 1,
                retries + 1,
                exc,
            )
            if attempt >= retries:
                break
            await asyncio.sleep(min(2**attempt, 10))
        except Exception as exc:
            last_error = exc
            logger.exception("[%s] Unexpected fetch error.", group_name)
            break

    logger.error(
        "[%s] Fetch incomplete after %s attempt(s): %s",
        group_name,
        max(0, retries) + 1,
        last_error,
    )
    return FetchOutcome(
        mode=mode,
        unread_count=unread,
        remaining_unread=unread,
        incomplete=True,
        error=str(last_error) if last_error else "Message fetch failed.",
    )


async def fetch_target_messages(
    client: TelegramClient,
    target_group: str,
    limit_msgs: int = 100,
    hours_back: int = 24,
    force_fetch_fallback: bool = False,
    dialog=None,
    **kwargs,
) -> list[dict]:
    """Compatibility wrapper returning only the parsed message list."""
    outcome = await fetch_target_messages_with_stats(
        client,
        target_group,
        limit_msgs=limit_msgs,
        hours_back=hours_back,
        force_fetch_fallback=force_fetch_fallback,
        dialog=dialog,
        **kwargs,
    )
    return outcome.messages
