import asyncio
import logging
from aiogram import Dispatcher, types
from aiogram.types import KeyboardButton

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import format_uptime, get_host_path

BUTTON_KEY = "btn_uptime"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(uptime_handler)


async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "uptime"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)

    try:
        with open(get_host_path("/proc/uptime"), "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime_str = format_uptime(uptime_seconds, lang)
            response_text = _("uptime_text", lang, uptime=uptime_str)
    except Exception as e:
        logging.error(f"Uptime error: {e}")
        response_text = _("uptime_fail", lang, error=str(e))

    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
