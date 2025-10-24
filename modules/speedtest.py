# /opt/tg-bot/modules/speedtest.py
import asyncio
import re  # <- ИМПОРТИРОВАНО
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

BUTTON_TEXT = "🚀 Скорость сети"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(speedtest_handler)


async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "speedtest"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)

    sent_message = await message.answer("🚀 Запуск speedtest (Cloudflare)... Это может занять до минуты.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    # --- [НАЧАЛО ИЗМЕНЕНИЙ] ---
    cmd = "npx speed-cloudflare-cli"
    # --- [КОНЕЦ ИЗМЕНЕНИЙ] ---
    
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()

    await delete_previous_message(user_id, command, chat_id, message.bot)

    if process.returncode == 0:
        output = stdout.decode('utf-8', errors='ignore')
        try:
            # --- [НАЧАЛО ИЗМЕНЕНИЙ ПАРСИНГА] ---
            download_speed = "N/A"
            upload_speed = "N/A"
            ip = "N/A"
            latency = "N/A"
            jitter = "N/A"

            # Ищем значения с помощью регулярных выражений
            down_match = re.search(r"Download speed:\s*([\d\.]+)", output)
            up_match = re.search(r"Upload speed:\s*([\d\.]+)", output)
            ip_match = re.search(r"Your IP:\s*([^\s\(]+)", output)
            latency_match = re.search(r"Latency:\s*([\d\.]+)", output)
            jitter_match = re.search(r"Jitter:\s*([\d\.]+)", output)

            if down_match:
                download_speed = down_match.group(1)
            if up_match:
                upload_speed = up_match.group(1)
            if ip_match:
                ip = ip_match.group(1)
            if latency_match:
                latency = latency_match.group(1)
            if jitter_match:
                jitter = jitter_match.group(1)

            response_text = (
                f"🚀 <b>Speedtest Результаты (Cloudflare):</b>\n\n"
                f"⬇️ <b>Скачивание / Download:</b> {download_speed} Мбит/с\n"
                f"⬆️ <b>Загрузка / Upload:</b> {upload_speed} Мбит/с\n"
                f"⏱ <b>Задержка / Latency:</b> {latency} мс\n"
                f"📊 <b>Джиттер / Jitter:</b> {jitter} мс\n\n"
                f"🌍 <b>Ваш IP / Your IP:</b> <code>{escape_html(ip)}</code>"
            )
            # --- [КОНЕЦ ИЗМЕНЕНИЙ ПАРСИНГА] ---

        except Exception as e:
            logging.error(f"Неожиданная ошибка обработки speedtest: {e}")
            response_text = f"❌ Неожиданная ошибка при обработке результатов speedtest: {escape_html(str(e))}"
    else:
        error_output = stderr.decode(
            'utf-8',
            errors='ignore') or stdout.decode(
            'utf-8',
            errors='ignore')
        logging.error(
            f"Ошибка выполнения speedtest. Код: {process.returncode}. Вывод: {error_output}")
        
        # --- [НАЧАЛО ИЗМЕНЕНИЙ ОБРАБОТКИ ОШИБОК] ---
        if "command not found" in error_output.lower() or "not found" in error_output.lower() or "ENOENT" in error_output:
             response_text = "❌ <b>Ошибка:</b> <code>npx</code> или <code>speed-cloudflare-cli</code> не найден.\nУбедитесь, что <b>NPM</b> установлен (<code>sudo apt install npm</code>) и <code>npx</code> доступен."
        else:
            response_text = f"❌ Ошибка при запуске speedtest:\n<pre>{escape_html(error_output)}</pre>"
        # --- [КОНЕЦ ИЗМЕНЕНИЙ ОБРАБОТКИ ОШИБОК] ---

    sent_message_final = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
    LAST_MESSAGE_IDS.setdefault(
        user_id, {})[command] = sent_message_final.message_id