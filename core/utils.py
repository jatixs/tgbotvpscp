# /opt/tg-bot/core/utils.py
import os
import time
import json
import logging
import requests
import re
import asyncio
import urllib.parse
from datetime import datetime
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from .config import (
    ALERTS_CONFIG_FILE, REBOOT_FLAG_FILE, RESTART_FLAG_FILE
)
from .shared_state import ALERTS_CONFIG

def load_alerts_config():
    """Загружает ALERTS_CONFIG из shared_state"""
    global ALERTS_CONFIG
    try:
        if os.path.exists(ALERTS_CONFIG_FILE):
            with open(ALERTS_CONFIG_FILE, "r", encoding='utf-8') as f:
                ALERTS_CONFIG = json.load(f)
                ALERTS_CONFIG = {int(k): v for k, v in ALERTS_CONFIG.items()}
            logging.info("Настройки уведомлений загружены.")
        else:
            ALERTS_CONFIG = {}
            logging.info("Файл настроек уведомлений не найден, используется пустой конфиг.")
    except Exception as e:
        logging.error(f"Ошибка загрузки alerts_config.json: {e}")
        ALERTS_CONFIG = {}

def save_alerts_config():
    """Сохраняет ALERTS_CONFIG из shared_state"""
    try:
        os.makedirs(os.path.dirname(ALERTS_CONFIG_FILE), exist_ok=True)
        with open(ALERTS_CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump({str(k): v for k, v in ALERTS_CONFIG.items()}, f, indent=4, ensure_ascii=False)
        logging.info("Настройки уведомлений сохранены.")
    except Exception as e:
        logging.error(f"Ошибка сохранения alerts_config.json: {e}")

def get_country_flag(ip: str) -> str:
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=2)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get("countryCode")
            if country_code:
                flag = "".join(chr(ord(char) + 127397) for char in country_code.upper())
                return flag
    except requests.exceptions.RequestException as e:
        logging.warning(f"Ошибка при получении флага для IP {ip}: {e}")
        return "❓"
    return "🌍"

def escape_html(text):
    if text is None:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def convert_json_to_vless(json_data, custom_name):
    try:
        config = json.loads(json_data)
        outbound = config['outbounds'][0]
        vnext = outbound['settings']['vnext'][0]
        user = vnext['users'][0]
        reality = outbound['streamSettings']['realitySettings']
        vless_params = {
            'id': user['id'],
            'address': vnext['address'],
            'port': vnext['port'],
            'security': outbound['streamSettings']['security'],
            'host': reality['serverName'],
            'fp': reality['fingerprint'],
            'pbk': reality['publicKey'],
            'sid': reality['shortId'],
            'type': outbound['streamSettings']['network'],
            'flow': user['flow'],
            'encryption': user['encryption'],
            'headerType': 'none'
        }
        vless_url = (f"vless://{vless_params['id']}@{vless_params['address']}:{vless_params['port']}"
                     f"?security={vless_params['security']}"
                     f"&encryption={vless_params['encryption']}"
                     f"&pbk={urllib.parse.quote(vless_params['pbk'])}"
                     f"&host={urllib.parse.quote(vless_params['host'])}"
                     f"&headerType={vless_params['headerType']}"
                     f"&fp={vless_params['fp']}"
                     f"&type={vless_params['type']}"
                     f"&flow={vless_params['flow']}"
                     f"&sid={vless_params['sid']}"
                     f"#{urllib.parse.quote(custom_name)}")
        return vless_url
    except Exception as e:
        logging.error(f"Ошибка при генерации VLESS-ссылки: {e}")
        return f"⚠️ Ошибка при генерации VLESS-ссылки: {str(e)}"

def format_traffic(bytes_value):
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"]
    value = float(bytes_value)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"

