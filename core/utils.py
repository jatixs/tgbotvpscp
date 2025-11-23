import os
import json
import logging
import re
import asyncio
import urllib.parse
import time
import aiohttp
from datetime import datetime
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from . import config
from . import shared_state
from .i18n import get_text, get_user_lang
from .config import INSTALL_MODE, DEPLOY_MODE
from .config import ALERTS_CONFIG_FILE, REBOOT_FLAG_FILE, RESTART_FLAG_FILE


def get_host_path(path: str) -> str:
    """Корректирует путь к файлу хоста, если бот запущен в режиме docker-root."""
    if DEPLOY_MODE == "docker" and INSTALL_MODE == "root":
        if not path.startswith('/'):
            path = '/' + path
        host_path = f"/host{path}"
        if os.path.exists(host_path):
            return host_path
        elif os.path.exists(path):
            return path
        else:
            return host_path
    return path


def load_alerts_config():
    """Загружает ALERTS_CONFIG в shared_state"""
    try:
        if os.path.exists(ALERTS_CONFIG_FILE):
            with open(ALERTS_CONFIG_FILE, "r", encoding='utf-8') as f:
                loaded_data = json.load(f)
                loaded_data_int_keys = {
                    int(k): v for k, v in loaded_data.items()}
                shared_state.ALERTS_CONFIG.clear()
                shared_state.ALERTS_CONFIG.update(loaded_data_int_keys)
            logging.info("Настройки уведомлений загружены.")
        else:
            shared_state.ALERTS_CONFIG.clear()
            logging.info(
                "Файл настроек уведомлений не найден, используется пустой конфиг.")
    except Exception as e:
        logging.error(f"Ошибка загрузки alerts_config.json: {e}")
        shared_state.ALERTS_CONFIG.clear()


