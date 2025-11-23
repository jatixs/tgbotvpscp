import asyncio
import psutil
import time
import re
import os
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.i18n import I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import format_uptime, format_traffic, get_country_flag, get_server_timezone_label, escape_html, get_host_path
from core.config import INSTALL_MODE

BUTTON_KEY = "btn_selftest"


def get_button() -> KeyboardButton:
    from core.i18n import _
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(selftest_handler)


async def selftest_handler(message: types.Message):
    from core.i18n import _
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "selftest"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    sent_msg = await message.answer(_("selftest_gathering_info", lang))
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id

    try:
        psutil.cpu_percent(interval=None)
        await asyncio.sleep(0.5)
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        try:
            disk = psutil.disk_usage(get_host_path('/')).percent
        except BaseException:
            disk = 0
        with open(get_host_path("/proc/uptime")) as f:
            uptime_sec = float(f.readline().split()[0])
        net = psutil.net_io_counters()

        uptime_str = format_uptime(uptime_sec, lang)

        # Проверка доступности Интернета (HTTP/S)
        conn_proc = await asyncio.create_subprocess_shell(
            "curl -I -s --max-time 3 https://www.google.com/", # -I: HEAD request, -s: silent
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE
        )
        c_out, c_err = await conn_proc.communicate()
        
        conn_ok = conn_proc.returncode == 0 and b'HTTP/' in c_out.upper()
        
        inet_status = _(
            "selftest_inet_ok",
            lang) if conn_ok else _(
            "selftest_inet_fail",
            lang)

        # Ping check (async subprocess - только для метрики задержки)
        ping_proc = await asyncio.create_subprocess_shell("ping -c 1 -W 1 8.8.8.8", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        # FIX: _ -> stderr_dummy
        p_out, stderr_dummy = await ping_proc.communicate()
        p_match = re.search(r"time=([\d\.]+) ms", p_out.decode())
        ping_time = p_match.group(1) if p_match else "N/A"

        # IP check (async subprocess)
        ip_proc = await asyncio.create_subprocess_shell("curl -4 -s --max-time 2 ifconfig.me", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        # FIX: _ -> stderr_dummy
        ip_out, stderr_dummy = await ip_proc.communicate()
        ext_ip = ip_out.decode().strip() or _("selftest_ip_fail", lang)

        ssh_info = ""
        if INSTALL_MODE == "root":
            log_file = None
            if os.path.exists(get_host_path("/var/log/secure")):
                log_file = get_host_path("/var/log/secure")
            elif os.path.exists(get_host_path("/var/log/auth.log")):
                log_file = get_host_path("/var/log/auth.log")

            line = None
            src = ""

            if log_file:
                src = _(
                    "selftest_ssh_source",
                    lang,
                    source=os.path.basename(log_file))
                proc = await asyncio.create_subprocess_shell(f"tail -n 50 {log_file}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                # FIX: _ -> stderr_dummy
                l_out, stderr_dummy = await proc.communicate()
                for l in reversed(l_out.decode('utf-8', 'ignore').split('\n')):
                    if "Accepted" in l and "sshd" in l:
                        line = l.strip()
                        break
            else:
                src = _("selftest_ssh_source_journal", lang)
                proc = await asyncio.create_subprocess_shell("journalctl -u ssh --no-pager -n 50", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                # FIX: _ -> stderr_dummy
                j_out, stderr_dummy = await proc.communicate()
                for l in reversed(j_out.decode('utf-8', 'ignore').split('\n')):
                    if "Accepted" in l:
                        line = l.strip()
                        break

            ssh_header = _("selftest_ssh_header", lang, source=src)

            if line:
                match = re.search(
                    r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)

                if match:
                    u = escape_html(match.group(1))
                    ip = escape_html(match.group(2))
                    fl = await get_country_flag(ip)
                    
                    # --- [ИСПРАВЛЕНИЕ] Логика парсинга даты/времени из sshlog.py ---
                    tz = get_server_timezone_label()
                    dt = None
                    
                    match_iso = re.search(
                        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                    match_sys = re.search(
                        r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

                    try:
                        if match_iso:
                            dt = datetime.strptime(
                                match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                        elif match_sys:
                            dt = datetime.strptime(
                                match_sys.group(1), "%b %d %H:%M:%S")
                            dt = dt.replace(year=datetime.now().year)
                    except BaseException:
                        pass # Если парсинг не удался, dt останется None
                    
                    time_str = dt.strftime('%H:%M:%S') if dt else "?"
                    date_str = dt.strftime('%d.%m.%Y') if dt else "?"
                    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                    
                    ssh_info = ssh_header + \
                        _("selftest_ssh_entry", lang, user=u, flag=fl, ip=ip, time=time_str, tz=tz, date=date_str)
                else:
                    ssh_info = ssh_header + _("selftest_ssh_parse_fail", lang)
            else:
                ssh_info = ssh_header + _("selftest_ssh_not_found", lang)
        else:
            ssh_info = _("selftest_ssh_root_only", lang)

        body = _(
            "selftest_results_body",
            lang,
            cpu=cpu,
            mem=mem,
            disk=disk,
            uptime=uptime_str,
            inet_status=inet_status,
            ping=ping_time,
            ip=ext_ip,
            rx=format_traffic(
                net.bytes_recv,
                lang),
            tx=format_traffic(
                net.bytes_sent,
                lang))
        await message.bot.edit_message_text(_("selftest_results_header", lang) + body + ssh_info, chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Error in selftest: {e}")
        await message.bot.edit_message_text(_("selftest_error", lang, error=str(e)), chat_id=chat_id, message_id=sent_msg.message_id)