import asyncio
import re
import logging
import json
import platform
import shlex
import os
import concurrent.futures
import time
import aiohttp
from typing import Optional, Dict, Any, Tuple, List
import ipaddress
import yaml

from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html, get_country_details

BUTTON_KEY = "btn_speedtest"
SERVER_LIST_URL = "https://export.iperf3serverlist.net/listed_iperf3_servers.json"
RU_SERVER_LIST_URL = "https://raw.githubusercontent.com/itdoginfo/russian-iperf3-servers/refs/heads/main/list.yml"
LOCAL_CACHE_FILE = os.path.join(config.CONFIG_DIR, "iperf_servers_cache.json")
LOCAL_RU_CACHE_FILE = os.path.join(
    config.CONFIG_DIR,
    "iperf_servers_ru_cache.yml")

MAX_SERVERS_TO_PING = 100 
PING_COUNT = 3
PING_TIMEOUT_SEC = 2
IPERF_TEST_DURATION = 8
IPERF_PROCESS_TIMEOUT = 30.0
MAX_TEST_ATTEMPTS = 3
MESSAGE_EDIT_THROTTLE = {}
MIN_UPDATE_INTERVAL = 1.5


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(speedtest_handler)


async def edit_status_safe(
        bot: Bot,
        chat_id: int,
        message_id: Optional[int],
        text: str,
        lang: str,
        force: bool = False):
    if not message_id:
        return message_id
    now = time.time()
    last_update = MESSAGE_EDIT_THROTTLE.get(message_id, 0)
    if not force and (now - last_update < MIN_UPDATE_INTERVAL):
        return message_id
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML")
        MESSAGE_EDIT_THROTTLE[message_id] = now
        return message_id
    except Exception:
        return None


async def get_ping_async(host: str) -> Optional[float]:
    safe_host = shlex.quote(host)
    os_type = platform.system().lower()
    if os_type == "windows":
        cmd = f"ping -n {PING_COUNT} -w {PING_TIMEOUT_SEC * 1000} {safe_host}"
        regex = r"Average = ([\d.]+)ms"
    elif os_type == "linux":
        cmd = f"ping -c {PING_COUNT} -W {PING_TIMEOUT_SEC} {safe_host}"
        regex = r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/"
    else:
        cmd = f"ping -c {PING_COUNT} -t {PING_TIMEOUT_SEC} {safe_host}"
        regex = r"round-trip min/avg/max/stddev = [\d.]+/([\d.]+)/"

    try:
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        output = stdout.decode('utf-8', 'ignore')
        match = re.search(regex, output)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None

