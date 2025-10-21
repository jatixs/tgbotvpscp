# /opt/tg-bot/modules/speedtest.py
import asyncio
import json
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

    sent_message = await message.answer("🚀 Запуск speedtest... Это может занять до минуты.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    cmd = "speedtest --accept-license --accept-gdpr --format=json"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()

    await delete_previous_message(user_id, command, chat_id, message.bot)

    if process.returncode == 0:
        output = stdout.decode('utf-8', errors='ignore')
        try:
            data = json.loads(output)
            download_speed = data.get(
                "download", {}).get(
                "bandwidth", 0) / 125000
            upload_speed = data.get("upload", {}).get("bandwidth", 0) / 125000
            ping_latency = data.get("ping", {}).get("latency", "N/A")
            server_name = data.get("server", {}).get("name", "N/A")
            server_location = data.get("server", {}).get("location", "N/A")
            result_url = data.get("result", {}).get("url", "N/A")

            response_text = (
                f"🚀 <b>Speedtest Результаты:</b>\n\n"
                f"⬇️ <b>Скачивание:</b> {download_speed:.2f} Мбит/с\n"
                f"⬆️ <b>Загрузка:</b> {upload_speed:.2f} Мбит/с\n"
                f"⏱ <b>Пинг:</b> {ping_latency} мс\n\n"
                f"🏢 <b>Сервер:</b> {server_name} ({server_location})\n"
                f"🔗 <b>Подробнее:</b> {result_url}")
        except json.JSONDecodeError as e:
            logging.error(
                f"Ошибка парсинга JSON от speedtest: {e}\nOutput: {output[:500]}")
            response_text = f"❌ Ошибка при обработке результатов speedtest: Неверный формат ответа.\n<pre>{escape_html(output[:1000])}</pre>"
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
        response_text = f"❌ Ошибка при запуске speedtest:\n<pre>{escape_html(error_output)}</pre>"

    sent_message_final = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
    LAST_MESSAGE_IDS.setdefault(
        user_id, {})[command] = sent_message_final.message_id