def save_alerts_config():
    """Сохраняет ALERTS_CONFIG из shared_state"""
    try:
        os.makedirs(os.path.dirname(ALERTS_CONFIG_FILE), exist_ok=True)
        config_to_save = {
            str(k): v for k,
            v in shared_state.ALERTS_CONFIG.items()}
        with open(ALERTS_CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump(config_to_save, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Ошибка сохранения alerts_config.json: {e}")


async def get_country_flag(ip_or_code: str) -> str:
    """Асинхронно получает флаг страны по IP или коду."""
    if not ip_or_code or ip_or_code in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"

    input_str = ip_or_code.strip().upper()
    if len(input_str) == 2 and input_str.isalpha():
        return "".join(chr(ord(char) - 65 + 0x1F1E6) for char in input_str)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{ip_or_code}?fields=countryCode,status", timeout=2) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        country_code = data.get("countryCode")
                        if country_code and len(country_code) == 2:
                            return "".join(chr(ord(char.upper()) - 65 + 0x1F1E6)
                                           for char in country_code)
    except Exception as e:
        logging.warning(f"Error getting flag for {ip_or_code}: {e}")

    return "❓"


async def get_country_details(ip_or_code: str):
    """Асинхронно получает флаг и название страны."""
    flag = await get_country_flag(ip_or_code)
    country_name = None
    identifier = ip_or_code.strip().upper()

    if not identifier or identifier in ["localhost", "127.0.0.1", "::1"]:
        return "🏠", None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{identifier}?fields=country,status", timeout=2) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        country_name = data.get("country")
    except Exception as e:
        logging.warning(f"Error getting country details for {identifier}: {e}")

    return flag, country_name


def escape_html(text):
    if text is None:
        return ""
    text = str(text)
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def convert_json_to_vless(json_data, custom_name):
    try:
        config_data = json.loads(json_data)
        outbounds = config_data.get('outbounds')
        if not outbounds:
            raise ValueError("No outbounds")
        outbound = next(
            (ob for ob in outbounds if ob.get('protocol') == 'vless'), None)
        if not outbound:
            raise ValueError("No vless outbound")
        settings = outbound.get('settings')
        vnext = settings.get('vnext')
        if not vnext:
            raise ValueError("No vnext")
        server_info = vnext[0]
        user = server_info.get('users')[0]
        stream_settings = outbound.get('streamSettings')
        reality_settings = stream_settings.get('realitySettings')

        uuid = user['id']
        address = server_info['address']
        port = server_info['port']
        host = reality_settings['serverName']
        pbk = reality_settings['publicKey']
        sid = reality_settings['shortId']
        net_type = stream_settings['network']

        params = {
            "security": 'reality',
            "pbk": pbk,
            "host": host,
            "sni": host,
            "sid": sid,
            "type": net_type,
        }
        if 'flow' in user:
            params["flow"] = user['flow']
        if 'fingerprint' in reality_settings:
            params["fp"] = reality_settings['fingerprint']

        base = f"vless://{uuid}@{address}:{port}"
        encoded_params = urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote)
        encoded_name = urllib.parse.quote(custom_name)
        return f"{base}?{encoded_params}#{encoded_name}"
    except Exception as e:
        logging.error(f"VLESS convert error: {e}")
        return f"Error: {e}"


def format_traffic(bytes_value, lang: str):
    units = [
        get_text(
            "unit_bytes", lang), get_text(
            "unit_kb", lang), get_text(
                "unit_mb", lang), get_text(
                    "unit_gb", lang), get_text(
                        "unit_tb", lang)]
    try:
        value = float(bytes_value)
    except (ValueError, TypeError):
        return f"0 {units[0]}"

    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"


def format_uptime(seconds, lang: str):
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return f"0{get_text('unit_second_short', lang)}"

    days = seconds // (24 * 3600)
    seconds %= (24 * 3600)
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60

    day_unit = get_text("unit_day_short", lang)
    hour_unit = get_text("unit_hour_short", lang)
    min_unit = get_text("unit_minute_short", lang)

    parts = []
    if days > 0:
        parts.append(f"{days}{day_unit}")
    if hours > 0:
        parts.append(f"{hours}{hour_unit}")
    parts.append(f"{minutes}{min_unit}")
    return " ".join(parts)


def get_server_timezone_label():
    try:
        is_dst = time.daylight and time.localtime().tm_isdst > 0
        offset_seconds = -time.altzone if is_dst else -time.timezone
        offset_hours = offset_seconds // 3600
        return f" (GMT{'+' if offset_hours >= 0 else ''}{offset_hours})"
    except BaseException:
        return ""


async def detect_xray_client():
    try:
        proc = await asyncio.create_subprocess_shell("docker ps --format '{{.Names}} {{.Image}}'", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()
        if not output:
            return None, None

        for line in output.split('\n'):
            parts = line.split()
            if len(parts) >= 2:
                name, image = parts[0], parts[1]
                if 'amnezia' in image.lower() or name == 'amnezia-xray':
                    return "amnezia", name
                if 'marzban' in image.lower() or 'marzban' in name:
                    return "marzban", name
        return None, None
    except BaseException:
        return None, None


async def initial_restart_check(bot: Bot):
    if os.path.exists(RESTART_FLAG_FILE):
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
            if ':' in content:
                cid, mid = content.split(':', 1)
                await bot.edit_message_text(chat_id=int(cid), message_id=int(mid), text=get_text("utils_bot_restarted", get_user_lang(int(cid))))
        except Exception as e:
            logging.error(f"Restart check error: {e}")
        finally:
            if os.path.exists(RESTART_FLAG_FILE):
                os.remove(RESTART_FLAG_FILE)


async def initial_reboot_check(bot: Bot):
    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                uid = int(f.read().strip())
            await bot.send_message(chat_id=uid, text=get_text("utils_server_rebooted", get_user_lang(uid)), parse_mode="HTML")
        except Exception as e:
            logging.error(f"Reboot check error: {e}")
        finally:
            if os.path.exists(REBOOT_FLAG_FILE):
                os.remove(REBOOT_FLAG_FILE)
