# /opt/tg-bot/modules/selftest.py
import asyncio
import psutil
import time
import re
import os
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
from core.utils import format_uptime, format_traffic, get_country_flag, get_server_timezone_label, escape_html # Добавлен escape_html
from core.config import INSTALL_MODE

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_selftest"
# --------------------------------

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(selftest_handler)
    # --------------------------------------

async def selftest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "selftest" # Имя команды оставляем

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    # --- ИЗМЕНЕНО: Используем i18n ---
    sent_message = await message.answer(_("selftest_gathering_info", lang))
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    def get_system_stats_sync():
        psutil.cpu_percent(interval=None)
        time.sleep(0.2)
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        with open("/proc/uptime") as f:
            uptime_sec = float(f.readline().split()[0])
        counters = psutil.net_io_counters()
        rx = counters.bytes_recv
        tx = counters.bytes_sent
        return cpu, mem, disk, uptime_sec, rx, tx

    try:
        cpu, mem, disk, uptime_sec, rx, tx = await asyncio.to_thread(get_system_stats_sync)
    except Exception as e:
        logging.error(f"Ошибка при сборе системной статистики: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.bot.edit_message_text(
            _("selftest_error", lang, error=e), 
            chat_id=chat_id, 
            message_id=sent_message.message_id
        )
        # --------------------------------
        return

    uptime_str = format_uptime(uptime_sec)

    ping_cmd = "ping -c 1 -W 1 8.8.8.8"
    ping_process = await asyncio.create_subprocess_shell(
        ping_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    ping_stdout, _ = await ping_process.communicate()
    ping_result = ping_stdout.decode()
    ping_match = re.search(r"time=([\d\.]+) ms", ping_result)
    ping_time = ping_match.group(1) if ping_match else "N/A"
    # --- ИЗМЕНЕНО: Используем i18n ---
    internet = _("selftest_inet_ok", lang) if ping_match else _("selftest_inet_fail", lang)
    # --------------------------------

    ip_cmd = "curl -4 -s --max-time 3 ifconfig.me"
    ip_process = await asyncio.create_subprocess_shell(
        ip_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    ip_stdout, _ = await ip_process.communicate()
    # --- ИЗМЕНЕНО: Используем i18n ---
    external_ip = ip_stdout.decode().strip() or _("selftest_ip_fail", lang)
    # --------------------------------

    last_login_info = ""
    if INSTALL_MODE == "root":
        try:
            log_file = None
            if await asyncio.to_thread(os.path.exists, "/var/log/secure"):
                log_file = "/var/log/secure"
            elif await asyncio.to_thread(os.path.exists, "/var/log/auth.log"):
                log_file = "/var/log/auth.log"

            line = None
            source_text = ""

            if log_file:
                # --- ИЗМЕНЕНО: Используем i18n ---
                source = os.path.basename(log_file)
                source_text = _("selftest_ssh_source", lang, source=source)
                # --------------------------------
                cmd = f"tail -n 100 {log_file}"
                process = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0: raise Exception(stderr.decode())

                for l in reversed(stdout.decode().strip().split('\n')):
                    if "Accepted" in l and "sshd" in l:
                        line = l.strip()
                        break
            else:
                # --- ИЗМЕНЕНО: Используем i18n ---
                source_text = _("selftest_ssh_source_journal", lang)
                # --------------------------------
                cmd = "journalctl -u ssh --no-pager -g 'Accepted' | tail -n 1"
                process = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
                except asyncio.TimeoutError:
                    raise Exception("journalctl timeout") # Оставим на английском для логов

                if process.returncode != 0: raise Exception(stderr.decode())
                line = stdout.decode().strip()

            # --- ИЗМЕНЕНО: Используем i18n ---
            ssh_header = _("selftest_ssh_header", lang, source=source_text)
            # --------------------------------
            
            if line:
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
                except Exception as e:
                    logging.warning(f"Selftest: не удалось распарсить дату: {e}. Строка: {line}")

                login_match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)

                if dt_object and login_match:
                    user = escape_html(login_match.group(1)) # Экранируем
                    ip = escape_html(login_match.group(2))   # Экранируем
                    flag = await asyncio.to_thread(get_country_flag, ip)

                    tz_label = get_server_timezone_label()
                    formatted_time = dt_object.strftime("%H:%M")
                    formatted_date = dt_object.strftime("%d.%m.%Y")

                    # --- ИЗМЕНЕНО: Используем i18n ---
                    last_login_info = ssh_header + _("selftest_ssh_entry", lang, 
                                                     user=user, flag=flag, ip=ip, 
                                                     time=formatted_time, tz=tz_label, 
                                                     date=formatted_date)
                    # --------------------------------
                else:
                    logging.warning(f"Selftest: Не удалось разобрать строку SSH (login_match={login_match}, dt_object={dt_object}): {line}")
                    # --- ИЗМЕНЕНО: Используем i18n ---
                    last_login_info = ssh_header + _("selftest_ssh_parse_fail", lang)
                    # --------------------------------
            else:
                # --- ИЗМЕНЕНО: Используем i18n ---
                last_login_info = ssh_header + _("selftest_ssh_not_found", lang)
                # --------------------------------

        except Exception as e:
            logging.warning(f"SSH log check skipped: {e}")
            # --- ИЗМЕНЕНО: Используем i18n ---
            last_login_info = _("selftest_ssh_header", lang, source="") + _("selftest_ssh_read_error", lang, error=escape_html(str(e)))
            # --------------------------------
    else:
        # --- ИЗМЕНЕНО: Используем i18n ---
        last_login_info = _("selftest_ssh_root_only", lang)
        # --------------------------------

    # --- ИЗМЕНЕНО: Формируем ответ с i18n ---
    response_header = _("selftest_results_header", lang)
    response_body = _("selftest_results_body", lang, 
                      cpu=cpu, mem=mem, disk=disk, 
                      uptime=uptime_str, 
                      inet_status=internet, 
                      ping=ping_time, 
                      ip=external_ip, 
                      rx=format_traffic(rx), 
                      tx=format_traffic(tx))
    response_text = response_header + response_body + last_login_info
    # -----------------------------------------

    await message.bot.edit_message_text(response_text, chat_id=chat_id, message_id=sent_message.message_id, parse_mode="HTML")