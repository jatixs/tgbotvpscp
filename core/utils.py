# /opt-tg-bot/core/utils.py
import os
import json
import logging
import requests
import re
import asyncio
import urllib.parse
import time
from datetime import datetime
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

# --- Импортируем i18n и config ---
from . import config
from .i18n import get_text, get_user_lang
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
    except json.JSONDecodeError as e:
        logging.error(f"Ошибка JSON при загрузке alerts_config.json: {e}")
        ALERTS_CONFIG = {}
    except Exception as e:
        logging.error(f"Ошибка загрузки alerts_config.json: {e}", exc_info=True)
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
        logging.error(f"Ошибка сохранения alerts_config.json: {e}", exc_info=True)


def get_country_flag(ip: str) -> str:
    """Получает флаг страны по IP, обрабатывая различные ошибки."""
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"
    try:
        response = requests.get(
            f"http://ip-api.com/json/{ip}?fields=countryCode,status", # Добавил status для проверки
            timeout=2)
        response.raise_for_status() # Проверяем на HTTP ошибки (4xx, 5xx)
        data = response.json()

        if data.get("status") != "success":
            logging.warning(f"API ip-api.com вернул статус '{data.get('status')}' для IP {ip}")
            return "❓"

        country_code = data.get("countryCode")
        if country_code:
            if len(country_code) == 2 and country_code.isalpha():
                # Преобразуем AA -> 🇦🇦 (Regional Indicator Symbol Letter)
                # Кодовые точки для A-Z: 0x1F1E6 - 0x1F1FF
                # Смещение относительно ASCII 'A' (65)
                flag = "".join(chr(ord(char.upper()) - 65 + 0x1F1E6) for char in country_code)
                return flag
            else:
                logging.warning(
                    f"Некорректный countryCode '{country_code}' для IP {ip}")
                return "❓"
        else:
            # Этого не должно произойти, если status == 'success', но на всякий
            # случай
            logging.debug(
                f"Не удалось получить countryCode для IP {ip}, хотя статус success. Ответ: {data}")
            return "❓"

    except requests.exceptions.Timeout:
        logging.warning(f"Тайм-аут при получении флага для IP {ip}")
        return "⏳"
    except requests.exceptions.HTTPError as e:
        # Логируем HTTP ошибки отдельно
        logging.warning(f"HTTP ошибка {e.response.status_code} при запросе флага для IP {ip}: {e}")
        return "❓"
    except requests.exceptions.RequestException as e:
        # Остальные ошибки сети (DNS, ConnectionError и т.д.)
        logging.warning(f"Ошибка сети при получении флага для IP {ip}: {e}")
        return "❓"
    except json.JSONDecodeError as e:
        # Ошибка разбора JSON ответа
        logging.warning(f"Ошибка разбора JSON ответа от ip-api.com для IP {ip}: {e}")
        return "❓"
    except Exception as e:
        # Ловим все остальные неожиданные ошибки и логируем с трейсбеком
        logging.exception(f"Неожиданная ошибка в get_country_flag для IP {ip}: {e}")
        return "❓"


def escape_html(text):
    if text is None:
        return ""
    text = str(text)
    # Заменяем только основные символы, необходимые для HTML в Telegram
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    # Убрал замену ", т.к. она обычно не нужна для Telegram HTML


