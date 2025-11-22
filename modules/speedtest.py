import asyncio
import re
import logging
import json
import platform
import shlex
import requests
import os
import subprocess
import concurrent.futures
import time
from concurrent.futures import ThreadPoolExecutor
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

MAX_SERVERS_TO_PING = 30
PING_COUNT = 3
PING_TIMEOUT_SEC = 2
IPERF_TEST_DURATION = 8
IPERF_PROCESS_TIMEOUT = 30.0
MAX_TEST_ATTEMPTS = 3

# Словарь для хранения времени последнего обновления сообщения (чтобы не спамить API)
MESSAGE_EDIT_THROTTLE = {}
# Минимальный интервал обновления сообщения "на лету" (сек)
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
    """
    Безопасно редактирует сообщение статуса с учетом троттлинга.
    
    :param force: Если True, сообщение будет обновлено немедленно (для финальных статусов или ошибок).
                  Если False, сообщение обновится только если прошло достаточно времени.
    """
    if not message_id:
        logging.warning("edit_status_safe: message_id is None, cannot edit.")
        return message_id

    now = time.time()
    last_update = MESSAGE_EDIT_THROTTLE.get(message_id, 0)

    # Если не форсировано и прошло мало времени - пропускаем обновление
    if not force and (now - last_update < MIN_UPDATE_INTERVAL):
        return message_id

    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML")
        MESSAGE_EDIT_THROTTLE[message_id] = now # Обновляем метку времени
        return message_id
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        elif "message to edit not found" in str(e).lower():
            logging.warning(
                f"edit_status_safe: Message {message_id} not found. Sending new.")
            return None
        else:
            logging.error(
                f"edit_status_safe: Error editing message {message_id}: {e}")
            return None
    except Exception as e:
        logging.error(
            f"edit_status_safe: Unexpected error editing message {message_id}: {e}",
            exc_info=True)
        return None

def get_ping_sync(host: str) -> Optional[float]:
    os_type = platform.system().lower()
    if os_type == "windows":
        cmd = f"ping -n {PING_COUNT} -w {PING_TIMEOUT_SEC * 1000} {host}"
        regex = r"Average = ([\d.]+)ms"
    elif os_type == "linux":
        cmd = f"ping -c {PING_COUNT} -W {PING_TIMEOUT_SEC} {host}"
        regex = r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/"
    else:
        cmd = f"ping -c {PING_COUNT} -t {PING_TIMEOUT_SEC} {host}"
        regex = r"round-trip min/avg/max/stddev = [\d.]+/([\d.]+)/"
    try:
        process = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            timeout=10)
        output = process.stdout
        match = re.search(regex, output)
        if match:
            return float(match.group(1))
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        pass
    except Exception as e:
        logging.error(f"Ошибка пинга {host}: {e}", exc_info=True)
    return None

def get_vps_location_sync() -> Tuple[Optional[str], Optional[str]]:
    ip, country_code = None, None
    try:
        ip_response = requests.get(
            "https://api.ipify.org?format=json", timeout=5)
        ip_response.raise_for_status()
        ip = ip_response.json().get("ip")
        if not ip:
            ip_response = requests.get("https://ipinfo.io/ip", timeout=5)
            ip_response.raise_for_status()
            ip = ip_response.text.strip()
    except requests.RequestException as e:
        logging.warning(f"Не удалось определить IP VPS: {e}")
        return None, None
    if ip:
        try:
            geo_response = requests.get(
                f"http://ip-api.com/json/{ip}?fields=status,countryCode", timeout=5)
            geo_response.raise_for_status()
            data = geo_response.json()
            if data.get("status") == "success":
                country_code = data.get("countryCode")
                logging.info(f"Определен код страны VPS: {country_code}")
            else:
                logging.warning(
                    f"Не удалось получить страну для IP {ip}. Ответ: {data}")
        except requests.RequestException as e:
            logging.warning(f"Ошибка при запросе геолокации для IP {ip}: {e}")
    return ip, country_code

def is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False