def format_uptime(seconds):
    seconds = int(seconds)
    years = seconds // (365 * 24 * 3600)
    remaining = seconds % (365 * 24 * 3600)
    days = remaining // (24 * 3600)
    remaining %= (24 * 3600)
    hours = remaining // 3600
    remaining %= 3600
    mins = remaining // 60
    secs = remaining % 60
    parts = []
    if years > 0:
        parts.append(f"{years}г")
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0:
        parts.append(f"{hours}ч")
    if mins > 0:
        parts.append(f"{mins}м")
    if seconds < 60 or not parts:
       parts.append(f"{secs}с")
    return " ".join(parts) if parts else "0с"

def get_server_timezone_label():
    try:
        offset_str = time.strftime("%z")
        if not offset_str or len(offset_str) != 5:
            return ""

        sign = offset_str[0]
        hours_str = offset_str[1:3]
        mins_str = offset_str[3:5]

        hours_int = int(hours_str)

        if mins_str == "00":
            return f" (GMT{sign}{hours_int})"
        else:
            return f" (GMT{sign}{hours_int}:{mins_str})"
    except Exception:
        return ""

async def detect_xray_client():
    cmd = "docker ps --format '{{.Names}} {{.Image}}'"
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logging.error(f"Ошибка выполнения 'docker ps': {stderr.decode()}")
        raise Exception(f"Не удалось выполнить 'docker ps'. Убедитесь, что Docker установлен и запущен, и у бота есть права.\n<pre>{stderr.decode()}</pre>")

    containers = stdout.decode().strip().split('\n')
    if not containers:
        logging.warning("detect_xray_client: 'docker ps' не вернул контейнеров.")
        return None, None

    # Поиск Amnezia
    for line in containers:
        if not line: continue
        try:
            name, image = line.split(' ', 1)
            if 'amnezia' in image.lower() and 'xray' in image.lower():
                logging.info(f"Обнаружен Amnezia (контейнер: {name}, образ: {image})")
                return "amnezia", name
        except ValueError: continue

    # Поиск Marzban
    for line in containers:
        if not line: continue
        try:
            name, image = line.split(' ', 1)
            if ('marzban' in image.lower() or 'marzban' in name.lower()) and 'xray' not in name.lower():
                logging.info(f"Обнаружен Marzban (контейнер: {name}, образ: {image})")
                return "marzban", name
        except ValueError: continue

    logging.warning("Не удалось определить поддерживаемый Xray (Marzban, Amnezia).")
    return None, None

async def initial_restart_check(bot: Bot):
    if os.path.exists(RESTART_FLAG_FILE):
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
                chat_id, message_id = map(int, content.split(':'))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="✅ Бот успешно перезапущен.")
            logging.info(f"Изменено сообщение о перезапуске в чате ID: {chat_id}")
        except FileNotFoundError: logging.info("Restart flag file not found on startup.")
        except ValueError: logging.error("Invalid content in restart flag file.")
        except TelegramBadRequest as e: logging.warning(f"Failed to edit restart message (likely deleted or invalid): {e}")
        except Exception as e: logging.error(f"Ошибка при обработке флага перезапуска: {e}")
        finally:
            try: os.remove(RESTART_FLAG_FILE)
            except OSError as e:
                 if e.errno != 2: logging.error(f"Error removing restart flag file: {e}")


async def initial_reboot_check(bot: Bot):
    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                user_id_str = f.read().strip()
                if not user_id_str.isdigit(): raise ValueError("Invalid content in reboot flag file.")
                user_id = int(user_id_str)
            await bot.send_message(chat_id=user_id, text="✅ <b>Сервер успешно перезагружен! Бот снова в сети.</b>", parse_mode="HTML")
            logging.info(f"Отправлено уведомление о перезагрузке пользователю ID: {user_id}")
        except FileNotFoundError: logging.info("Reboot flag file not found on startup.")
        except ValueError as ve: logging.error(f"Error processing reboot flag file content: {ve}")
        except TelegramBadRequest as e: logging.warning(f"Failed to send reboot notification to user {user_id_str}: {e}")
        except Exception as e: logging.error(f"Ошибка при обработке флага перезагрузки: {e}")
        finally:
             try: os.remove(REBOOT_FLAG_FILE)
             except OSError as e:
                  if e.errno != 2: logging.error(f"Error removing reboot flag file: {e}")