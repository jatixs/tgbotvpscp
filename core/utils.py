# /opt-tg-bot/core/utils.py
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

# --- Импортируем i18n и config ---
from . import config
from .i18n import get_text, get_user_lang  # Используем get_text
# -----------------------------------------------

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
            logging.info(
                "Файл настроек уведомлений не найден, используется пустой конфиг.")
    except Exception as e:
        logging.error(f"Ошибка загрузки alerts_config.json: {e}")
        ALERTS_CONFIG = {}


def save_alerts_config():
    """Сохраняет ALERTS_CONFIG из shared_state"""
    try:
        os.makedirs(os.path.dirname(ALERTS_CONFIG_FILE), exist_ok=True)
        config_to_save = {str(k): v for k, v in ALERTS_CONFIG.items()}
        with open(ALERTS_CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump(config_to_save, f, indent=4, ensure_ascii=False)
        logging.info("Настройки уведомлений сохранены.")
    except Exception as e:
        logging.error(f"Ошибка сохранения alerts_config.json: {e}")


def get_country_flag(ip: str) -> str:
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"
    try:
        response = requests.get(
            f"http://ip-api.com/json/{ip}?fields=countryCode",
            timeout=2)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get("countryCode")
            if country_code:
                if len(country_code) == 2 and country_code.isalpha():
                    flag = "".join(chr(ord(char) + 127397)
                                   for char in country_code.upper())
                    return flag
                else:
                    logging.warning(
                        f"Некорректный countryCode '{country_code}' для IP {ip}")
                    return "❓"
            else:
                logging.debug(
                    f"Не удалось получить countryCode для IP {ip}. Ответ: {data}")
                return "❓"
        else:
            logging.warning(
                f"Ошибка API ip-api.com ({response.status_code}) для IP {ip}")
            return "❓"
    except requests.exceptions.Timeout:
        logging.warning(f"Тайм-аут при получении флага для IP {ip}")
        return "⏳"
    except requests.exceptions.RequestException as e:
        logging.warning(f"Ошибка сети при получении флага для IP {ip}: {e}")
        return "❓"
    except Exception as e:
        logging.error(
            f"Неожиданная ошибка в get_country_flag для IP {ip}: {e}",
            exc_info=True)
        return "❓"


def escape_html(text):
    if text is None:
        return ""
    text = str(text)
    return text.replace(
        '&',
        '&amp;').replace(
        '<',
        '&lt;').replace(
            '>',
            '&gt;').replace(
                '"',
        '&quot;')


def convert_json_to_vless(json_data, custom_name):
    try:
        config_data = json.loads(json_data)
        if 'outbounds' not in config_data or not isinstance(
                config_data['outbounds'], list) or not config_data['outbounds']:
            raise ValueError(
                "Invalid config: 'outbounds' array is missing or empty.")
        outbound = config_data['outbounds'][0]
        if 'settings' not in outbound or 'vnext' not in outbound['settings'] or not isinstance(
                outbound['settings']['vnext'], list) or not outbound['settings']['vnext']:
            raise ValueError(
                "Invalid config: 'vnext' array is missing or empty in outbound settings.")
        vnext = outbound['settings']['vnext'][0]
        if 'users' not in vnext or not isinstance(
                vnext['users'], list) or not vnext['users']:
            raise ValueError(
                "Invalid config: 'users' array is missing or empty in vnext settings.")
        user = vnext['users'][0]
        if 'streamSettings' not in outbound or 'realitySettings' not in outbound[
                'streamSettings']:
            raise ValueError(
                "Invalid config: 'realitySettings' are missing in streamSettings.")
        reality = outbound['streamSettings']['realitySettings']

        required_vnext = ['address', 'port']
        required_user = ['id', 'flow', 'encryption']
        required_reality = [
            'serverName',
            'fingerprint',
            'publicKey',
            'shortId']
        required_stream = ['security', 'network']

        for key in required_vnext:
            if key not in vnext:
                raise ValueError(f"Missing '{key}' in vnext settings.")
        for key in required_user:
            if key not in user:
                raise ValueError(f"Missing '{key}' in user settings.")
        for key in required_reality:
            if key not in reality:
                raise ValueError(f"Missing '{key}' in realitySettings.")
        for key in required_stream:
            if key not in outbound['streamSettings']:
                raise ValueError(f"Missing '{key}' in streamSettings.")

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
        }
        base = f"vless://{vless_params['id']}@{vless_params['address']}:{vless_params['port']}"
        params = {
            "security": vless_params['security'],
            "encryption": vless_params['encryption'],
            "pbk": vless_params['pbk'],
            "host": vless_params['host'],
            "headerType": "none",
            "fp": vless_params['fp'],
            "type": vless_params['type'],
            "flow": vless_params['flow'],
            "sid": vless_params['sid'],
        }
        encoded_params = urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote)
        encoded_name = urllib.parse.quote(custom_name)

        vless_url = f"{base}?{encoded_params}#{encoded_name}"
        return vless_url
    except json.JSONDecodeError as e:
        logging.error(f"Ошибка декодирования JSON в VLESS: {e}")
        # --- Используем язык по умолчанию для ошибок ---
        return get_text(
            "utils_vless_error",
            config.DEFAULT_LANGUAGE,
            error=f"JSON Decode Error: {e}")
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logging.error(
            f"Ошибка структуры или отсутствия ключа в VLESS JSON: {e}")
        # --- Используем язык по умолчанию для ошибок ---
        return get_text(
            "utils_vless_error",
            config.DEFAULT_LANGUAGE,
            error=f"Invalid config structure: {e}")
    except Exception as e:
        logging.error(
            f"Неожиданная ошибка при генерации VLESS-ссылки: {e}",
            exc_info=True)
        # --- Используем язык по умолчанию для ошибок ---
        return get_text(
            "utils_vless_error",
            config.DEFAULT_LANGUAGE,
            error=str(e))