def convert_json_to_vless(json_data, custom_name):
    try:
        config_data = json.loads(json_data)
        outbounds = config_data.get('outbounds')
        if not outbounds or not isinstance(outbounds, list):
            raise ValueError("Invalid config: 'outbounds' array is missing or invalid.")

        # Ищем первый outbound типа 'vless'
        outbound = next((ob for ob in outbounds if ob.get('protocol') == 'vless'), None)
        if not outbound:
             raise ValueError("Invalid config: No 'vless' outbound found.")

        settings = outbound.get('settings')
        vnext = settings.get('vnext') if settings else None
        if not vnext or not isinstance(vnext, list):
            raise ValueError("Invalid config: 'vnext' array is missing or invalid in vless settings.")

        server_info = vnext[0] # Берем первый сервер
        users = server_info.get('users')
        if not users or not isinstance(users, list):
            raise ValueError("Invalid config: 'users' array is missing or invalid in vnext settings.")
        user = users[0] # Берем первого пользователя

        stream_settings = outbound.get('streamSettings')
        if not stream_settings:
             raise ValueError("Invalid config: 'streamSettings' are missing.")

        reality_settings = stream_settings.get('realitySettings')
        if stream_settings.get('security') != 'reality' or not reality_settings:
            raise ValueError("Invalid config: 'realitySettings' are missing or security is not 'reality'.")

        # Проверка наличия обязательных полей (можно добавить больше проверок)
        required_vnext = ['address', 'port']
        required_user = ['id'] # Flow и encryption могут быть опциональны в некоторых клиентах
        required_reality = ['serverName', 'publicKey', 'shortId'] # fingerprint опционален
        required_stream = ['network']

        for key in required_vnext:
            if key not in server_info: raise ValueError(f"Missing '{key}' in vnext server settings.")
        for key in required_user:
            if key not in user: raise ValueError(f"Missing '{key}' in user settings.")
        for key in required_reality:
            if key not in reality_settings: raise ValueError(f"Missing '{key}' in realitySettings.")
        for key in required_stream:
            if key not in stream_settings: raise ValueError(f"Missing '{key}' in streamSettings.")

        # Формирование URL
        uuid = user['id']
        address = server_info['address']
        port = server_info['port']
        host = reality_settings['serverName'] # Используем serverName как host
        pbk = reality_settings['publicKey']
        sid = reality_settings['shortId']
        net_type = stream_settings['network']
        security = 'reality'
        # Добавляем опциональные параметры с проверкой
        params = {
            "security": security,
            "pbk": pbk,
            "host": host, # Используем host вместо sni, как требуют некоторые клиенты
            "sni": reality_settings.get('serverName'), # Добавляем sni отдельно
            "sid": sid,
            "type": net_type,
        }
        if 'flow' in user: params["flow"] = user['flow']
        if 'fingerprint' in reality_settings: params["fp"] = reality_settings['fingerprint']
        # headerType=none обычно подразумевается, если type не http

        base = f"vless://{uuid}@{address}:{port}"
        encoded_params = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        encoded_name = urllib.parse.quote(custom_name)

        vless_url = f"{base}?{encoded_params}#{encoded_name}"
        return vless_url

    except json.JSONDecodeError as e:
        logging.error(f"Ошибка декодирования JSON в VLESS: {e}")
        return get_text("utils_vless_error", config.DEFAULT_LANGUAGE, error=f"JSON Decode Error: {e}")
    except (KeyError, IndexError, TypeError, ValueError, StopIteration) as e:
        logging.error(f"Ошибка структуры или отсутствия ключа в VLESS JSON: {e}")
        return get_text("utils_vless_error", config.DEFAULT_LANGUAGE, error=f"Invalid config structure: {e}")
    except Exception as e:
        logging.exception(f"Неожиданная ошибка при генерации VLESS-ссылки: {e}") # Используем exception
        return get_text("utils_vless_error", config.DEFAULT_LANGUAGE, error=str(e))


def format_traffic(bytes_value, lang: str):
    units = [
        get_text("unit_bytes", lang), get_text("unit_kb", lang), get_text("unit_mb", lang),
        get_text("unit_gb", lang), get_text("unit_tb", lang), get_text("unit_pb", lang)
    ]
    try:
        value = float(bytes_value)
    except (ValueError, TypeError):
        logging.warning(f"Неверное значение для format_traffic: {bytes_value}")
        return f"0 {units[0]}"

    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    # Использовать f-string для форматирования
    return f"{value:.2f} {units[unit_index]}"


