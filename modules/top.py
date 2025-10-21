# /opt/tg-bot/modules/top.py
import asyncio
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

BUTTON_TEXT = "🔥 Топ процессов"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(top_handler)


async def top_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "top"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)

    cmd = "ps aux --sort=-%cpu | head -n 11"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        output = escape_html(stdout.decode())
        response_text = f"🔥 <b>Топ 10 процессов по загрузке CPU:</b>\n<pre>{output}</pre>"
    else:
        error_output = escape_html(stderr.decode())
        response_text = f"❌ Ошибка при получении списка процессов:\n<pre>{error_output}</pre>"

    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
