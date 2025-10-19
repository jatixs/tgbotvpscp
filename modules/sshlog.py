# /opt/tg-bot/modules/sshlog.py
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

BUTTON_TEXT = "📜 SSH-лог"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(sshlog_handler)

async def sshlog_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "sshlog"
    if not is_allowed(user_id, command):
         await send_access_denied_message(message.bot, user_id, chat_id, command)
         return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    sent_message = await message.answer("🔍 Ищу последние 10 событий SSH (вход/провал)...")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    try:
        log_file = None
        if await asyncio.to_thread(os.path.exists, "/var/log/secure"):
            log_file = "/var/log/secure"
        elif await asyncio.to_thread(os.path.exists, "/var/log/auth.log"):
            log_file = "/var/log/auth.log"

        lines = []
        source = ""
        log_entries = []
        found_count = 0

        if log_file:
            source = f" (из {os.path.basename(log_file)})"
            cmd = f"tail -n 200 {log_file}"
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0: raise Exception(stderr.decode())
            lines = stdout.decode().strip().split('\n')
        else:
            source = " (из journalctl, за месяц)"
            cmd = "journalctl -u ssh -n 100 --no-pager --since '1 month ago' -o short-precise"
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                raise Exception("journalctl завис (тайм-аут 5с)")
            if process.returncode != 0: raise Exception(stderr.decode())
            lines = stdout.decode().strip().split('\n')

        tz_label = get_server_timezone_label()

        for line in reversed(lines):
            if found_count >= 10:
                break

            line = line.strip()
            if "sshd" not in line:
                continue

            dt_object = None
            date_match_iso = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            date_match_syslog = re.search(r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

            try:
                if date_match_iso:
                    dt_object = datetime.strptime(date_match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                elif date_match_syslog:
                    log_timestamp = datetime.strptime(date_match_syslog.group(1), "%b %d %H:%M:%S")
                    current_year = datetime.now().year
                    dt_object = log_timestamp.replace(year=current_year)
                    if dt_object > datetime.now():
                        dt_object = dt_object.replace(year=current_year - 1)
                else:
                    continue
            except Exception as e:
                logging.warning(f"Sshlog: не удалось распарсить дату: {e}. Строка: {line}")
                continue

            formatted_time = dt_object.strftime('%H:%M:%S')
            formatted_date = dt_object.strftime('%d.%m.%Y')

            entry = None

            match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
            if match:
                user = match.group(1)
                ip = match.group(2)
                flag = await asyncio.to_thread(get_country_flag, ip)
                entry = f"✅ <b>Успешный вход</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if not entry:
                match = re.search(r"Failed\s+(?:\S+)\s+for\s+invalid\s+user\s+(\S+)\s+from\s+(\S+)", line)
                if match:
                    user = match.group(1)
                    ip = match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry = f"❌ <b>Неверный юзер</b>\n👤 Попытка: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if not entry:
                match = re.search(r"Failed password for (\S+) from (\S+)", line)
                if match:
                    user = match.group(1)
                    ip = match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry = f"❌ <b>Неверный пароль</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if not entry:
                match = re.search(r"authentication failure;.*rhost=(\S+)\s+user=(\S+)", line)
                if match:
                    ip = match.group(1)
                    user = match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry = f"❌ <b>Провал (PAM)</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if entry:
                log_entries.append(entry)
                found_count += 1

        if log_entries:
            log_output = "\n\n".join(log_entries)
            await message.bot.edit_message_text(f"🔐 <b>Последние {found_count} событий SSH{source}:</b>\n\n{log_output}", chat_id=chat_id, message_id=sent_message.message_id, parse_mode="HTML")
        else:
            await message.bot.edit_message_text(f"🔐 Не найдено событий SSH (вход/провал){source}.", chat_id=chat_id, message_id=sent_message.message_id)

    except Exception as e:
        logging.error(f"Ошибка при чтении журнала SSH: {e}")
        await message.bot.edit_message_text(f"⚠️ Ошибка при чтении журнала SSH: {str(e)}", chat_id=chat_id, message_id=sent_message.message_id)