# /opt/tg-bot/modules/sshlog.py
import asyncio
import os
import re
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
# Добавлен escape_html
from core.utils import get_country_flag, get_server_timezone_label, escape_html, get_host_path # <-- Добавлен get_host_path

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_sshlog"
# --------------------------------


def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------


def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(sshlog_handler)
    # --------------------------------------


async def sshlog_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "sshlog"  # Имя команды оставляем
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    # --- ИЗМЕНЕНО: Используем i18n ---
    sent_message = await message.answer(_("sshlog_searching", lang))
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    try:
        log_file = None
        # --- ИЗМЕНЕНО: Используем get_host_path ---
        secure_path = get_host_path("/var/log/secure")
        auth_path = get_host_path("/var/log/auth.log")
        if await asyncio.to_thread(os.path.exists, secure_path):
            log_file = secure_path
        elif await asyncio.to_thread(os.path.exists, auth_path):
            log_file = auth_path
        # -----------------------------------------

        lines = []
        source_text = ""
        log_entries = []
        found_count = 0

        if log_file:
            # --- ИЗМЕНЕНО: Используем i18n ---
            source = os.path.basename(log_file)
            # Используем ключ из selftest
            source_text = _("selftest_ssh_source", lang, source=source)
            # --------------------------------
            cmd = f"tail -n 200 {log_file}"
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise Exception(stderr.decode())
            lines = stdout.decode().strip().split('\n')
        else:
            # --- ИЗМЕНЕНО: Используем i18n ---
            source_text = _(
                "selftest_ssh_source_journal",
                lang)  # Используем ключ из selftest
            # --------------------------------
            # --- ИЗМЕНЕНО: journalctl должен работать в docker-root из-за pid:host ---
            cmd = "journalctl -u ssh -n 100 --no-pager --since '1 month ago' -o short-precise"
            # ---------------------------------------------------------------------
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                raise Exception("journalctl timeout")
            if process.returncode != 0:
                raise Exception(stderr.decode())
            lines = stdout.decode().strip().split('\n')

        tz_label = get_server_timezone_label()

        for line in reversed(lines):
            if found_count >= 10:
                break

            line = line.strip()
            if "sshd" not in line:
                continue

            dt_object = None
            date_match_iso = re.search(
                r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            date_match_syslog = re.search(
                r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

            try:
                if date_match_iso:
                    dt_object = datetime.strptime(
                        date_match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                elif date_match_syslog:
                    log_timestamp = datetime.strptime(
                        date_match_syslog.group(1), "%b %d %H:%M:%S")
                    current_year = datetime.now().year
                    dt_object = log_timestamp.replace(year=current_year)
                    if dt_object > datetime.now():
                        dt_object = dt_object.replace(year=current_year - 1)
                else:
                    continue
            except Exception as e:
                logging.warning(
                    f"Sshlog: не удалось распарсить дату: {e}. Строка: {line}")
                continue

            formatted_time = dt_object.strftime('%H:%M:%S')
            formatted_date = dt_object.strftime('%d.%m.%Y')

            entry_key = None  # Ключ для i18n
            entry_data = {}  # Данные для форматирования

            match = re.search(
                r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
            if match:
                entry_key = "sshlog_entry_success"
                user = escape_html(match.group(1))
                ip = escape_html(match.group(2))
                flag = await asyncio.to_thread(get_country_flag, ip)
                entry_data = {"user": user, "flag": flag, "ip": ip}

            if not entry_key:
                match = re.search(
                    r"Failed\s+(?:\S+)\s+for\s+invalid\s+user\s+(\S+)\s+from\s+(\S+)", line)
                if match:
                    entry_key = "sshlog_entry_invalid_user"
                    user = escape_html(match.group(1))
                    ip = escape_html(match.group(2))
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry_data = {"user": user, "flag": flag, "ip": ip}

            if not entry_key:
                match = re.search(
                    r"Failed password for (\S+) from (\S+)", line)
                if match:
                    entry_key = "sshlog_entry_wrong_pass"
                    user = escape_html(match.group(1))
                    ip = escape_html(match.group(2))
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry_data = {"user": user, "flag": flag, "ip": ip}

            if not entry_key:
                match = re.search(
                    r"authentication failure;.*rhost=(\S+)\s+user=(\S+)", line)
                if match:
                    entry_key = "sshlog_entry_fail_pam"
                    ip = escape_html(match.group(1))
                    user = escape_html(match.group(2))
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry_data = {"user": user, "flag": flag, "ip": ip}

            if entry_key:
                # --- ИЗМЕНЕНО: Добавляем форматированную строку i18n ---
                entry_data.update(
                    {"time": formatted_time, "tz": tz_label, "date": formatted_date})
                log_entries.append(_(entry_key, lang, **entry_data))
                # -------------------------------------------------------
                found_count += 1

        if log_entries:
            log_output = "\n\n".join(log_entries)
            # --- ИЗМЕНЕНО: Используем i18n ---
            await message.bot.edit_message_text(
                _("sshlog_header", lang, count=found_count, source=source_text, log_output=log_output),
                chat_id=chat_id,
                message_id=sent_message.message_id,
                parse_mode="HTML"
            )
            # --------------------------------
        else:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await message.bot.edit_message_text(
                _("sshlog_not_found", lang, source=source_text),
                chat_id=chat_id,
                message_id=sent_message.message_id
            )
            # --------------------------------

    except Exception as e:
        logging.error(f"Ошибка при чтении журнала SSH: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.bot.edit_message_text(
            _("sshlog_read_error", lang, error=escape_html(str(e))),
            chat_id=chat_id,
            message_id=sent_message.message_id
        )
        # --------------------------------
