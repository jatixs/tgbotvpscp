# /opt-tg-bot/watchdog.py
import os
import time
import subprocess
import requests
import logging
import logging.handlers
import re
import json
import sys
from datetime import datetime, timedelta
from typing import Optional, Callable  # <-- Добавлено

# --- ДОБАВЛЕНЫ ИМПОРТЫ DOCKER ---
try:
    import docker
    import docker.errors
    from docker.client import DockerClient
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
# ---------------------------------

# Добавляем путь к core
BASE_DIR_WATCHDOG = os.path.dirname(__file__)
CORE_DIR_WATCHDOG = os.path.join(BASE_DIR_WATCHDOG, "core")
if CORE_DIR_WATCHDOG not in sys.path:
    sys.path.insert(0, BASE_DIR_WATCHDOG)

try:
    from core import config
    from core.i18n import get_text
    from core.utils import escape_html
except ImportError as e:
    print(f"FATAL: Could not import core modules: {e}")
    print("Ensure watchdog.py is run from the correct directory (/opt-tg-bot) and venv.")
    sys.exit(1)

# --- Настройки ---
ALERT_BOT_TOKEN = config.TOKEN
ALERT_ADMIN_ID = config.ADMIN_USER_ID
# --- ИЗМЕНЕНО: DEPLOY_MODE ---
DEPLOY_MODE = config.DEPLOY_MODE
# ------------------------------

