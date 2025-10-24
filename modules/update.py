# /opt/tg-bot/modules/update.py
import asyncio
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_update"
# --------------------------------


def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------


def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(update_handler)
    # --------------------------------------


async def update_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "update"  # Имя команды оставляем
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)

    # --- ИЗМЕНЕНО: Используем i18n ---
    sent_message = await message.answer(_("update_start", lang))
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    # Удаляем сообщение "Выполняю обновление..."
    # await delete_previous_message(user_id, command, chat_id, message.bot) #
    # Эта строка уже была выше, удаляем повтор
    try:
        await message.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
        LAST_MESSAGE_IDS.get(
            user_id, {}).pop(
            command, None)  # Удаляем из словаря
    except Exception:
        pass  # Игнорируем ошибки удаления

    if process.returncode == 0:
        # --- ИЗМЕНЕНО: Используем i18n ---
        response_text = _("update_success", lang,
                          output=escape_html(output[-4000:]))
        # --------------------------------
    else:
        # --- ИЗМЕНЕНО: Используем i18n ---
        response_text = _("update_fail",
                          lang,
                          code=process.returncode,
                          error=escape_html(error_output[-4000:]))
        # --------------------------------

    sent_message_final = await message.answer(response_text, parse_mode="HTML")
    # Сохраняем ID *финального* сообщения
    LAST_MESSAGE_IDS.setdefault(
        user_id, {})[command] = sent_message_final.message_id
