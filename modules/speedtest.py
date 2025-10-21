# /opt/tg-bot/modules/speedtest.py
import asyncio
import json
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
BUTTON_KEY = "btn_speedtest"
# --------------------------------

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(speedtest_handler)
    # --------------------------------------

async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "speedtest" # Имя команды оставляем
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    # --- ИЗМЕНЕНО: Используем i18n ---
    sent_message = await message.answer(_("speedtest_start", lang))
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    cmd = "speedtest --accept-license --accept-gdpr --format=json"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()

    await delete_previous_message(user_id, command, chat_id, message.bot)

    if process.returncode == 0:
        output = stdout.decode('utf-8', errors='ignore')
        try:
            data = json.loads(output)
            download_speed = data.get("download", {}).get("bandwidth", 0) / 125000
            upload_speed = data.get("upload", {}).get("bandwidth", 0) / 125000
            ping_latency = data.get("ping", {}).get("latency", "N/A")
            server_name = data.get("server", {}).get("name", "N/A")
            server_location = data.get("server", {}).get("location", "N/A")
            result_url = data.get("result", {}).get("url", "N/A")

            # --- ИЗМЕНЕНО: Используем i18n ---
            response_text = _("speedtest_results", lang, 
                              dl=download_speed, 
                              ul=upload_speed, 
                              ping=ping_latency, 
                              server=escape_html(server_name), 
                              location=escape_html(server_location), 
                              url=escape_html(result_url))
            # --------------------------------
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка парсинга JSON от speedtest: {e}\nOutput: {output[:500]}")
            # --- ИЗМЕНЕНО: Используем i18n ---
            response_text = _("error_parsing_json", lang, output=escape_html(output[:1000]))
            # --------------------------------
        except Exception as e:
             logging.error(f"Неожиданная ошибка обработки speedtest: {e}")
             # --- ИЗМЕНЕНО: Используем i18n ---
             response_text = _("error_unexpected_json_parsing", lang, error=escape_html(str(e)))
             # --------------------------------
    else:
        error_output = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
        logging.error(f"Ошибка выполнения speedtest. Код: {process.returncode}. Вывод: {error_output}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        response_text = _("speedtest_fail", lang, error=escape_html(error_output))
        # --------------------------------

    sent_message_final = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id