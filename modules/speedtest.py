# /opt-tg-bot/modules/speedtest.py
import asyncio
import re
import logging
# import json # No longer needed for parsing
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

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

# Регулярное выражение для удаления ANSI-кодов (цветов)
ANSI_ESCAPE_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

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
    sent_message = await message.answer(_("speedtest_start", lang)) # Используем ключ speedtest_start
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    # [ИСПРАВЛЕНИЕ] Убираем -f json, но оставляем -4
    cmd = "npx speed-cloudflare-cli -4"

    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()

    # Удаляем сообщение "Запуск..."
    try:
        await message.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
        LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
    except Exception:
        pass

    if process.returncode == 0:
        output_raw = stdout.decode('utf-8', errors='ignore')
        # [ИСПРАВЛЕНИЕ] Очищаем вывод от ANSI-кодов (цветов)
        output = ANSI_ESCAPE_REGEX.sub('', output_raw)
        logging.debug(f"Speedtest (Cloudflare) cleaned text output:\n{output}")

        try:
            # --- [ИСПРАВЛЕНИЕ] Возвращаем парсинг ТЕКСТА ---
            download_speed = 0.0 # Используем float для единообразия
            upload_speed = 0.0
            latency = 0.0
            jitter = 0.0 # Jitter добавлен в i18n
            location = "N/A"
            colo = "N/A"

            # Используем re.M (MULTILINE) для поиска в начале строк
            down_match = re.search(r"^\s*Download speed:\s*([\d\.]+)", output, re.M)
            up_match = re.search(r"^\s*Upload speed:\s*([\d\.]+)", output, re.M)
            latency_match = re.search(r"^\s*Latency:\s*([\d\.]+)", output, re.M)
            jitter_match = re.search(r"^\s*Jitter:\s*([\d\.]+)", output, re.M)
            location_match = re.search(r"^\s*Server location:\s*([^\(]+)\s*\((\w+)\)", output, re.M) # Ищем Локацию (COLO)

            if down_match:
                download_speed = float(down_match.group(1))
            if up_match:
                upload_speed = float(up_match.group(1))
            if latency_match:
                latency = float(latency_match.group(1))
            if jitter_match:
                jitter = float(jitter_match.group(1))
            if location_match:
                location = location_match.group(1).strip()
                colo = location_match.group(2).strip()

            # Формируем текст ответа с использованием i18n
            response_text = _("speedtest_results", lang,
                              dl=download_speed, # Передаем как float
                              ul=upload_speed, # Передаем как float
                              ping=f"{latency:.2f}", # Форматируем ping
                              location=escape_html(location),
                              colo=escape_html(colo))
            # ------------------------------------

        # Убираем обработку json.JSONDecodeError
        except Exception as e:
            logging.error(f"Неожиданная ошибка обработки speedtest: {e}\nВывод: {output}")
            response_text = _("error_unexpected_json_parsing", lang, error=escape_html(str(e))) # Используем старый ключ ошибки парсинга
    else:
        error_output_raw = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
        error_output = ANSI_ESCAPE_REGEX.sub('', error_output_raw)

        logging.error(
            f"Ошибка выполнения speedtest. Код: {process.returncode}. Вывод: {error_output}")

        # Используем ключи i18n для ошибок
        if "command not found" in error_output.lower() or "not found" in error_output.lower() or "ENOENT" in error_output:
            response_text = _("error_npx", lang) # Используем ключ error_npx
        else:
            response_text = f"{_('speedtest_fail', lang, error=escape_html(error_output))}" # Используем speedtest_fail

    sent_message_final = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
    # Сохраняем ID *финального* сообщения
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id