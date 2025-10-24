# /opt/tg-bot/modules/fail2ban.py
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
from core.utils import get_country_flag, get_server_timezone_label

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_fail2ban"
# --------------------------------


def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------


def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(fail2ban_handler)
    # --------------------------------------


async def fail2ban_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "fall2ban"  # Имя команды оставляем как есть
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    try:
        F2B_LOG_FILE = "/var/log/fail2ban.log"

        if not await asyncio.to_thread(os.path.exists, F2B_LOG_FILE):
            # --- ИЗМЕНЕНО: Используем i18n ---
            sent_message = await message.answer(
                _("f2b_log_not_found", lang, path=F2B_LOG_FILE),
                parse_mode="HTML"
            )
            # --------------------------------
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
            # --- ИЗМЕНЕНО: Используем i18n ---
            raise Exception(_("f2b_log_read_error", lang))
            # --------------------------------

        log_entries = []
        tz_label = get_server_timezone_label()
        regex_ban = r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* Ban\s+(\S+)"
        regex_already = r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* (\S+)\s+already banned"

        for line in reversed(lines):
            line = line.strip()
            if "fail2ban.actions" not in line:
                continue

            match = None
            ban_type_key = None  # Используем ключ для перевода
            ip = None
            timestamp_str = None

            match_ban_found = re.search(regex_ban, line)
            if match_ban_found:
                match = match_ban_found
                ban_type_key = "f2b_banned"  # Ключ
                timestamp_str, ip = match.groups()
            else:
                match_already_found = re.search(regex_already, line)
                if match_already_found:
                    match = match_already_found
                    ban_type_key = "f2b_already_banned"  # Ключ
                    timestamp_str, ip = match.groups()

            if match and ip and timestamp_str and ban_type_key:
                try:
                    dt = datetime.strptime(
                        timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    formatted_time = dt.strftime('%H:%M:%S')
                    formatted_date = dt.strftime('%d.%m.%Y')
                    # --- ИЗМЕНЕНО: Используем i18n ---
                    ban_type_translated = _(ban_type_key, lang)
                    log_entries.append(
                        _("f2b_ban_entry", lang,
                          ban_type=ban_type_translated,
                          flag=flag, ip=ip,
                          time=formatted_time, tz=tz_label,
                          date=formatted_date)
                    )
                    # --------------------------------
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
            # --- ИЗМЕНЕНО: Используем i18n ---
            sent_message = await message.answer(
                _("f2b_header", lang, log_output=log_output),
                parse_mode="HTML"
            )
            # --------------------------------
        else:
            # --- ИЗМЕНЕНО: Используем i18n ---
            sent_message = await message.answer(_("f2b_no_bans", lang))
            # --------------------------------
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id

    except Exception as e:
        logging.error(f"Ошибка при чтении журнала Fail2Ban: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        sent_message = await message.answer(_("f2b_read_error_generic", lang, error=str(e)))
        # --------------------------------
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