def format_uptime(seconds, lang: str):
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        logging.warning(f"Неверное значение для format_uptime: {seconds}")
        return f"0{get_text('unit_second_short', lang)}"

    if seconds < 0:
         logging.warning(f"Отрицательное значение для format_uptime: {seconds}")
         seconds = 0

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
    if years > 0: parts.append(f"{years}{year_unit}")
    if days > 0: parts.append(f"{days}{day_unit}")
    if hours > 0: parts.append(f"{hours}{hour_unit}")
    if mins > 0: parts.append(f"{mins}{min_unit}")
    # Показываем секунды, если аптайм меньше минуты или если другие части пусты
    if seconds < 60 or not parts:
        parts.append(f"{secs}{sec_unit}")

    return " ".join(parts)


def get_server_timezone_label():
    """Возвращает метку часового пояса сервера (например, ' (GMT+3)' или ' (MSK)')."""
    try:
        # Пробуем получить смещение UTC
        # time.timezone дает смещение в секундах ЗАПАДНЕЕ UTC (противоположный знак)
        # time.altzone используется для летнего времени, если применимо
        is_dst = time.daylight and time.localtime().tm_isdst > 0
        offset_seconds = -time.altzone if is_dst else -time.timezone
        offset_hours = offset_seconds // 3600
        offset_minutes = abs(offset_seconds % 3600) // 60

        sign = "+" if offset_hours >= 0 else "" # Знак добавляется автоматически для отрицательных
        # Форматируем строку смещения
        if offset_minutes == 0:
            offset_str = f"GMT{sign}{offset_hours}"
        else:
            offset_str = f"GMT{sign}{offset_hours}:{offset_minutes:02}" # Добавляем минуты с нулем

        # Пробуем получить имя зоны (может не работать на некоторых системах)
        try:
            zone_name = time.tzname[1 if is_dst else 0]
            # Возвращаем имя зоны, если оно не пустое и не равно строке смещения
            if zone_name and zone_name != offset_str:
                 return f" ({zone_name})"
        except Exception:
            pass # Игнорируем ошибки получения имени зоны

        # Если имя зоны недоступно или совпадает со смещением, возвращаем смещение
        return f" ({offset_str})"

    except Exception as e:
        logging.warning(f"Ошибка при получении метки часового пояса: {e}")
        return ""


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

        for line in containers:
            if not line: continue
            try:
                # Используем более надежный способ разделения, учитывая возможные пробелы в образах
                parts = line.strip().split(maxsplit=1)
                if len(parts) != 2: continue
                name, image = parts
                image_lower = image.lower()

                # 1. Проверка Amnezia
                # Сначала по имени (более точное совпадение)
                if name == 'amnezia-xray':
                    logging.info(f"Обнаружен Amnezia (контейнер по имени: {name}, образ: {image})")
                    return "amnezia", name
                # Потом по образу (исключая awg)
                if 'amnezia' in image_lower and 'xray' in image_lower and 'awg' not in image_lower and 'wireguard' not in image_lower:
                     logging.info(f"Обнаружен Amnezia (контейнер по образу: {name}, образ: {image})")
                     return "amnezia", name

                # 2. Проверка Marzban
                if 'ghcr.io/gozargah/marzban:' in image_lower or name.startswith('marzban-'):
                    logging.info(f"Обнаружен Marzban (контейнер: {name}, образ: {image})")
                    return "marzban", name

            except Exception as e:
                # Логируем ошибку парсинга конкретной строки, но продолжаем цикл
                logging.warning(f"Ошибка разбора строки docker ps: '{line}'. Ошибка: {e}")
                continue

        logging.warning("Не удалось определить поддерживаемый Xray (Marzban, Amnezia).")
        return None, None
    except FileNotFoundError:
        logging.error("Команда 'docker' не найдена. Убедитесь, что Docker установлен.")
        raise Exception(get_text("utils_docker_ps_error", config.DEFAULT_LANGUAGE, error="Command 'docker' not found."))
    except Exception as e:
        # Используем logging.exception для автоматического добавления трейсбека
        logging.exception(f"Неожиданная ошибка при выполнении 'docker ps': {e}")
        raise Exception(get_text("utils_docker_ps_error", config.DEFAULT_LANGUAGE, error=escape_html(str(e))))


