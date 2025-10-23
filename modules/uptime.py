# /opt/tg-bot/modules/uptime.py
import logging
import asyncio
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import format_uptime

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_uptime"
# --------------------------------

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(uptime_handler)
    # --------------------------------------

async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "uptime" # Имя команды оставляем
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    try:
        def read_uptime_file():
            with open("/proc/uptime") as f:
                return float(f.readline().split()[0])

        uptime_sec = await asyncio.to_thread(read_uptime_file)
        uptime_str = format_uptime(uptime_sec, lang) # ИСПРАВЛЕНО: Добавлен аргумент lang
        # --- ИЗМЕНЕНО: Используем i18n ---
        sent_message = await message.answer(
            _("uptime_text", lang, uptime=uptime_str), 
            parse_mode="HTML"
        )
        # --------------------------------
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
       logging.error(f"Ошибка в uptime_handler: {e}")
       # --- ИЗМЕНЕНО: Используем i18n ---
       sent_message = await message.answer(_("uptime_fail", lang, error=str(e)))
       # --------------------------------
       LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id