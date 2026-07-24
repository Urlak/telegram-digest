import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient

from src.config import AppConfig
from src.service import get_available_dialogs, execute_digest_pipeline

logger = logging.getLogger(__name__)

def split_message(text: str, limit: int = 4000) -> list[str]:
    """Splits Markdown text into chunks beneath Telegram's character limit."""
    if len(text) <= limit:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
            
        # Try to break at a newline to avoid splitting Markdown formatting mid-line
        split_idx = text.rfind('\n', 0, limit)
        if split_idx == -1:
            split_idx = limit
            
        chunks.append(text[:split_idx])
        text = text[split_idx:].lstrip('\n')
        
    return chunks

def create_bot(config: AppConfig, telethon_client: TelegramClient) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=config.tg_bot_token)
    dp = Dispatcher()

    @dp.message(Command(commands=["start", "help", "groups", "digest"]))
    async def cmd_main(message: Message):
        user = message.from_user
        username = user.username or user.full_name
        logger.info(f"[REQUEST] User: @{username} (ID: {user.id}) | Command: {message.text}")
        
        dialogs = await get_available_dialogs(telethon_client)
        unread_dialogs = [d for d in dialogs if d.get("unread_count", 0) > 0]
        
        if not unread_dialogs:
            await message.answer("There are no unread messages in your groups.")
            return

        keyboard = []
        for dialog in unread_dialogs[:50]: # limit to 50 for inline keyboard safety
            btn_text = f"• {dialog['name']} ({dialog['unread_count']} unread)"
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"digest:{dialog['id']}")])
            
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer("Select a group with unread messages to summarize:", reply_markup=markup)

    @dp.callback_query(F.data.startswith("digest:"))
    async def process_digest_callback(query: CallbackQuery):
        await query.answer()
        
        group_id = query.data.split(":")[1]
        
        user = query.from_user
        username = user.username or user.full_name
        logger.info(f'[REQUEST] User: @{username} (ID: {user.id}) | Command: /digest | Target Group: (ID: {group_id})')
        
        await bot.edit_message_text(
            text="⏳ Summarizing group...",
            chat_id=query.message.chat.id,
            message_id=query.message.message_id
        )
        
        result = await execute_digest_pipeline(
            client=telethon_client,
            config=config,
            target_group=group_id,
            unread_only=True
        )
        
        if result["status"] == "success":
            chunks = split_message(result["summary"])
            
            await bot.edit_message_text(
                text=chunks[0],
                chat_id=query.message.chat.id,
                message_id=query.message.message_id
            )
            
            for chunk in chunks[1:]:
                await bot.send_message(
                    chat_id=query.message.chat.id,
                    text=chunk
                )
        elif result["status"] == "no_messages":
            await bot.edit_message_text(
                text="No matching messages found to summarize.",
                chat_id=query.message.chat.id,
                message_id=query.message.message_id
            )
        else:
            await bot.edit_message_text(
                text=f"Error during summarization: {result.get('error', 'Unknown error')}",
                chat_id=query.message.chat.id,
                message_id=query.message.message_id
            )

    return bot, dp