async def initial_restart_check(bot: Bot):
    if os.path.exists(RESTART_FLAG_FILE):
        logging.info(f"Обнаружен флаг перезапуска: {RESTART_FLAG_FILE}")
        chat_id = None
        message_id = None
        content = "N/A"
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
                if ':' not in content:
                    raise ValueError("Invalid content in restart flag file (missing colon).")
                chat_id_str, message_id_str = content.split(':', 1)
                chat_id = int(chat_id_str)
                message_id = int(message_id_str)

            lang = get_user_lang(chat_id) # Получаем язык пользователя
            text_to_send = get_text("utils_bot_restarted", lang) # Используем язык
            # Используем edit_message_text для изменения существующего сообщения
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text_to_send)
            logging.info(f"Успешно изменено сообщение о перезапуске в чате ID: {chat_id}, сообщение ID: {message_id}")

        except FileNotFoundError:
            logging.info("Restart flag file disappeared before processing.")
        except (ValueError, TypeError) as ve: # Объединяем обработку ошибок
            logging.error(f"Неверный контент в файле флага перезапуска ('{content}'): {ve}")
        except TelegramBadRequest as e:
            # Обрабатываем случай, если сообщение было удалено
            if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                 logging.warning(f"Не удалось изменить сообщение о перезапуске ({chat_id}:{message_id}, вероятно удалено или невалидно): {e}")
            else:
                 logging.error(f"Ошибка Telegram API при изменении сообщения о перезапуске: {e}")
        except Exception as e:
            logging.exception(f"Неожиданная ошибка при обработке флага перезапуска: {e}") # Используем exception
        finally:
            try:
                os.remove(RESTART_FLAG_FILE)
                logging.info(f"Файл флага перезапуска удален: {RESTART_FLAG_FILE}")
            except OSError as e:
                # Игнорируем ошибку "No such file or directory", если файл уже удален
                if e.errno != 2: # errno.ENOENT
                    logging.error(f"Ошибка удаления файла флага перезапуска: {e}")


async def initial_reboot_check(bot: Bot):
    if os.path.exists(REBOOT_FLAG_FILE):
        logging.info(f"Обнаружен флаг перезагрузки: {REBOOT_FLAG_FILE}")
        user_id = None
        user_id_str = "N/A"
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                user_id_str = f.read().strip()
                if not user_id_str.isdigit():
                    raise ValueError("Invalid content in reboot flag file (not a digit).")
                user_id = int(user_id_str)

            lang = get_user_lang(user_id) # Получаем язык
            text_to_send = get_text("utils_server_rebooted", lang) # Используем язык
            # Отправляем новое сообщение, так как после перезагрузки старых нет
            await bot.send_message(chat_id=user_id, text=text_to_send, parse_mode="HTML")
            logging.info(f"Успешно отправлено уведомление о перезагрузке пользователю ID: {user_id}")
        except FileNotFoundError:
            logging.info("Reboot flag file disappeared before processing.")
        except (ValueError, TypeError) as ve: # Объединяем
            logging.error(f"Ошибка обработки контента файла флага перезагрузки ('{user_id_str}'): {ve}")
        except TelegramBadRequest as e:
            # Обрабатываем случай, если пользователь заблокировал бота или чат не найден
            if "chat not found" in str(e).lower() or "bot was blocked by the user" in str(e).lower():
                 logging.warning(f"Не удалось отправить уведомление о перезагрузке пользователю {user_id_str}: {e}")
            else:
                 logging.error(f"Ошибка Telegram API при отправке уведомления о перезагрузке: {e}")
        except Exception as e:
            logging.exception(f"Неожиданная ошибка при обработке флага перезагрузки: {e}") # Используем exception
        finally:
            try:
                os.remove(REBOOT_FLAG_FILE)
                logging.info(f"Файл флага перезагрузки удален: {REBOOT_FLAG_FILE}")
            except OSError as e:
                if e.errno != 2: # errno.ENOENT
                    logging.error(f"Ошибка удаления файла флага перезагрузки: {e}")