def fetch_parse_and_prioritize_servers_sync(
        vps_country_code: Optional[str],
        lang: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    servers_list = []
    error_key = None
    use_ru_list = vps_country_code == 'RU'

    if use_ru_list:
        logging.info(
            f"VPS находится в RU, попытка загрузки российского списка с {RU_SERVER_LIST_URL}...")
        ru_yaml_content = None
        ru_download_error = None
        try:
            response_ru = requests.get(RU_SERVER_LIST_URL, timeout=10)
            response_ru.raise_for_status()
            ru_yaml_content = response_ru.text
            try:
                os.makedirs(
                    os.path.dirname(LOCAL_RU_CACHE_FILE),
                    exist_ok=True)
                with open(LOCAL_RU_CACHE_FILE, "w", encoding='utf-8') as f:
                    f.write(ru_yaml_content)
                logging.info(
                    f"Свежий российский список сохранен в {LOCAL_RU_CACHE_FILE}")
            except Exception as e:
                logging.error(
                    f"Не удалось сохранить кеш RU: {e}",
                    exc_info=True)
        except requests.RequestException as e:
            ru_download_error = f"Ошибка сети/таймаут RU: {e}"
            logging.warning(f"Ошибка загрузки RU: {ru_download_error}")
        except Exception as e:
            ru_download_error = f"Ошибка RU: {e}"
            logging.error(
                f"Ошибка загрузки RU: {ru_download_error}",
                exc_info=True)

        if ru_yaml_content is None:
            if os.path.exists(LOCAL_RU_CACHE_FILE):
                logging.warning(f"Чтение RU из кеша {LOCAL_RU_CACHE_FILE}...")
                try:
                    with open(LOCAL_RU_CACHE_FILE, "r", encoding='utf-8') as f:
                        ru_yaml_content = f.read()
                    logging.info("Успешно прочитан RU кеш.")
                except Exception as e:
                    logging.error(
                        f"Не удалось прочитать RU кеш: {e}",
                        exc_info=True)
            else:
                logging.error(
                    f"Не удалось скачать RU список ({ru_download_error}) и кеш не найден.")
                error_key = "iperf_fetch_error_ru"

        if ru_yaml_content:
            try:
                ru_servers_data = yaml.safe_load(ru_yaml_content)
                if not isinstance(ru_servers_data, list):
                    raise ValueError("Ожидался список в YAML")
                for s in ru_servers_data:
                    if not isinstance(s, dict):
                        continue
                    host, port_str, city, name = s.get('address'), s.get(
                        'port'), s.get('City'), s.get('Name')
                    if not host or not port_str or not city or not name:
                        continue
                    port = None
                    try:
                        port = int(str(port_str).split('-')[0].strip())
                    except ValueError:
                        continue

                    servers_list.append({
                        "host": host,
                        "port": port,
                        "city": city,
                        "country": "RU",
                        "continent": "EU",
                        "provider": name
                    })
                logging.info(
                    f"Успешно загружено и распарсено {len(servers_list)} российских серверов.")
                return servers_list, None
            except yaml.YAMLError as e:
                logging.error(f"Ошибка разбора RU YAML: {e}")
                error_key = "iperf_parse_error_ru"
                if ru_download_error and os.path.exists(LOCAL_RU_CACHE_FILE):
                    try:
                        os.remove(LOCAL_RU_CACHE_FILE)
                        logging.warning("Поврежденный RU кеш удален.")
                    except OSError as rm_e:
                        logging.error(
                            f"Не удалось удалить поврежденный RU файл кеша {LOCAL_RU_CACHE_FILE}: {rm_e}")
            except Exception as e:
                logging.error(
                    f"Неожиданная ошибка при парсинге RU YAML: {e}",
                    exc_info=True)
                error_key = "iperf_parse_error_ru"

    if not servers_list:
        if use_ru_list:
            logging.warning(
                "Не удалось использовать российский список, переход на основной JSON...")

        servers_json_content, download_error = None, None
        vps_continent = None
        try:
            response = requests.get(SERVER_LIST_URL, timeout=10)
            response.raise_for_status()
            servers_json_content = response.text
            try:
                os.makedirs(os.path.dirname(LOCAL_CACHE_FILE), exist_ok=True)
                with open(LOCAL_CACHE_FILE, "w", encoding='utf-8') as f:
                    f.write(servers_json_content)
                logging.info(
                    f"Свежий JSON список сохранен в {LOCAL_CACHE_FILE}")
            except Exception as e:
                logging.error(
                    f"Не удалось сохранить JSON кеш: {e}",
                    exc_info=True)
        except requests.RequestException as e:
            download_error = f"Ошибка сети/таймаут JSON: {e}"
            logging.warning(f"Ошибка загрузки JSON: {download_error}")
        except Exception as e:
            download_error = f"Ошибка JSON: {e}"
            logging.error(
                f"Ошибка загрузки JSON: {download_error}",
                exc_info=True)

        if servers_json_content is None:
            if os.path.exists(LOCAL_CACHE_FILE):
                logging.warning(f"Чтение JSON из кеша {LOCAL_CACHE_FILE}...")
                try:
                    with open(LOCAL_CACHE_FILE, "r", encoding='utf-8') as f:
                        servers_json_content = f.read()
                    logging.info("Успешно прочитан JSON кеш.")
                except Exception as e:
                    logging.error(
                        f"Не удалось прочитать JSON кеш: {e}",
                        exc_info=True)
                    return [], error_key or "iperf_fetch_error"
            else:
                logging.error(
                    f"Не удалось скачать JSON ({download_error}) и кеш не найден.")
                return [], error_key or "iperf_fetch_error"

        try:
            servers_data = json.loads(servers_json_content)
            if not isinstance(servers_data, list):
                raise ValueError("Ожидался список в JSON")

            if vps_country_code:
                for s in servers_data:
                    if isinstance(s, dict) and s.get(
                            "COUNTRY") == vps_country_code:
                        vps_continent = s.get("CONTINENT")
                        break

            domain_same_country, domain_same_continent, domain_others = [], [], []
            ip_same_country, ip_same_continent, ip_others = [], [], []
            for s in servers_data:
                if not isinstance(s, dict):
                    continue
                host, port_str, s_country, s_continent = s.get(
                    "IP/HOST"), s.get("PORT"), s.get("COUNTRY"), s.get("CONTINENT")
                if not host or not port_str:
                    continue
                port = None
                try:
                    port = int(port_str.split('-')[0].strip()) if isinstance(
                        port_str, str) and '-' in port_str else int(port_str)
                except ValueError:
                    continue

                server_dict = {
                    "host": host, "port": port,
                    "city": s.get("SITE", "N/A"),
                    "country": s_country,
                    "continent": s_continent,
                    "provider": s.get("PROVIDER", "N/A")
                }
                is_ip = is_ip_address(host)
                if vps_country_code and s_country == vps_country_code:
                    (ip_same_country if is_ip else domain_same_country).append(
                        server_dict)
                elif vps_continent and s_continent == vps_continent:
                    (ip_same_continent if is_ip else domain_same_continent).append(
                        server_dict)
                else:
                    (ip_others if is_ip else domain_others).append(server_dict)

            prioritized_list = (
                domain_same_country +
                domain_same_continent +
                domain_others +
                ip_same_country +
                ip_same_continent +
                ip_others)
            logging.info(
                f"Загружено/распарсено и приоритезировано {len(prioritized_list)} JSON серверов.")
            return prioritized_list, None

        except json.JSONDecodeError as e:
            logging.error(f"Ошибка разбора JSON: {e}")
            if download_error and os.path.exists(LOCAL_CACHE_FILE):
                try:
                    os.remove(LOCAL_CACHE_FILE)
                    logging.warning("Поврежденный JSON кеш удален.")
                except OSError as rm_e:
                    logging.error(
                        f"Не удалось удалить поврежденный JSON файл кеша {LOCAL_CACHE_FILE}: {rm_e}")
            return [], error_key or "iperf_fetch_error"
        except ValueError as e:
            logging.error(f"Ошибка структуры JSON: {e}")
            return [], error_key or "iperf_fetch_error"
        except Exception as e:
            logging.error(
                f"Неожиданная ошибка при парсинге/приоритезации JSON: {e}",
                exc_info=True)
            return [], error_key or "iperf_fetch_error"

    return servers_list, None

def find_best_servers_sync(
        servers: list[Dict[str, Any]]) -> List[Tuple[float, Dict[str, Any]]]:
    servers_to_check = servers[:MAX_SERVERS_TO_PING]
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_server = {
            executor.submit(
                get_ping_sync,
                server["host"]): server for server in servers_to_check}
        for future in concurrent.futures.as_completed(future_to_server):
            server = future_to_server[future]
            try:
                ping = future.result()
                if ping is not None:
                    results.append((ping, server))
            except Exception as e:
                logging.warning(
                    f"Ошибка при получении результата пинга для {server['host']}: {e}")
    if not results:
        logging.warning(
            "Не удалось успешно пропинговать ни один сервер из выборки.")
        return []
    results.sort(key=lambda x: x[0])
    logging.info(
        f"Найдено {len(results)} доступных серверов по пингу. Лучший: {results[0][1]['host']} ({results[0][0]:.2f} мс)")
    return results

async def run_iperf_test_async(bot: Bot,
                               chat_id: int,
                               message_id: Optional[int],
                               server: Dict[str,
                                            Any],
                               ping: float,
                               lang: str) -> str:
    """
    Асинхронно запускает тест iperf3, обновляя статус в Telegram.
    Возвращает строку результата или маркер ошибки.
    Использует edit_status_safe с force=False для промежуточных этапов.
    """
    host = server["host"]
    port = str(server["port"])
    duration = str(IPERF_TEST_DURATION)
    logging.info(f"Запуск iperf3 теста на {host}:{port}...")

    status_text_start = _(
        "speedtest_status_testing",
        lang,
        host=escape_html(host),
        ping=f"{ping:.2f}")
    message_id = await edit_status_safe(bot, chat_id, message_id, status_text_start, lang)
    if not message_id:
        return _("error_message_edit_failed", lang)

    cmd_download_args = [
        "iperf3", "-c", host, "-p", port, "-J", "-t", duration, "-R", "-4"]
    cmd_upload_args = [
        "iperf3", "-c", host, "-p", port, "-J", "-t", duration, "-4"]
    results = {"download": 0.0, "upload": 0.0, "ping": ping}
    try:
        status_text_dl = _(
            "speedtest_status_downloading",
            lang,
            host=escape_html(host),
            ping=f"{ping:.2f}")
        # force=False, так как это промежуточное сообщение
        message_id = await edit_status_safe(bot, chat_id, message_id, status_text_dl, lang, force=False)
        if not message_id:
            return _("error_message_edit_failed", lang)

        logging.debug(f"iperf Download: {' '.join(cmd_download_args)}")
        process_down = await asyncio.create_subprocess_exec(*cmd_download_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_down_bytes, stderr_down_bytes = await asyncio.wait_for(process_down.communicate(), timeout=IPERF_PROCESS_TIMEOUT)
        stdout_down = stdout_down_bytes.decode('utf-8', errors='ignore')
        stderr_down = stderr_down_bytes.decode(
            'utf-8', errors='ignore').strip()
        if process_down.returncode == 0 and stdout_down:
            try:
                data_down = json.loads(stdout_down)
                if "error" not in data_down:
                    speed_bps = data_down.get("end", {}).get(
                        "sum_received", {}).get("bits_per_second")
                    if speed_bps is None:
                        raise ValueError(
                            "Ключ 'bits_per_second' не найден (Download)")
                    results["download"] = speed_bps / 1_000_000
                    logging.info(
                        f"Скорость скачивания: {results['download']:.2f} Мбит/с")
                else:
                    raise Exception(
                        f"Ошибка iperf (Download): {data_down['error']}")
            except (json.JSONDecodeError, ValueError) as e:
                logging.error(
                    f"Ошибка JSON (Download) от {host}:{port}: {e}\nОтвет:\n{stdout_down}")
                raise Exception(
                    f"Некорректный/неожиданный JSON ответ (Download)")
        elif process_down.returncode == 1:
            logging.warning(
                f"Ошибка iperf (Download), код: 1 на {host}:{port}. stderr: '{stderr_down}'")
            return "DOWNLOAD_CONNECTION_ERROR_CODE_1"
        elif stderr_down:
            raise Exception(
                f"Ошибка выполнения iperf (Download): {stderr_down}")
        else:
            raise Exception(
                f"Неизвестная ошибка iperf (Download), код: {process_down.returncode}")

        status_text_ul = _(
            "speedtest_status_uploading",
            lang,
            host=escape_html(host),
            ping=f"{ping:.2f}")
        # force=False, так как это промежуточное сообщение
        message_id = await edit_status_safe(bot, chat_id, message_id, status_text_ul, lang, force=False)
        if not message_id:
            return _("error_message_edit_failed", lang)

        logging.debug(f"iperf Upload: {' '.join(cmd_upload_args)}")
        process_up = await asyncio.create_subprocess_exec(*cmd_upload_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_up_bytes, stderr_up_bytes = await asyncio.wait_for(process_up.communicate(), timeout=IPERF_PROCESS_TIMEOUT)
        stdout_up = stdout_up_bytes.decode('utf-8', errors='ignore')
        stderr_up = stderr_up_bytes.decode('utf-8', errors='ignore').strip()
        if process_up.returncode == 0 and stdout_up:
            try:
                data_up = json.loads(stdout_up)
                if "error" not in data_up:
                    speed_bps = data_up.get("end", {}).get(
                        "sum_sent", {}).get("bits_per_second")
                    if speed_bps is None:
                        raise ValueError(
                            "Ключ 'bits_per_second' не найден (Upload)")
                    results["upload"] = speed_bps / 1_000_000
                    logging.info(
                        f"Скорость загрузки: {results['upload']:.2f} Мбит/с")
                else:
                    raise Exception(
                        f"Ошибка iperf (Upload): {data_up['error']}")
            except (json.JSONDecodeError, ValueError) as e:
                logging.error(
                    f"Ошибка JSON (Upload) от {host}:{port}: {e}\nОтвет:\n{stdout_up}")
                raise Exception(
                    f"Некорректный/неожиданный JSON ответ (Upload)")
        elif process_up.returncode == 1:
            logging.warning(
                f"Ошибка iperf (Upload), код: 1 на {host}:{port}. stderr: '{stderr_up}'")
            return "UPLOAD_CONNECTION_ERROR_CODE_1"
        elif stderr_up:
            raise Exception(f"Ошибка выполнения iperf (Upload): {stderr_up}")
        else:
            raise Exception(
                f"Неизвестная ошибка iperf (Upload), код: {process_up.returncode}")

        country_code = server.get('country')
        city_name = server.get('city', 'N/A')
        provider_name = server.get('provider', 'N/A')

        identifier = country_code if country_code else host
        flag, country_name_full = await get_country_details(identifier)
        logging.debug(
            f"get_country_details для '{identifier}' вернул: flag='{flag}', name='{country_name_full}'")

        if country_name_full:
            location_str = f"{country_name_full} {city_name}"
        elif country_code:
            location_str = f"{country_code} {city_name}"
        else:
            location_str = f"{city_name}"

        return _(
            "speedtest_results",
            lang,
            dl=results["download"],
            ul=results["upload"],
            ping=results["ping"],
            flag=flag,
            server=escape_html(location_str),
            provider=escape_html(provider_name)
        )

    except FileNotFoundError:
        logging.error("iperf3 не найден.")
        return _("iperf_not_found", lang)
    except asyncio.TimeoutError:
        logging.warning(
            f"iperf3 тест таймаут ({IPERF_PROCESS_TIMEOUT}с) для {host}")
        return _("iperf_timeout", lang, host=escape_html(host))
    except Exception as e:
        logging.error(
            f"Ошибка iperf3 теста ({host}:{port}): {e}",
            exc_info=False)
        error_message_safe = str(e)
        return _("speedtest_fail", lang, error=escape_html(error_message_safe))

async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "speedtest"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, [command, "access_denied"], chat_id, message.bot)

    status_message = await message.answer(_("speedtest_status_geo", lang), parse_mode="HTML")
    status_message_id = status_message.message_id
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = status_message_id

    final_text = ""
    try:
        vps_ip, vps_country_code = await asyncio.to_thread(get_vps_location_sync)
        if not vps_ip or not vps_country_code:
            logging.warning("Поиск без приоритезации геолокации.")

        fetch_status_key = "speedtest_status_fetch_ru" if vps_country_code == 'RU' else "speedtest_status_fetch"
        status_message_id = await edit_status_safe(message.bot, chat_id, status_message_id, _(fetch_status_key, lang), lang)
        if not status_message_id:
            raise Exception("Не удалось обновить статус 'Загрузка списка'")

        all_servers, fetch_error_key = await asyncio.to_thread(fetch_parse_and_prioritize_servers_sync, vps_country_code, lang)

        if not all_servers:
            final_text = _(fetch_error_key or "iperf_fetch_error", lang)
        else:
            count_to_ping = min(len(all_servers), MAX_SERVERS_TO_PING)
            status_message_id = await edit_status_safe(message.bot, chat_id, status_message_id, _("speedtest_status_ping", lang, count=count_to_ping), lang)
            if not status_message_id:
                raise Exception("Не удалось обновить статус 'Пинг'")

            best_servers_list = await asyncio.to_thread(find_best_servers_sync, all_servers)

            if not best_servers_list:
                final_text = _("iperf_no_servers", lang)
            else:
                test_successful, last_error_text, attempts_made = False, "", 0
                for attempt in range(
                        min(MAX_TEST_ATTEMPTS, len(best_servers_list))):
                    attempts_made += 1
                    best_ping, best_server = best_servers_list[attempt]
                    logging.info(
                        f"Попытка #{attempts_made} теста на сервере: {best_server['host']} ({best_ping:.2f} мс)")

                    test_result = await run_iperf_test_async(message.bot, chat_id, status_message_id, best_server, best_ping, lang)

                    if test_result in [
                        "DOWNLOAD_CONNECTION_ERROR_CODE_1",
                            "UPLOAD_CONNECTION_ERROR_CODE_1"]:
                        error_type = "Download" if test_result == "DOWNLOAD_CONNECTION_ERROR_CODE_1" else "Upload"
                        logging.warning(
                            f"Попытка #{attempts_made}: Ошибка подключения при {error_type} на {best_server['host']}. Пробую следующий сервер.")
                        error_text = _(
                            "iperf_conn_error_generic", lang, host=escape_html(
                                best_server['host']))
                        # При ошибке используем force=True, чтобы пользователь сразу увидел
                        status_message_id = await edit_status_safe(message.bot, chat_id, status_message_id, error_text, lang, force=True)
                        last_error_text = error_text
                        await asyncio.sleep(1)
                        continue

                    is_fail = test_result.startswith(
                        _("speedtest_fail", lang, error="").split(':')[0])
                    is_not_found = test_result == _("iperf_not_found", lang)
                    is_timeout = test_result.startswith(
                        _("iperf_timeout", lang, host="").split('(')[0])
                    is_edit_fail = test_result == _(
                        "error_message_edit_failed", lang)

                    if is_fail or is_not_found or is_timeout or is_edit_fail:
                        logging.warning(
                            f"Попытка #{attempts_made}: Ошибка теста iperf3 на {best_server['host']}: {test_result}")
                        status_message_id = await edit_status_safe(message.bot, chat_id, status_message_id, test_result, lang, force=True)
                        last_error_text = test_result
                        await asyncio.sleep(1)
                        continue
                    else:
                        final_text = test_result
                        test_successful = True
                        logging.info(
                            f"Тест успешен на попытке #{attempts_made}.")
                        break

                if not test_successful:
                    logging.error(
                        f"Тест не удался после {attempts_made} попыток.")
                    final_text = last_error_text if last_error_text else _(
                        "iperf_all_attempts_failed", lang, attempts=attempts_made)

    except Exception as e:
        logging.error(
            f"Критическая ошибка в speedtest_handler: {e}",
            exc_info=True)
        final_text = _("speedtest_fail", lang, error=escape_html(str(e)))

    if status_message_id:
        try:
            # Финальное редактирование всегда без проверок троттлинга (напрямую)
            await message.bot.edit_message_text(final_text, chat_id=chat_id, message_id=status_message_id, parse_mode="HTML")
            LAST_MESSAGE_IDS.setdefault(
                user_id, {})[command] = status_message_id
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                pass
            elif "message to edit not found" in str(e).lower():
                logging.warning(
                    f"Speedtest: Финальное сообщение {status_message_id} не найдено. Отправляю новое.")
                LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
                try:
                    new_msg = await message.answer(final_text, parse_mode="HTML")
                    LAST_MESSAGE_IDS.setdefault(
                        user_id, {})[command] = new_msg.message_id
                except Exception as send_e:
                    logging.error(f"Speedtest: Не отправить новое: {send_e}")
            else:
                logging.error(
                    f"Speedtest: Ошибка финального ред. ({status_message_id}): {e}. Отправляю новое.")
                LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
                try:
                    new_msg = await message.answer(final_text, parse_mode="HTML")
                    LAST_MESSAGE_IDS.setdefault(
                        user_id, {})[command] = new_msg.message_id
                except Exception as send_e:
                    logging.error(f"Speedtest: Не отправить новое: {send_e}")
        except Exception as e:
            logging.error(
                f"Speedtest: Неожиданная ошибка финального ред. ({status_message_id}): {e}. Отправляю новое.")
            LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
            try:
                new_msg = await message.answer(final_text, parse_mode="HTML")
                LAST_MESSAGE_IDS.setdefault(
                    user_id, {})[command] = new_msg.message_id
            except Exception as send_e:
                logging.error(f"Speedtest: Не отправить новое: {send_e}")
    else:
        logging.warning(
            "Speedtest: Не найден ID для финального ред. Отправляю новым.")
        LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
        try:
            new_msg = await message.answer(final_text, parse_mode="HTML")
            LAST_MESSAGE_IDS.setdefault(
                user_id, {})[command] = new_msg.message_id
        except Exception as send_e:
            logging.error(f"Speedtest: Не отправить новое (нет ID): {send_e}")