def format_traffic(bytes_value, lang: str):
    units = [
        get_text(
            "unit_bytes", lang), get_text(
            "unit_kb", lang), get_text(
                "unit_mb", lang), get_text(
                    "unit_gb", lang), get_text(
                        "unit_tb", lang), get_text(
                            "unit_pb", lang)]
    try:
        value = float(bytes_value)
    except (ValueError, TypeError):
        logging.warning(f"Неверное значение для format_traffic: {bytes_value}")
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
        logging.warning(f"Неверное значение для format_uptime: {seconds}")
        return f"0{get_text('unit_second_short', lang)}"

    years = seconds // (365 * 24 * 3600)
    remaining = seconds % (365 * 24 * 3600)
    days = remaining // (24 * 3600)
    remaining %= (24 * 3600)
    hours = remaining // 3600
    remaining %= 3600
    mins = remaining // 60
    secs = remaining % 60

    year_unit = get_text("unit_year_short", lang)
    day_unit = get_text("unit_day_short", lang)
    hour_unit = get_text("unit_hour_short", lang)
    min_unit = get_text("unit_minute_short", lang)
    sec_unit = get_text("unit_second_short", lang)

    parts = []
    if years > 0:
        parts.append(f"{years}{year_unit}")
    if days > 0:
        parts.append(f"{days}{day_unit}")
    if hours > 0:
        parts.append(f"{hours}{hour_unit}")
    if mins > 0:
        parts.append(f"{mins}{min_unit}")
    if seconds < 60 or not parts:
        parts.append(f"{secs}{sec_unit}")
    return " ".join(parts) if parts else f"0{sec_unit}"


def get_server_timezone_label():
    try:
        tz_env = os.environ.get('TZ')
        if tz_env:
            import time
            offset_str = time.strftime("%z")
            if not offset_str or len(offset_str) != 5:
                return f" ({tz_env})"
        else:
            offset_str = time.strftime("%z")

        if not offset_str or len(offset_str) != 5:
            logging.debug("Не удалось определить смещение часового пояса.")
            return ""

        sign = offset_str[0]
        hours_str = offset_str[1:3]
        mins_str = offset_str[3:5]

        if not hours_str.isdigit() or not mins_str.isdigit():
            logging.warning(
                f"Некорректный формат смещения часового пояса: {offset_str}")
            return ""

        hours_int = int(hours_str)

        if mins_str == "00":
            return f" (GMT{sign}{hours_int})"
        else:
            return f" (GMT{sign}{hours_int}:{mins_str})"
    except Exception as e:
        logging.warning(f"Ошибка при получении метки часового пояса: {e}")
        return ""

# --- ИСПРАВЛЕНИЕ: Логика определения Amnezia ---


