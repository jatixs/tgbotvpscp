# /opt/tg-bot/modules/fail2ban.py
import asyncio
import os
import re
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import get_country_flag, get_server_timezone_label

BUTTON_TEXT = "🔒 Fail2Ban Log"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(fail2ban_handler)


async def fail2ban_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "fall2ban"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    try:
        F2B_LOG_FILE = "/var/log/fail2ban.log"

        if not await asyncio.to_thread(os.path.exists, F2B_LOG_FILE):
            sent_message = await message.answer(f"⚠️ Файл лога Fail2Ban не найден: <code>{F2B_LOG_FILE}</code>", parse_mode="HTML")
            LAST_MESSAGE_IDS.setdefault(
                user_id, {})[command] = sent_message.message_id
            return

        def read_f2b_log():
            try:
                with open(F2B_LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
                    return f.readlines()[-50:]
            except Exception as read_e:
                logging.error(f"Error reading Fail2Ban log file: {read_e}")
                return None

        lines = await asyncio.to_thread(read_f2b_log)

        if lines is None:
            raise Exception("Не удалось прочитать файл лога.")

        log_entries = []
        tz_label = get_server_timezone_label()
        regex_ban = r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* Ban\s+(\S+)"
        regex_already = r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* (\S+)\s+already banned"

        for line in reversed(lines):
            line = line.strip()
            if "fail2ban.actions" not in line:
                continue

            match = None
            ban_type = None
            ip = None
            timestamp_str = None

            match_ban_found = re.search(regex_ban, line)
            if match_ban_found:
                match = match_ban_found
                ban_type = "Бан"
                timestamp_str, ip = match.groups()
            else:
                match_already_found = re.search(regex_already, line)
                if match_already_found:
                    match = match_already_found
                    ban_type = "Уже забанен"
                    timestamp_str, ip = match.groups()

            if match and ip and timestamp_str:
                try:
                    dt = datetime.strptime(
                        timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    formatted_time = dt.strftime('%H:%M:%S')
                    formatted_date = dt.strftime('%d.%m.%Y')
                    log_entries.append(
                        f"🔒 <b>{ban_type}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Время: <b>{formatted_time}</b>{tz_label}\n🗓️ Дата: <b>{formatted_date}</b>")
                except ValueError:
                    logging.warning(
                        f"Could not parse Fail2Ban timestamp: {timestamp_str}")
                    continue
                except Exception as parse_e:
                    logging.error(
                        f"Error processing Fail2Ban line: {parse_e} | Line: {line}")
                    continue

            if len(log_entries) >= 10:
                break

        if log_entries:
            log_output = "\n\n".join(log_entries)
            sent_message = await message.answer(f"🔒 <b>Последние 10 блокировок IP (Fail2Ban):</b>\n\n{log_output}", parse_mode="HTML")
        else:
            sent_message = await message.answer("🔒 Нет недавних блокировок IP в логах Fail2Ban (проверено 50 последних строк).")
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id

    except Exception as e:
        logging.error(f"Ошибка при чтении журнала Fail2Ban: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журнала Fail2Ban: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
