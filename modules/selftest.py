import asyncio
import logging
import psutil
import aiohttp
import os
import re
import time
from datetime import datetime, timezone, timedelta
from aiogram import Dispatcher, types, F
from aiogram.types import KeyboardButton
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import (
    format_traffic,
    format_uptime,
    get_server_timezone_label,
    get_host_path,
    escape_html,
)

BUTTON_KEY = "btn_selftest"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(selftest_handler)


async def get_external_ips_for_selftest() -> tuple[str, str, bool]:
    endpoints = {
        "ipv4": [
            "https://api.ipify.org",
            "https://ipv4.icanhazip.com",
            "https://ifconfig.me/ip",
        ],
        "ipv6": [
            "https://api6.ipify.org",
            "https://ipv6.icanhazip.com",
            "https://ifconfig.me/ip",
        ],
    }

    results = {"ipv4": "", "ipv6": ""}

    async def fetch_ip(session: aiohttp.ClientSession, family: str) -> str:
        for url in endpoints[family]:
            try:
                async with session.get(url, timeout=2) as resp:
                    if resp.status != 200:
                        continue
                    candidate = (await resp.text()).strip()
                    if not candidate:
                        continue
                    if family == "ipv4" and ":" not in candidate:
                        return candidate
                    if family == "ipv6" and ":" in candidate:
                        return candidate
            except Exception:
                continue
        return ""

    connector = aiohttp.TCPConnector(family=0, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        results["ipv4"], results["ipv6"] = await asyncio.gather(
            fetch_ip(session, "ipv4"),
            fetch_ip(session, "ipv6"),
        )

    inet_ok = bool(results["ipv4"] or results["ipv6"])
    return results["ipv4"], results["ipv6"], inet_ok


async def get_ip_data_full(ip: str):
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠", None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{ip}?fields=status,countryCode,offset",
                timeout=2,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        country_code = data.get("countryCode")
                        flag = "❓"
                        if country_code and len(country_code) == 2:
                            flag = "".join(
                                (
                                    chr(ord(char.upper()) - 65 + 127462)
                                    for char in country_code
                                )
                            )
                        return flag, data.get("offset")
    except Exception as e:
        logging.debug(f"Error getting IP data: {e}")
    return "❓", None


async def get_last_ssh_login(lang: str):
    log_files = [
        get_host_path("/var/log/auth.log"),
        get_host_path("/var/log/secure"),
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                proc = await asyncio.create_subprocess_shell(
                    f"tail -n 200 {log_file}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr_data = await proc.communicate()
                
                lines = stdout.decode("utf-8", errors="ignore").splitlines()
                
                for line in reversed(lines):
                    match = re.search(r"Accepted\s+(\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
                    if match:
                        method_raw = match.group(1).lower()
                        user = escape_html(match.group(2))
                        ip = escape_html(match.group(3))
                        
                        method_key = "auth_method_unknown"
                        if "publickey" in method_raw:
                            method_key = "auth_method_key"
                        elif "password" in method_raw:
                            method_key = "auth_method_password"
                        
                        method_str = _(method_key, lang)

                        flag, offset = await get_ip_data_full(ip)
                        
                        s_now = datetime.now()
                        s_tz_label = get_server_timezone_label()
                        time_str = f"{s_now.strftime('%H:%M:%S')}{s_tz_label}"
                        
                        if offset is not None:
                            try:
                                utc_now = datetime.now(timezone.utc)
                                ip_dt = utc_now + timedelta(seconds=offset)
                                
                                off_h = int(offset / 3600)
                                sign = "+" if off_h >= 0 else ""
                                ip_tz_label = f"GMT{sign}{off_h}"
                                
                                time_str += f" / 📍 {ip_dt.strftime('%H:%M')} ({ip_tz_label})"
                            except Exception:
                                pass

                        return _(
                            "selftest_ssh_entry",
                            lang,
                            user=user,
                            method=method_str,
                            flag=flag,
                            ip=ip,
                            time=time_str,
                            tz="", 
                            source=f" {_('selftest_ssh_source', lang, source=os.path.basename(log_file))}"
                        )
            except Exception as e:
                logging.error(f"Error parsing log file {log_file}: {e}")

    if config.INSTALL_MODE == "root" or config.DEPLOY_MODE != "docker":
        try:
            cmd = "journalctl -u ssh -n 50 --no-pager -o cat"
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr_data = await proc.communicate()
            
            if stdout:
                lines = stdout.decode("utf-8", errors="ignore").splitlines()
                for line in reversed(lines):
                    match = re.search(r"Accepted\s+(\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
                    if match:
                        method_raw = match.group(1).lower()
                        user = escape_html(match.group(2))
                        ip = escape_html(match.group(3))
                        
                        method_key = "auth_method_key" if "publickey" in method_raw else "auth_method_password"
                        method_str = _(method_key, lang)
                        
                        flag, offset = await get_ip_data_full(ip)
                        
                        s_now = datetime.now()
                        s_tz_label = get_server_timezone_label()
                        time_str = f"{s_now.strftime('%H:%M:%S')}{s_tz_label}"
                        
                        if offset is not None:
                            try:
                                utc_now = datetime.now(timezone.utc)
                                ip_dt = utc_now + timedelta(seconds=offset)
                                off_h = int(offset / 3600)
                                sign = "+" if off_h >= 0 else ""
                                time_str += f" / 📍 {ip_dt.strftime('%H:%M')} (GMT{sign}{off_h})"
                            except: pass

                        return _(
                            "selftest_ssh_entry",
                            lang,
                            user=user,
                            method=method_str,
                            flag=flag,
                            ip=ip,
                            time=time_str,
                            tz="",
                            source=f" {_('selftest_ssh_source_journal', lang)}"
                        )
        except Exception as e:
            logging.debug(f"Journalctl check failed: {e}")

    return _("selftest_ssh_not_found", lang)


async def selftest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "selftest"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(
        user_id,
        list(LAST_MESSAGE_IDS.get(user_id, {}).keys()),
        chat_id,
        message.bot,
    )

    loading_msg = await message.answer(_("selftest_gathering_info", lang))

    try:
        cpu = psutil.cpu_percent(interval=0.5)
        _mem = psutil.virtual_memory()
        ram = round((_mem.total - _mem.available) / _mem.total * 100, 1) if _mem.total > 0 else 0
        disk = psutil.disk_usage(get_host_path("/")).percent
        uptime_seconds = time.time() - psutil.boot_time()
        uptime_str = format_uptime(uptime_seconds, lang)

        counters = psutil.net_io_counters()
        rx_fmt = format_traffic(counters.bytes_recv, lang)
        tx_fmt = format_traffic(counters.bytes_sent, lang)

        ip_fail = _("selftest_ip_fail", lang)
        ip_v4 = ip_fail
        ip_v6 = ip_fail
        ping = "n/a"
        inet_status = _("selftest_inet_fail", lang)

        fetched_ipv4, fetched_ipv6, inet_ok = await get_external_ips_for_selftest()
        if fetched_ipv4:
            ip_v4 = fetched_ipv4
        if fetched_ipv6:
            ip_v6 = fetched_ipv6
        if inet_ok:
            inet_status = _("selftest_inet_ok", lang)
        
        # Measure ping: ICMP first (accurate), HTTP fallback if blocked
        import subprocess
        import platform
        try:
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "1", "-w", "2000", "8.8.8.8"]
                pattern = r"[=<](\d+)\s*ms"
            else:
                cmd = ["ping", "-c", "1", "-W", "2", "8.8.8.8"]
                pattern = r"time=([\d\.]+)\s*ms"
            
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr_ignored = await asyncio.wait_for(proc.communicate(), timeout=5)
            ping_match = re.search(pattern, stdout.decode())
            if ping_match:
                ping = str(round(float(ping_match.group(1)), 1))
        except Exception:
            pass
        
        # HTTP fallback if ICMP failed
        if ping == "n/a":
            try:
                async with aiohttp.ClientSession() as session:
                    t1 = time.time()
                    async with session.get("http://www.google.com", timeout=2) as resp:
                        if resp.status == 200:
                            ping = f"{int((time.time() - t1) * 1000)}"
            except Exception:
                pass

        ssh_info = ""
        if config.INSTALL_MODE == "root" or os.geteuid() == 0:
             ssh_entry = await get_last_ssh_login(lang)
             ssh_info = _("selftest_ssh_header", lang, source="") + ssh_entry
        else:
             ssh_info = _("selftest_ssh_root_only", lang)

        header = _("selftest_results_header", lang)
        body = _(
            "selftest_results_body",
            lang,
            cpu=cpu,
            mem=ram,
            disk=disk,
            uptime=uptime_str,
            inet_status=inet_status,
            ping=ping,
            ipv4=ip_v4,
            ipv6=ip_v6,
            rx=rx_fmt,
            tx=tx_fmt,
        )

        full_text = f"{header}{body}{ssh_info}"

        await loading_msg.edit_text(full_text, parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = loading_msg.message_id

    except Exception as e:
        logging.error(f"Selftest error: {e}")
        await loading_msg.edit_text(
            _("selftest_error", lang, error=str(e)), parse_mode="HTML"
        )