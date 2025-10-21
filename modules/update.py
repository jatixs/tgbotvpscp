# /opt/tg-bot/modules/update.py
import asyncio
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

BUTTON_TEXT = "🔄 Обновление VPS/VDS"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(update_handler)

async def update_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "update"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    sent_message = await message.answer("🔄 Выполняю обновление VPS... Это может занять несколько минут.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    
    cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    await delete_previous_message(user_id, command, chat_id, message.bot)

    if process.returncode == 0:
        response_text = f"✅ Обновление завершено:\n<pre>{escape_html(output[-4000:])}</pre>"
    else:
        response_text = f"❌ Ошибка при обновлении (Код: {process.returncode}):\n<pre>{escape_html(error_output[-4000:])}</pre>"

    sent_message_final = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id