async def detect_xray_client():
    cmd = "docker ps --format '{{.Names}} {{.Image}}'"
    try:
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode('utf-8', 'ignore').strip()
            logging.error(f"Ошибка выполнения 'docker ps': {error_msg}")
            # --- Используем язык по умолчанию для ошибок ---
            raise Exception(
                get_text(
                    "utils_docker_ps_error",
                    config.DEFAULT_LANGUAGE,
                    error=escape_html(error_msg)))

        containers = stdout.decode('utf-8', 'ignore').strip().split('\n')
        if not containers or containers == ['']:
            logging.warning(
                "detect_xray_client: 'docker ps' не вернул контейнеров.")
            return None, None

        # 1. Сначала ищем по имени 'amnezia-xray'
        for line in containers:
            if not line:
                continue
            try:
                match = re.match(r'^(\S+)\s+(.+)$', line.strip())
                if not match:
                    continue
                name, image = match.groups()
                if name == 'amnezia-xray':
                    logging.info(
                        f"Обнаружен Amnezia (контейнер по имени: {name}, образ: {image})")
                    return "amnezia", name
            except Exception as e:
                logging.warning(
                    f"Ошибка разбора строки docker ps (Amnezia by name): '{line}'. Ошибка: {e}")
                continue

        # 2. Если не нашли по имени, ищем по образу, исключая awg/wireguard
        for line in containers:
            if not line:
                continue
            try:
                match = re.match(r'^(\S+)\s+(.+)$', line.strip())
                if not match:
                    continue
                name, image = match.groups()
                image_lower = image.lower()
                if 'amnezia' in image_lower and 'xray' in image_lower and 'awg' not in image_lower and 'wireguard' not in image_lower:
                    logging.info(
                        f"Обнаружен Amnezia (контейнер по образу: {name}, образ: {image})")
                    return "amnezia", name
            except Exception as e:
                logging.warning(
                    f"Ошибка разбора строки docker ps (Amnezia by image): '{line}'. Ошибка: {e}")
                continue

        # 3. Ищем Marzban
        for line in containers:
            if not line:
                continue
            try:
                match = re.match(r'^(\S+)\s+(.+)$', line.strip())
                if not match:
                    continue
                name, image = match.groups()
                if 'ghcr.io/gozargah/marzban:' in image.lower() or name.startswith('marzban-'):
                    logging.info(
                        f"Обнаружен Marzban (контейнер: {name}, образ: {image})")
                    return "marzban", name
            except Exception as e:
                logging.warning(
                    f"Ошибка разбора строки docker ps (Marzban): '{line}'. Ошибка: {e}")
                continue

        logging.warning(
            "Не удалось определить поддерживаемый Xray (Marzban, Amnezia).")
        return None, None
    except FileNotFoundError:
        logging.error(
            "Команда 'docker' не найдена. Убедитесь, что Docker установлен.")
        # --- Используем язык по умолчанию для ошибок ---
        raise Exception(
            get_text(
                "utils_docker_ps_error",
                config.DEFAULT_LANGUAGE,
                error="Command 'docker' not found."))
    except Exception as e:
        logging.error(
            f"Неожиданная ошибка при выполнении 'docker ps': {e}",
            exc_info=True)
        # --- Используем язык по умолчанию для ошибок ---
        raise Exception(
            get_text(
                "utils_docker_ps_error",
                config.DEFAULT_LANGUAGE,
                error=escape_html(
                    str(e))))
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---


async def initial_restart_check(bot: Bot):
    if os.path.exists(RESTART_FLAG_FILE):
        logging.info(f"Обнаружен флаг перезапуска: {RESTART_FLAG_FILE}")
        chat_id = None
        message_id = None
        content = "N/A"  # Для логгирования
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
                if ':' not in content:
                    raise ValueError(
                        "Invalid content in restart flag file (missing colon).")
                chat_id_str, message_id_str = content.split(':', 1)
                chat_id = int(chat_id_str)
                message_id = int(message_id_str)

            lang = get_user_lang(chat_id)
            text_to_send = get_text("utils_bot_restarted", lang)
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text_to_send)
            logging.info(
                f"Успешно изменено сообщение о перезапуске в чате ID: {chat_id}, сообщение ID: {message_id}")

        except FileNotFoundError:
            logging.info("Restart flag file disappeared before processing.")
        except ValueError as ve:
            logging.error(
                f"Неверный контент в файле флага перезапуска ('{content}'): {ve}")
        except TelegramBadRequest as e:
            logging.warning(
                f"Не удалось изменить сообщение о перезапуске ({chat_id}:{message_id}, likely deleted or invalid): {e}")
        except Exception as e:
            logging.error(
                f"Неожиданная ошибка при обработке флага перезапуска: {e}",
                exc_info=True)
        finally:
            try:
                os.remove(RESTART_FLAG_FILE)
                logging.info(
                    f"Файл флага перезапуска удален: {RESTART_FLAG_FILE}")
            except OSError as e:
                if e.errno != 2:  # Игнорируем ошибку "No such file or directory"
                    logging.error(
                        f"Ошибка удаления файла флага перезапуска: {e}")


async def initial_reboot_check(bot: Bot):
    if os.path.exists(REBOOT_FLAG_FILE):
        logging.info(f"Обнаружен флаг перезагрузки: {REBOOT_FLAG_FILE}")
        user_id = None
        user_id_str = "N/A"
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                user_id_str = f.read().strip()
                if not user_id_str.isdigit():
                    raise ValueError(
                        "Invalid content in reboot flag file (not a digit).")
                user_id = int(user_id_str)

            lang = get_user_lang(user_id)
            text_to_send = get_text("utils_server_rebooted", lang)
            await bot.send_message(chat_id=user_id, text=text_to_send, parse_mode="HTML")
            logging.info(
                f"Успешно отправлено уведомление о перезагрузке пользователю ID: {user_id}")
        except FileNotFoundError:
            logging.info("Reboot flag file disappeared before processing.")
        except ValueError as ve:
            logging.error(
                f"Ошибка обработки контента файла флага перезагрузки ('{user_id_str}'): {ve}")
        except TelegramBadRequest as e:
            logging.warning(
                f"Не удалось отправить уведомление о перезагрузке пользователю {user_id_str}: {e}")
        except Exception as e:
            logging.error(
                f"Неожиданная ошибка при обработке флага перезагрузки: {e}",
                exc_info=True)
        finally:
            try:
                os.remove(REBOOT_FLAG_FILE)
                logging.info(
                    f"Файл флага перезагрузки удален: {REBOOT_FLAG_FILE}")
            except OSError as e:
                if e.errno != 2:  # Игнорируем ошибку "No such file or directory"
                    logging.error(
                        f"Ошибка удаления файла флага перезагрузки: {e}")
