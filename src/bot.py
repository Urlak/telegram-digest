import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telethon import TelegramClient

from src.config import AppConfig
from src.service import execute_digest_pipeline, get_available_dialogs
from src.telegram_format import markdown_to_telegram_html, split_html, utf16_len

logger = logging.getLogger(__name__)


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Splits plain text into chunks below Telegram's UTF-16 limit."""
    if not text:
        return []

    chunks: list[str] = []
    rest = text

    while rest:
        if utf16_len(rest) <= limit:
            chunks.append(rest)
            break

        low, high = 1, len(rest)
        while low < high:
            mid = (low + high + 1) // 2
            if utf16_len(rest[:mid]) <= limit:
                low = mid
            else:
                high = mid - 1

        cut = max(low, 1)
        newline = rest.rfind("\n", 0, cut)
        if newline > cut // 2:
            cut = newline + 1

        chunk = rest[:cut]
        if not chunk:
            chunk = rest[:1]
        chunks.append(chunk)
        rest = rest[len(chunk) :].lstrip("\n")

    return [chunk for chunk in chunks if chunk]


def _status_notice(result: dict) -> str:
    parts: list[str] = []
    if result.get("incomplete"):
        parts.append(
            "⚠️ Загружена только часть сообщений. Прочитанным ничего не отмечено."
        )
    if result.get("remaining_unread", 0) > 0:
        parts.append(
            f"ℹ️ Обработана партия. Осталось непрочитанных: ~{result['remaining_unread']}. "
            "Запустите /start ещё раз, чтобы продолжить."
        )
    if result.get("truncated"):
        parts.append(
            "ℹ️ Часть сообщений не вошла в промпт из-за лимита объёма; "
            "подробности в метаданных отчёта."
        )
    return "\n".join(parts)


async def _send_digest(
    bot: Bot,
    chat_id: int,
    text: str,
    message_id: int | None = None,
) -> None:
    """Sends a Markdown digest as Telegram HTML, with a plain-text fallback."""
    html_text = markdown_to_telegram_html(text)
    chunks = split_html(html_text, limit=3500)
    if not chunks:
        chunks = [html_text]

    try:
        if message_id is not None:
            await bot.edit_message_text(
                text=chunks[0],
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_message(
                chat_id=chat_id, text=chunks[0], parse_mode=ParseMode.HTML
            )

        for chunk in chunks[1:]:
            await bot.send_message(
                chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML
            )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.warning("HTML digest delivery failed, falling back to plain text: %s", exc)
        plain_chunks = split_message(text, limit=3500)
        if not plain_chunks:
            return
        if message_id is not None:
            await bot.edit_message_text(
                text=plain_chunks[0], chat_id=chat_id, message_id=message_id
            )
        else:
            await bot.send_message(chat_id=chat_id, text=plain_chunks[0])
        for chunk in plain_chunks[1:]:
            await bot.send_message(chat_id=chat_id, text=chunk)


async def _edit_plain(
    bot: Bot, chat_id: int, message_id: int, text: str
) -> None:
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Failed to edit bot status message: %s", exc)


def create_bot(
    config: AppConfig, telethon_client: TelegramClient, owner_id: int
) -> tuple[Bot, Dispatcher]:
    """Factory creating and configuring the Telegram bot instance and handlers."""
    bot = Bot(token=config.tg_bot_token)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        user = message.from_user
        if user.id != owner_id:
            logger.warning("[SECURITY] Unauthorized message request from %s", user.id)
            return

        username = user.username or user.full_name
        logger.info(
            "[REQUEST] User: @%s (ID: %s) | Command: %s",
            username,
            user.id,
            message.text,
        )

        dialogs = await get_available_dialogs(telethon_client)
        unread_dialogs = [d for d in dialogs if d.get("unread_count", 0) > 0]

        if not unread_dialogs:
            await message.answer("There are no unread messages in your groups.")
            return

        keyboard = []
        for dialog in unread_dialogs[:50]:
            btn_text = f"• {dialog['name']} ({dialog['unread_count']} unread)"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=btn_text, callback_data=f"digest:{dialog['id']}"
                    )
                ]
            )

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer(
            "Select a group with unread messages to summarize:", reply_markup=markup
        )

    @dp.callback_query(F.data.startswith("digest:"))
    async def process_digest_callback(query: CallbackQuery):
        user = query.from_user
        if user.id != owner_id:
            logger.warning("[SECURITY] Unauthorized callback request from %s", user.id)
            return

        await query.answer()

        group_id = query.data.split(":", 1)[1]
        chat_id = query.message.chat.id
        status_message_id = query.message.message_id

        username = user.username or user.full_name
        logger.info(
            "[REQUEST] User: @%s (ID: %s) | Command: /digest | Target Group: (ID: %s)",
            username,
            user.id,
            group_id,
        )

        await _edit_plain(
            bot, chat_id, status_message_id, "⏳ Summarizing group..."
        )

        try:
            result = await execute_digest_pipeline(
                client=telethon_client,
                config=config,
                target_group=group_id,
                unread_only=True,
            )

            notice = _status_notice(result)

            if result["status"] in {"success", "incomplete"} and result.get("summary"):
                await _send_digest(
                    bot,
                    chat_id,
                    result["summary"],
                    message_id=status_message_id,
                )
                if notice:
                    await bot.send_message(chat_id=chat_id, text=notice)
            elif result["status"] == "no_messages":
                text = "No matching messages found to summarize."
                if result.get("acknowledged"):
                    text += " The filtered batch was marked as read."
                if notice:
                    text += f"\n\n{notice}"
                await _edit_plain(bot, chat_id, status_message_id, text)
            else:
                text = (
                    "Error during summarization: "
                    f"{result.get('error') or 'Unknown error'}"
                )
                if notice:
                    text += f"\n\n{notice}"
                await _edit_plain(bot, chat_id, status_message_id, text)
        except Exception as exc:
            logger.error("Error during bot digest processing: %s", exc, exc_info=True)
            await _edit_plain(
                bot, chat_id, status_message_id, f"Error during summarization: {exc}"
            )

    return bot, dp
