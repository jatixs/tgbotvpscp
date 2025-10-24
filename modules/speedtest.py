# /opt-tg-bot/modules/speedtest.py
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

# --- ИСПРАВЛЕНИЕ: Полная замена Ookla на Cloudflare ---
async def run_speedtest_command(cmd: str) -> str:
    """Вспомогательная функция для выполнения команды speedtest."""
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_output = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
        if not error_output:
            error_output = f"Command failed with code {process.returncode}"
        logging.error(f"Ошибка выполнения speedtest команды '{cmd}': {error_output}")
        raise Exception(error_output)
        
    return stdout.decode('utf-8', errors='ignore').strip()

async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "speedtest"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    # --- ИЗМЕНЕНО: Используем i18n (ключ 'speedtest_start' будет обновлен) ---
    sent_message = await message.answer(_("speedtest_start", lang))
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    try:
        # 1. Получаем метаданные (Пинг и Расположение)
        # Используем jq для парсинга, т.к. вывод curl может содержать заголовки
        meta_cmd = "curl -s --connect-timeout 5 https://speed.cloudflare.com/meta | jq -c '{ping: .clientTcpRtt, location: .clientCountry, colo: .colo}'"
        meta_output = await run_speedtest_command(meta_cmd)
        meta_data = json.loads(meta_output)
        
        ping_latency = meta_data.get("ping", "N/A")
        location = meta_data.get("location", "N/A")
        colo = meta_data.get("colo", "N/A")

        # 2. Тест скачивания (100MB)
        dl_cmd = "curl -s --connect-timeout 15 -w \"%{speed_download}\" https://speed.cloudflare.com/__down?bytes=100000000 -o /dev/null"
        dl_output = await run_speedtest_command(dl_cmd)
        # Вывод в Байтах/сек. Переводим в Мбит/с ( * 8 / 1000 / 1000 )
        download_speed = (float(dl_output) * 8) / 1_000_000

        # 3. Тест загрузки (25MB)
        ul_cmd = "curl -s --connect-timeout 15 -w \"%{speed_upload}\" -X POST --data-binary '@/dev/zero' 'https://speed.cloudflare.com/__up?bytes=25000000' -o /dev/null"
        ul_output = await run_speedtest_command(ul_cmd)
        # Вывод в Байтах/сек. Переводим в Мбит/с
        upload_speed = (float(ul_output) * 8) / 1_000_000

        # --- ИЗМЕНЕНО: Используем i18n (ключ 'speedtest_results' будет обновлен) ---
        response_text = _("speedtest_results", lang, 
                          dl=download_speed, 
                          ul=upload_speed, 
                          ping=ping_latency, 
                          location=escape_html(location), 
                          colo=escape_html(colo))
        # --------------------------------
        
    except json.JSONDecodeError as e:
        logging.error(f"Ошибка парсинга JSON от speedtest (Cloudflare meta): {e}\nOutput: {meta_output[:500]}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        response_text = _("error_parsing_json", lang, output=escape_html(meta_output[:1000]))
        # --------------------------------
    except Exception as e:
        error_output = str(e)
        if "command not found" in error_output.lower() and "jq" in error_output.lower():
             error_output = "Команда 'jq' не найдена. Пожалуйста, установите 'jq' на сервере (sudo apt install jq) или попросите администратора."
        
        logging.error(f"Ошибка выполнения speedtest (Cloudflare). Вывод: {error_output}")
        # --- ИЗМЕНЕНО: Используем i18n (ключ 'speedtest_fail' будет обновлен) ---
        response_text = _("speedtest_fail", lang, error=escape_html(error_output))
        # --------------------------------

    try:
        await message.bot.edit_message_text(
            response_text, 
            chat_id=chat_id, 
            message_id=sent_message.message_id, 
            parse_mode="HTML", 
            disable_web_page_preview=True
        )
    except Exception:
        # Если не удалось отредактировать (например, сообщение удалено), отправляем новое
        sent_message_final = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---