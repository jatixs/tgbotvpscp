# /opt/tg-bot/modules/logs.py
import asyncio
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

BUTTON_TEXT = "📜 Последние события"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(logs_handler)


async def logs_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "logs"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    try:
        cmd = "journalctl -n 20 --no-pager -o short-precise"
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(stderr.decode())
        log_output = escape_html(stdout.decode())
        sent_message = await message.answer(f"📜 <b>Последние системные журналы:</b>\n<pre>{log_output}</pre>", parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при чтении журналов: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журналов: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