dotenv_path = os.path.join(BASE_DIR_WATCHDOG, '.env')
env_vars = {}
try:
    with open(dotenv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                env_vars[key.strip()] = value.strip()
except Exception as e:
    print(f"WARNING: Could not read .env file for TG_BOT_NAME: {e}")

BOT_NAME = env_vars.get("TG_BOT_NAME", "VPS Bot")

# --- ИЗМЕНЕНО: Определение имени службы/контейнера ---
if DEPLOY_MODE == "docker":
    BOT_SERVICE_NAME = env_vars.get("TG_BOT_CONTAINER_NAME", "tg-bot-root")
else:  # systemd
    BOT_SERVICE_NAME = "tg-bot.service"
# ----------------------------------------------------

WATCHDOG_SERVICE_NAME = "tg-watchdog.service"  # Используется только в systemd


CONFIG_DIR = config.CONFIG_DIR
RESTART_FLAG_FILE = config.RESTART_FLAG_FILE
BOT_LOG_DIR = config.BOT_LOG_DIR
WATCHDOG_LOG_DIR = config.WATCHDOG_LOG_DIR

CHECK_INTERVAL_SECONDS = 5
ALERT_COOLDOWN_SECONDS = 300

# Настройка логирования для watchdog
config.setup_logging(WATCHDOG_LOG_DIR, "watchdog")

last_alert_times = {}
bot_service_was_down_or_activating = False
status_alert_message_id = None
current_reported_state = None
WD_LANG = config.DEFAULT_LANGUAGE

# --- ДОБАВЛЕНО: Инициализация Docker клиента ---
docker_client: Optional[DockerClient] = None
if DEPLOY_MODE == "docker":
    if DOCKER_AVAILABLE:
        try:
            docker_client = docker.from_env()
            docker_client.ping()
            logging.info("Успешное подключение к Docker API.")
        except docker.errors.DockerException:
            logging.critical(
                "Не удалось подключиться к Docker socket. Убедитесь, что /var/run/docker.sock смонтирован.")
            docker_client = None
        except Exception as e:
            logging.critical(
                f"Неожиданная ошибка при инициализации Docker клиента: {e}")
            docker_client = None
    else:
        logging.critical(
            "Режим Docker, но библиотека 'docker' не установлена! Watchdog не сможет работать.")
# --------------------------------------------


def send_or_edit_telegram_alert(
        message_key: str,
        alert_type: str,
        message_id_to_edit=None,
        **kwargs):
    """Отправляет или редактирует сообщение, используя ключ i18n и WD_LANG."""
    global last_alert_times, status_alert_message_id

    current_time = time.time()
    apply_cooldown = alert_type in [
        "bot_restart_fail",
        "watchdog_config_error",
        "watchdog_error",
        "bot_service_error_on_start"]
    if apply_cooldown and current_time - \
            last_alert_times.get(alert_type, 0) < ALERT_COOLDOWN_SECONDS:
        logging.warning(
            f"Активен кулдаун для '{alert_type}', пропуск уведомления.")
        return message_id_to_edit

    # --- ИСПРАВЛЕНО: Используем WD_LANG для всех i18n-строк ---
    alert_prefix = get_text("watchdog_alert_prefix", WD_LANG)
    if not message_key:
        logging.error(
            f"send_or_edit_telegram_alert вызван с пустым message_key для alert_type '{alert_type}'")
        message_body = get_text("error_internal", WD_LANG)
    else:
        message_body = get_text(message_key, WD_LANG, **kwargs)
    # --------------------------------------------------------
    text_to_send = f"{alert_prefix}\n\n{message_body}"

    message_sent_or_edited = False
    new_message_id = message_id_to_edit

    if message_id_to_edit:
        url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/editMessageText"
        payload = {
            'chat_id': ALERT_ADMIN_ID,
            'message_id': message_id_to_edit,
            'text': text_to_send,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            response_data = {}
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                logging.warning(
                    f"Не удалось декодировать JSON из ответа Telegram (edit): {response.text}")

            if response.status_code == 200:
                logging.info(
                    f"Telegram-сообщение ID {message_id_to_edit} успешно отредактировано (тип '{alert_type}').")
                message_sent_or_edited = True
                if apply_cooldown:
                    last_alert_times[alert_type] = current_time
            elif response.status_code == 400 and "message is not modified" in response_data.get("description", "").lower():
                logging.debug(
                    f"Сообщение ID {message_id_to_edit} не изменено (текст совпадает).")
                message_sent_or_edited = True
            else:
                logging.warning(
                    f"Не удалось отредактировать сообщение ID {message_id_to_edit}. Статус: {response.status_code}, Ответ: {response.text}. Попытка отправить новое.")
                status_alert_message_id = None
                new_message_id = None
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Ошибка сети при редактировании Telegram-сообщения ID {message_id_to_edit}: {e}. Попытка отправить новое.")
            status_alert_message_id = None
            new_message_id = None
        except Exception as e:
            logging.error(
                f"Неожиданное исключение при редактировании Telegram-сообщения ID {message_id_to_edit}: {e}. Попытка отправить новое.")
            status_alert_message_id = None
            new_message_id = None

    if not message_sent_or_edited:
        url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': ALERT_ADMIN_ID,
            'text': text_to_send,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                sent_message_data = response.json()
                new_message_id = sent_message_data.get(
                    'result', {}).get('message_id')
                logging.info(
                    f"Telegram-оповещение '{alert_type}' успешно отправлено (новое сообщение ID {new_message_id}).")
                if apply_cooldown:
                    last_alert_times[alert_type] = current_time
            else:
                logging.error(
                    f"Не удалось отправить Telegram-оповещение '{alert_type}'. Статус: {response.status_code}, Ответ: {response.text}")
                new_message_id = None
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Ошибка сети при отправке Telegram-оповещения '{alert_type}': {e}")
            new_message_id = None
        except Exception as e:
            logging.error(
                f"Неожиданное исключение при отправке Telegram-оповещения '{alert_type}': {e}")
            new_message_id = None

    return new_message_id


def check_bot_log_for_errors():
    """Читает последние 20 строк лога бота и ищет ошибки. Возвращает (key, kwargs)."""
    current_bot_log_file = os.path.join(BOT_LOG_DIR, "bot.log")
    try:
        if not os.path.exists(current_bot_log_file):
            yesterday_str = (
                datetime.now() -
                timedelta(
                    days=1)).strftime("%Y-%m-%d")
            yesterday_log_file = os.path.join(
                BOT_LOG_DIR, f"bot.log.{yesterday_str}")
            if os.path.exists(yesterday_log_file):
                current_bot_log_file = yesterday_log_file
                logging.info(
                    f"Основной лог-файл {os.path.basename(current_bot_log_file)} не найден, проверяю вчерашний: {os.path.basename(yesterday_log_file)}")
            else:
                logging.warning(
                    f"Лог-файл бота {os.path.basename(current_bot_log_file)} (и вчерашний) не найден. Не могу проверить на ошибки.")
                return None, {}

        result = subprocess.run(
            ['tail', '-n', '20', current_bot_log_file],
            capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore'
        )

        if result.returncode != 0:
            logging.error(
                f"Не удалось прочитать {os.path.basename(current_bot_log_file)} через tail: {result.stderr}")
            return "watchdog_log_read_error", {
                "error": result.stderr or "Unknown error"}

        log_content = result.stdout
        log_content_lower = log_content.lower()

        if "critical" in log_content_lower or "error" in log_content_lower:
            last_error_line = ""
            for line in log_content.splitlines():
                if "ERROR" in line or "CRITICAL" in line:
                    last_error_line = line

            if last_error_line:
                last_error_safe = escape_html(last_error_line)
                return "watchdog_log_error_found_details", {
                    "details": f"...{last_error_safe[-150:]}"}

            return "watchdog_log_error_found_generic", {}

        return "OK", {}

    except Exception as e:
        logging.error(
            f"Исключение в check_bot_log_for_errors: {e}",
            exc_info=True)
        error_safe = escape_html(str(e))
        return "watchdog_log_exception", {"error": error_safe}


# --- ФУНКЦИЯ ДЛЯ SYSTEMD ---
def check_bot_service_systemd():
    """Проверяет статус сервиса systemd."""
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state

    actual_state = "unknown"
    status_output_full = "N/A"

    try:
        status_result = subprocess.run(
            ['systemctl', 'status', BOT_SERVICE_NAME],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        )
        status_output_full = status_result.stdout.strip()
        if "Active: active (running)" in status_output_full:
            actual_state = "active"
        elif "Active: activating" in status_output_full:
            actual_state = "activating"

    except subprocess.CalledProcessError as e:
        status_output_full = e.stdout.strip() if e.stdout else e.stderr.strip()
        if "inactive (dead)" in status_output_full:
            actual_state = "inactive"
        elif "failed" in status_output_full:
            actual_state = "failed"
        else:
            logging.error(
                f"Ошибка выполнения systemctl status: {e.stderr or e.stdout}")
            actual_state = "unknown"
            status_output_full = e.stderr or e.stdout

    except FileNotFoundError:
        logging.error(
            "Команда systemctl не найдена. Не могу проверить статус сервиса.")
        if current_reported_state != "systemctl_error":
            send_or_edit_telegram_alert(
                "watchdog_systemctl_not_found",
                "watchdog_config_error",
                None)
            current_reported_state = "systemctl_error"
            status_alert_message_id = None
        time.sleep(CHECK_INTERVAL_SECONDS * 5)
        return  # Возвращаем, т.к. process_service_state вызовет ошибку
    except Exception as e:
        logging.error(
            f"Неожиданная ошибка при вызове systemctl status: {e}",
            exc_info=True)
        if current_reported_state != "check_error":
            error_safe = escape_html(str(e))
            send_or_edit_telegram_alert(
                "watchdog_check_error",
                "watchdog_error",
                None,
                error=error_safe)
            current_reported_state = "check_error"
            status_alert_message_id = None
        time.sleep(CHECK_INTERVAL_SECONDS)
        return  # Возвращаем

    # --- Функция перезапуска для systemd ---
    def restart_service_systemd():
        try:
            subprocess.run(['sudo',
                            'systemctl',
                            'restart',
                            BOT_SERVICE_NAME],
                           capture_output=True,
                           text=True,
                           check=True,
                           encoding='utf-8',
                           errors='ignore')
            logging.info(
                f"Команда перезапуска (systemd) для {BOT_SERVICE_NAME} отправлена успешно.")
        except subprocess.CalledProcessError as e:
            error_msg = escape_html(
                (e.stderr or e.stdout or str(e)).strip())
            logging.error(
                f"Не удалось отправить команду перезапуска (systemd) для {BOT_SERVICE_NAME}. Ошибка: {error_msg}")
            send_or_edit_telegram_alert(
                "watchdog_restart_fail",
                "bot_restart_fail",
                None,
                service_name=BOT_SERVICE_NAME,
                error=error_msg)
        except Exception as e:
            error_msg = escape_html(str(e))
            logging.error(
                f"Неожиданная ошибка при попытке перезапуска (systemd) {BOT_SERVICE_NAME}: {error_msg}")
            send_or_edit_telegram_alert(
                "watchdog_restart_fail",
                "bot_restart_fail",
                None,
                service_name=BOT_SERVICE_NAME,
                error=f"Unexpected error: {error_msg}")

    # --- Вызов общей логики ---
    process_service_state(
        actual_state,
        status_output_full,
        restart_service_systemd)


# --- ФУНКЦИЯ ДЛЯ DOCKER ---
def check_bot_service_docker():
    """Проверяет статус контейнера Docker."""
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state

    if not docker_client:
        logging.error("Docker клиент не инициализирован. Пропуск проверки.")
        time.sleep(CHECK_INTERVAL_SECONDS * 5)
        return

    actual_state = "unknown"
    container_status = "not_found"
    container = None

    try:
        # 1. Получаем контейнер по имени
        container = docker_client.containers.get(BOT_SERVICE_NAME)
        # 'running', 'restarting', 'exited', 'paused'
        container_status = container.status
        logging.debug(
            f"Контейнер {BOT_SERVICE_NAME} найден. Статус: {container_status}")

        if container_status == "running":
            actual_state = "active"
        elif container_status == "restarting":
            actual_state = "activating"
        elif container_status in ["exited", "dead"]:
            actual_state = "failed"
        else:
            actual_state = "inactive"  # 'created', 'paused'

    except docker.errors.NotFound:
        logging.warning(f"Контейнер {BOT_SERVICE_NAME} не найден.")
        actual_state = "inactive"
    except requests.exceptions.ConnectionError as e:
        logging.error(
            f"Ошибка подключения к Docker socket: {e}. Проверьте права и монтирование /var/run/docker.sock.")
        if current_reported_state != "docker_socket_error":
            send_or_edit_telegram_alert(
                "watchdog_check_error",
                "watchdog_config_error",
                None,
                error="Docker Socket Connection Error")
            current_reported_state = "docker_socket_error"
            status_alert_message_id = None
        time.sleep(CHECK_INTERVAL_SECONDS * 5)
        return
    except Exception as e:
        logging.error(
            f"Неожиданная ошибка при проверке статуса контейнера: {e}",
            exc_info=True)
        if current_reported_state != "check_error":
            error_safe = escape_html(str(e))
            send_or_edit_telegram_alert(
                "watchdog_check_error",
                "watchdog_error",
                None,
                error=error_safe)
            current_reported_state = "check_error"
            status_alert_message_id = None
        time.sleep(CHECK_INTERVAL_SECONDS)
        return

    # --- Функция перезапуска для Docker ---
    def restart_service_docker():
        if not container:
            logging.error(
                f"Контейнер {BOT_SERVICE_NAME} не найден, не могу перезапустить.")
            return
        try:
            container.restart(timeout=10)
            logging.info(
                f"Команда перезапуска (docker) для {BOT_SERVICE_NAME} отправлена успешно.")
        except docker.errors.APIError as e:
            error_msg = escape_html(str(e))
            logging.error(
                f"Не удалось отправить команду перезапуска (docker) для {BOT_SERVICE_NAME}. Ошибка Docker API: {error_msg}")
            send_or_edit_telegram_alert(
                "watchdog_restart_fail",
                "bot_restart_fail",
                None,
                service_name=BOT_SERVICE_NAME,
                error=error_msg)
        except Exception as e:
            error_msg = escape_html(str(e))
            logging.error(
                f"Неожиданная ошибка при попытке перезапуска (docker) {BOT_SERVICE_NAME}: {error_msg}")
            send_or_edit_telegram_alert(
                "watchdog_restart_fail",
                "bot_restart_fail",
                None,
                service_name=BOT_SERVICE_NAME,
                error=f"Unexpected error: {error_msg}")

    # --- Вызов общей логики ---
    process_service_state(
        actual_state,
        f"Docker status: {container_status}",
        restart_service_docker)


# --- ОБЩАЯ ЛОГИКА ОБРАБОТКИ СОСТОЯНИЯ ---
def process_service_state(
        actual_state: str,
        status_output_full: str,
        restart_function: Callable[[], None]):  # Принимает функцию перезапуска
    """
    Общая логика обработки состояния, не зависящая от systemd или docker.
    """
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state

    state_to_report = None
    alert_type = None
    message_key = None
    message_kwargs = {"bot_name": BOT_NAME}

    # --- ЛОГИКА ПЛАНОВОГО ПЕРЕЗАПУСКА ---
    restart_flag_exists = os.path.exists(RESTART_FLAG_FILE)
    logging.debug(
        f"Проверка флага перезапуска ({RESTART_FLAG_FILE}): {'Найден' if restart_flag_exists else 'Не найден'}")

    if restart_flag_exists and actual_state != "active":
        logging.info(
            f"Обнаружен плановый перезапуск. Отправка/обновление алерта о перезапуске бота...")
        state_to_report = "restarting"
        alert_type = "bot_service_restarting"
        message_key = "watchdog_status_restarting_bot"
        bot_service_was_down_or_activating = True

    elif restart_flag_exists and actual_state == "active":
        logging.debug(
            "Флаг перезапуска найден, но бот активен. Игнорирую флаг.")

    # --- ЛОГИКА АКТИВНОСТИ И СБОЕВ ---
    elif actual_state == "active":
        logging.debug(f"Сервис/контейнер '{BOT_SERVICE_NAME}' активен.")
        if bot_service_was_down_or_activating:
            logging.info(
                "Сервис перешел в состояние 'active'. Проверка лога через 3 секунды...")
            time.sleep(3)
            log_status_key, log_kwargs = check_bot_log_for_errors()
            if log_status_key == "OK":
                logging.info("Проверка лога: OK.")
                state_to_report = "active_ok"
                alert_type = "bot_service_up_ok"
                message_key = "watchdog_status_active_ok"
            elif log_status_key is not None:
                log_details = get_text(
                    log_status_key, WD_LANG, **log_kwargs)  # Используем WD_LANG
                logging.warning(
                    f"Проверка лога: ОБНАРУЖЕНЫ ОШИБКИ ({log_details}).")
                state_to_report = "active_error"
                alert_type = "bot_service_up_error"
                message_key = "watchdog_status_active_error"
                message_kwargs["details"] = log_details
            else:  # log_status_key is None
                logging.warning("Файл лога бота не найден.")
                state_to_report = "active_ok"
                alert_type = "bot_service_up_no_log_file"
                message_key = "watchdog_status_active_log_fail"

            bot_service_was_down_or_activating = False

    elif actual_state == "activating" and not restart_flag_exists:
        logging.info(f"Сервис/контейнер '{BOT_SERVICE_NAME}' активируется...")
        state_to_report = "activating"
        alert_type = "bot_service_activating"
        message_key = "watchdog_status_activating"
        bot_service_was_down_or_activating = True

    # Неплановый сбой
    elif actual_state in ["inactive", "failed", "unknown"] and not restart_flag_exists:
        logging.warning(
            f"Сервис/контейнер '{BOT_SERVICE_NAME}' НЕАКТИВЕН. Фактическое состояние: '{actual_state}'.")
        logging.debug(f"Вывод статуса:\n{status_output_full}")

        state_to_report = "down"
        alert_type = "bot_service_down"
        message_key = "watchdog_status_down"

        # --- Логика определения причины (остается полезной) ---
        if actual_state == "failed":
            fail_reason_match = re.search(
                r"Failed with result '([^']*)'",
                status_output_full)  # Для systemd
            if fail_reason_match:
                reason = fail_reason_match.group(1)
                message_kwargs["reason"] = f" ({get_text('watchdog_status_down_reason', WD_LANG)}: {reason})"
            else:
                message_kwargs["reason"] = f" ({get_text('watchdog_status_down_failed', WD_LANG)})"
        elif DEPLOY_MODE == "docker":
            # Для Docker просто показываем статус
            message_kwargs["reason"] = f" (Status: {status_output_full})"
        else:
            message_kwargs["reason"] = ""
        # --------------------------------------------------------

        if not bot_service_was_down_or_activating:
            logging.info(
                f"Первое обнаружение сбоя (флаг не найден). Вызов функции перезапуска...")
            restart_function()  # Вызываем переданную функцию (systemd или docker)

        bot_service_was_down_or_activating = True

    # --- Отправка или Редактирование Сообщения ---
    try:
        logging.debug(
            f"Перед отправкой: state_to_report='{state_to_report}', current_reported_state='{current_reported_state}', message_key='{message_key}'")

        if state_to_report and state_to_report != current_reported_state:
            logging.info(
                f"Состояние изменилось: '{current_reported_state}' -> '{state_to_report}'. Отправка/редактирование сообщения (ключ: '{message_key}')...")

            message_id_for_operation = status_alert_message_id if state_to_report not in [
                "down", "restarting"] else None

            if message_id_for_operation:
                logging.debug(
                    f"Попытка редактировать сообщение ID: {message_id_for_operation}")
            else:
                logging.debug("Попытка отправить новое сообщение.")

            new_id = send_or_edit_telegram_alert(
                message_key, alert_type, message_id_for_operation, **message_kwargs)

            if new_id is not None:
                logging.debug(
                    f"Операция с сообщением успешна. Новый ID: {new_id}. Обновляю состояние.")
                status_alert_message_id = new_id
                current_reported_state = state_to_report
            else:
                logging.error(
                    f"Не удалось отправить/отредактировать сообщение для состояния '{state_to_report}'. Предыдущее состояние '{current_reported_state}' сохранено.")

        elif state_to_report and state_to_report == current_reported_state:
            logging.debug(
                f"Состояние '{state_to_report}' не изменилось с последней отправки. Пропуск.")
        elif not state_to_report and current_reported_state and current_reported_state.startswith("active"):
            logging.debug(
                f"Сервис продолжает работать в состоянии '{current_reported_state}'. Пропуск.")

    except Exception as e:
        logging.error(
            f"Ошибка при отправке/редактировании уведомления о статусе: {e}",
            exc_info=True)
        status_alert_message_id = None


if __name__ == "__main__":
    if not ALERT_BOT_TOKEN:
        print("FATAL: Telegram Bot Token (TG_BOT_TOKEN) not found or empty.")
        sys.exit(1)
    if not ALERT_ADMIN_ID:
        print("FATAL: Telegram Admin ID (TG_ADMIN_ID) not found or empty.")
        sys.exit(1)
    try:
        int(ALERT_ADMIN_ID)
    except ValueError:
        print(
            f"FATAL: TG_ADMIN_ID ('{ALERT_ADMIN_ID}') is not a valid integer.")
        sys.exit(1)

    logging.info(
        f"Система оповещений (Alert) запущена. Режим: {DEPLOY_MODE.upper()}. Отслеживание: {BOT_SERVICE_NAME}")

    # --- ОТПРАВКА АЛЕРТА О ЗАПУСКЕ САМОГО НАБЛЮДАТЕЛЯ (Watchdog) ---
    send_or_edit_telegram_alert(
        "watchdog_status_restarting_wd",
        "watchdog_start",
        None,
        bot_name=BOT_NAME)
    # -----------------------------------------------------------------

    # --- ГЛАВНЫЙ ЦИКЛ ---
    while True:
        if DEPLOY_MODE == "docker":
            if DOCKER_AVAILABLE and docker_client:
                check_bot_service_docker()
            else:
                logging.critical(
                    "Режим Docker, но клиент не инициализирован или недоступен. Watchdog не может работать.")
                # Отправляем алерт, если еще не отправляли
                if current_reported_state != "docker_lib_error":
                    send_or_edit_telegram_alert(
                        "watchdog_check_error",
                        "watchdog_error",
                        None,
                        error="Docker client not available or not installed")
                    current_reported_state = "docker_lib_error"
                time.sleep(60)  # Спим долго
        else:
            # По умолчанию используем systemd
            check_bot_service_systemd()

        time.sleep(CHECK_INTERVAL_SECONDS)