async def get_vps_location() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    ip, country_code, continent = None, None, None
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get("https://api.ipify.org?format=json", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ip = data.get("ip")
            except Exception:
                pass

            if not ip:
                try:
                    async with session.get("https://ipinfo.io/ip", timeout=5) as resp:
                        if resp.status == 200:
                            ip = (await resp.text()).strip()
                except Exception:
                    pass

            if ip:
                try:
                    async with session.get(f"http://ip-api.com/json/{ip}?fields=status,countryCode,continent", timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == "success":
                                country_code = data.get("countryCode")
                                continent = data.get("continent")
                                logging.info(
                                    f"Detected VPS Location: {country_code} ({continent})")
                except Exception:
                    pass
    except Exception:
        pass
    return ip, country_code, continent


def is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def fetch_servers_async(
        vps_country_code: Optional[str]) -> List[Dict[str, Any]]:
    servers_list = []
    use_ru = vps_country_code == 'RU'

    async with aiohttp.ClientSession() as session:
        if use_ru:
            logging.info(f"VPS in RU, trying to fetch RU server list...")
            content = None
            try:
                async with session.get(RU_SERVER_LIST_URL, timeout=10) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        with open(LOCAL_RU_CACHE_FILE, "w", encoding='utf-8') as f:
                            f.write(content)
            except Exception:
                if os.path.exists(LOCAL_RU_CACHE_FILE):
                    with open(LOCAL_RU_CACHE_FILE, "r", encoding='utf-8') as f:
                        content = f.read()

            if content:
                try:
                    data = yaml.safe_load(content)
                    for s in data:
                        if 'address' in s and 'port' in s:
                            port = int(str(s['port']).split('-')[0].strip())
                            servers_list.append({"host": s['address'], "port": port, "city": s.get(
                                'City'), "country": "RU", "provider": s.get('Name'), "continent": "EU"})
                    logging.info(f"Loaded {len(servers_list)} RU servers.")
                    return servers_list
                except Exception:
                    pass

        try:
            async with session.get(SERVER_LIST_URL, timeout=10) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    with open(LOCAL_CACHE_FILE, "w", encoding='utf-8') as f:
                        f.write(content)
        except Exception:
            pass
        
        # --- Оптимизация RAM: потоковая загрузка JSON вместо чтения всего файла в строку ---
        if os.path.exists(LOCAL_CACHE_FILE):
            try:
                with open(LOCAL_CACHE_FILE, "r", encoding='utf-8') as f:
                    data = json.load(f)
                
                for s in data:
                    host, port_str = s.get("IP/HOST"), s.get("PORT")
                    if not host or not port_str:
                        continue
                    try:
                        port = int(str(port_str).split('-')[0].strip())
                    except Exception:
                        continue

                    servers_list.append({
                        "host": host, "port": port, "city": s.get("SITE", "N/A"),
                        "country": s.get("COUNTRY"), 
                        "continent": s.get("CONTINENT"),
                        "provider": s.get("PROVIDER", "N/A")
                    })
            except Exception:
                pass

    return servers_list


async def find_best_servers_async(
        servers: list, vps_country_code: Optional[str], vps_continent: Optional[str]) -> List[Tuple[float, Dict[str, Any]]]:
    to_check = servers[:MAX_SERVERS_TO_PING]
    tasks = []
    for s in to_check:
        tasks.append(get_ping_async(s["host"]))

    pings = await asyncio.gather(*tasks)
    results = []
    for i, ping in enumerate(pings):
        if ping is not None:
            server_data = to_check[i]
            
            continent_match_key = 0 if server_data.get("continent") == vps_continent else 1
            country_match_key = 0 if server_data.get("country") == vps_country_code else 1
            is_ip_key = is_ip_address(server_data["host"])
            
            results.append((continent_match_key, country_match_key, is_ip_key, ping, server_data))

    results.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    final_results = [(item[3], item[4]) for item in results]

    if final_results:
        logging.info(
            f"Best server found: {final_results[0][1]['host']} ({final_results[0][0]:.2f} ms)")
    return final_results


def _handle_iperf_error_output(out_bytes: bytes, err_bytes: bytes, returncode: int, direction: str) -> Optional[str]:
    output = (err_bytes or out_bytes).decode('utf-8', 'ignore')
    
    if returncode == 0:
        return None
        
    specific_error = "Connection or Timeout Error"
    try:
        error_data = json.loads(output)
        if "error" in error_data:
            specific_error = error_data["error"]
        elif "end" in error_data and "error" in error_data["end"]:
            specific_error = error_data["end"]["error"]
    except json.JSONDecodeError:
        specific_error = output[-100:] if len(output) > 100 else output
    
    log_prefix = "DL" if direction == "download" else "UL"
    logging.error(f"{log_prefix} Test failed (Code {returncode}): {specific_error}")
    
    return f"{log_prefix}_FAIL:{specific_error[:200]}"


async def run_iperf_test_async(
        bot: Bot,
        chat_id: int,
        message_id: int,
        server: dict,
        ping: float,
        lang: str) -> str:
    host = server["host"]
    port = str(server["port"])
    safe_host = shlex.quote(host)
    safe_port = shlex.quote(port)

    logging.info(f"Starting iperf3 test on {host}:{port}...")
    await edit_status_safe(bot, chat_id, message_id, _("speedtest_status_testing", lang, host=escape_html(host), ping=f"{ping:.2f}"), lang)

    cmd_dl = f"iperf3 -c {safe_host} -p {safe_port} -J -t {IPERF_TEST_DURATION} -R -4"
    cmd_ul = f"iperf3 -c {safe_host} -p {safe_port} -J -t {IPERF_TEST_DURATION} -4"

    results = {"download": 0.0, "upload": 0.0, "ping": ping}

    await edit_status_safe(bot, chat_id, message_id, _("speedtest_status_downloading", lang, host=escape_html(host), ping=f"{ping:.2f}"), lang)
    try:
        proc = await asyncio.create_subprocess_shell(cmd_dl, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=IPERF_PROCESS_TIMEOUT)
        
        if proc.returncode != 0:
            return _handle_iperf_error_output(out, err, proc.returncode, "download")
        
        try:
            data = json.loads(out)
            if "sum_received" not in data["end"]:
                 return f"DOWNLOAD_FAIL: No sum_received in final report"

            results["download"] = data["end"]["sum_received"]["bits_per_second"] / 1_000_000
            logging.info(f"Download speed: {results['download']:.2f} Mbps")
        except json.JSONDecodeError:
            return f"DOWNLOAD_FAIL: JSON Decode Error"
            
    except Exception as e:
        logging.error(f"DL Error: {e}")
        return str(e)

    await edit_status_safe(bot, chat_id, message_id, _("speedtest_status_uploading", lang, host=escape_html(host), ping=f"{ping:.2f}"), lang)
    try:
        proc = await asyncio.create_subprocess_shell(cmd_ul, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=IPERF_PROCESS_TIMEOUT)
        
        if proc.returncode != 0:
            return _handle_iperf_error_output(out, err, proc.returncode, "upload")
            
        try:
            data = json.loads(out)
            if "sum_sent" not in data["end"]:
                 return f"UPLOAD_FAIL: No sum_sent in final report"

            results["upload"] = data["end"]["sum_sent"]["bits_per_second"] / 1_000_000
            logging.info(f"Upload speed: {results['upload']:.2f} Mbps")
        except json.JSONDecodeError:
            return f"UPLOAD_FAIL: JSON Decode Error"
            
    except Exception as e:
        logging.error(f"UL Error: {e}")
        return str(e)

    flag, country_name = await get_country_details(server.get('country') or host)
    loc = f"{country_name or server.get('country')} {server.get('city')}"

    return _(
        "speedtest_results",
        lang,
        dl=results["download"],
        ul=results["upload"],
        ping=ping,
        flag=flag,
        server=escape_html(loc),
        provider=escape_html(
            server.get('provider')))


async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "speedtest"):
        await send_access_denied_message(message.bot, user_id, message.chat.id, "speedtest")
        return

    await delete_previous_message(user_id, "speedtest", message.chat.id, message.bot)
    msg = await message.answer(_("speedtest_status_geo", lang), parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})["speedtest"] = msg.message_id

    try:
        ip, cc, continent = await get_vps_location()
        fetch_key = "speedtest_status_fetch_ru" if cc == 'RU' else "speedtest_status_fetch"
        await edit_status_safe(message.bot, message.chat.id, msg.message_id, _(fetch_key, lang), lang, force=True)

        all_servers = await fetch_servers_async(cc)
        if not all_servers:
            try:
                await message.bot.edit_message_text(_("iperf_fetch_error", lang), chat_id=message.chat.id, message_id=msg.message_id)
            except TelegramBadRequest: pass
            return

        await edit_status_safe(message.bot, message.chat.id, msg.message_id, _("speedtest_status_ping", lang, count=min(len(all_servers), MAX_SERVERS_TO_PING)), lang, force=True)
        best_servers = await find_best_servers_async(all_servers, cc, continent)

        if not best_servers:
            try:
                await message.bot.edit_message_text(_("iperf_no_servers", lang), chat_id=message.chat.id, message_id=msg.message_id)
            except TelegramBadRequest: pass
            return

        final_text = ""
        for ping, server in best_servers[:MAX_TEST_ATTEMPTS]:
            logging.info(
                f"Attempting test on server: {server['host']} ({ping:.2f} ms)")
            res = await run_iperf_test_async(message.bot, message.chat.id, msg.message_id, server, ping, lang)
            
            if not res.startswith("DL_FAIL:") and not res.startswith("UL_FAIL:") and not res.startswith("DOWNLOAD_FAIL:") and not res.startswith("UPLOAD_FAIL:"):
                final_text = res
                break
            
            logging.warning(f"Test failed on {server['host']}. Retrying...")
            await asyncio.sleep(1)

        if not final_text:
            final_text = _(
                "iperf_all_attempts_failed",
                lang,
                attempts=MAX_TEST_ATTEMPTS)

        try:
            await message.bot.edit_message_text(final_text, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML")
        except TelegramBadRequest:
            logging.warning("Speedtest finished, but message was deleted.")

    except Exception as e:
        logging.error(f"Speedtest fatal: {e}", exc_info=True)
        try:
            await message.bot.edit_message_text(_("speedtest_fail", lang, error=str(e)), chat_id=message.chat.id, message_id=msg.message_id)
        except TelegramBadRequest: pass