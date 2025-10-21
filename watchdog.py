# /opt/tg-bot/watchdog.py
import os
import time
import subprocess
import requests
import logging
import re
import json
import sys

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
# Добавляем путь к core в sys.path, чтобы импорт сработал
BASE_DIR_WATCHDOG = os.path.dirname(__file__)
CORE_DIR_WATCHDOG = os.path.join(BASE_DIR_WATCHDOG, "core")
if CORE_DIR_WATCHDOG not in sys.path:
    sys.path.insert(0, BASE_DIR_WATCHDOG) # Добавляем /opt/tg-bot

try:
    from core import config
    from core.i18n import _ # Импортируем функцию перевода
except ImportError as e:
    print(f"FATAL: Could not import core modules: {e}")
    print("Ensure watchdog.py is run from the correct directory (/opt/tg-bot) and venv.")
    sys.exit(1)
# ----------------------------------------

# --- Настройки ---
# Используем переменные из импортированного config
ALERT_BOT_TOKEN = config.TOKEN
ALERT_ADMIN_ID = config.ADMIN_USER_ID
BOT_SERVICE_NAME = "tg-bot.service"
# Используем имя из .env или имя сервиса (логика остается)
# Пытаемся загрузить .env, чтобы получить TG_BOT_NAME
dotenv_path = os.path.join(BASE_DIR_WATCHDOG, '.env')
env_vars = {}
try:
    with open(dotenv_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                if value.startswith('"') and value.endswith('"'): value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"): value = value[1:-1]
                env_vars[key.strip()] = value.strip()
except Exception as e:
    print(f"WARNING: Could not read .env file for TG_BOT_NAME: {e}")

BOT_NAME = env_vars.get("TG_BOT_NAME", BOT_SERVICE_NAME) # Используем имя из .env или имя сервиса

CONFIG_DIR = config.CONFIG_DIR
RESTART_FLAG_FILE = config.RESTART_FLAG_FILE

LOG_DIR = config.LOG_DIR
BOT_LOG_FILE = config.LOG_FILE
WATCHDOG_LOG_FILE = os.path.join(LOG_DIR, "watchdog.log")

# Остальные настройки
CHECK_INTERVAL_SECONDS = 5
ALERT_COOLDOWN_SECONDS = 300

# Настройка логирования
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, filename=WATCHDOG_LOG_FILE,
                    format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

last_alert_times = {}
bot_service_was_down_or_activating = False
status_alert_message_id = None
current_reported_state = None

# --- ИЗМЕНЕНО: Используем язык по умолчанию ---
WD_LANG = config.DEFAULT_LANGUAGE
# --------------------------------------------

def send_or_edit_telegram_alert(message_key: str, alert_type: str, message_id_to_edit=None, **kwargs):
    """Отправляет или редактирует сообщение, используя ключ i18n."""
    global last_alert_times, status_alert_message_id

    current_time = time.time()
    apply_cooldown = alert_type in ["bot_restart_fail", "watchdog_config_error", "watchdog_error", "bot_service_error_on_start"]
    if apply_cooldown and current_time - last_alert_times.get(alert_type, 0) < ALERT_COOLDOWN_SECONDS:
        logging.warning(f"Активен кулдаун для '{alert_type}', пропуск уведомления.")
        return message_id_to_edit

    # --- ИЗМЕНЕНО: Получаем текст через i18n ---
    alert_prefix = _("watchdog_alert_prefix", WD_LANG)
    message_body = _(message_key, WD_LANG, **kwargs)
    text_to_send = f"{alert_prefix}\n\n{message_body}"
    # -------------------------------------------

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
                logging.warning(f"Не удалось декодировать JSON из ответа Telegram (edit): {response.text}")

            if response.status_code == 200:
                logging.info(f"Telegram-сообщение ID {message_id_to_edit} успешно отредактировано (тип '{alert_type}').")
                message_sent_or_edited = True
                if apply_cooldown: last_alert_times[alert_type] = current_time
            # Исправлена проверка 'message is not modified'
            elif response.status_code == 400 and "message is not modified" in response_data.get("description", "").lower():
                 logging.debug(f"Сообщение ID {message_id_to_edit} не изменено (текст совпадает).")
                 message_sent_or_edited = True
            else:
                logging.warning(f"Не удалось отредактировать сообщение ID {message_id_to_edit}. Статус: {response.status_code}, Ответ: {response.text}. Попытка отправить новое.")
                status_alert_message_id = None
                new_message_id = None
        except requests.exceptions.RequestException as e: # Уточнили тип исключения
            logging.error(f"Ошибка сети при редактировании Telegram-сообщения ID {message_id_to_edit}: {e}. Попытка отправить новое.")
            status_alert_message_id = None
            new_message_id = None
        except Exception as e:
            logging.error(f"Неожиданное исключение при редактировании Telegram-сообщения ID {message_id_to_edit}: {e}. Попытка отправить новое.")
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
                new_message_id = sent_message_data.get('result', {}).get('message_id')
                logging.info(f"Telegram-оповещение '{alert_type}' успешно отправлено (новое сообщение ID {new_message_id}).")
                if apply_cooldown: last_alert_times[alert_type] = current_time
            else:
                logging.error(f"Не удалось отправить Telegram-оповещение '{alert_type}'. Статус: {response.status_code}, Ответ: {response.text}")
                new_message_id = None
        except requests.exceptions.RequestException as e: # Уточнили тип исключения
            logging.error(f"Ошибка сети при отправке Telegram-оповещения '{alert_type}': {e}")
            new_message_id = None
        except Exception as e:
            logging.error(f"Неожиданное исключение при отправке Telegram-оповещения '{alert_type}': {e}")
            new_message_id = None

    return new_message_id

def check_bot_log_for_errors():
    """Читает последние 20 строк лога бота и ищет ошибки. Возвращает (key, kwargs)."""
    try:
        if not os.path.exists(BOT_LOG_FILE):
            logging.warning(f"Лог-файл бота {BOT_LOG_FILE} не найден. Не могу проверить на ошибки.")
            return None, {} # Не ошибка, просто файла нет

        result = subprocess.run(
            ['tail', '-n', '20', BOT_LOG_FILE],
            capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore' # Добавлен errors='ignore'
        )

        if result.returncode != 0:
            logging.error(f"Не удалось прочитать {BOT_LOG_FILE} через tail: {result.stderr}")
            return "watchdog_log_read_error", {"error": result.stderr or "Unknown error"}

        log_content = result.stdout
        log_content_lower = log_content.lower()

        if "critical" in log_content_lower or "error" in log_content_lower:
            last_error_line = ""
            for line in log_content.splitlines():
                 if "ERROR" in line or "CRITICAL" in line:
                      last_error_line = line

            if last_error_line:
                 last_error_safe = last_error_line.replace('<', '&lt;').replace('>', '&gt;')
                 return "watchdog_log_error_found_details", {"details": f"...{last_error_safe[-150:]}"}

            return "watchdog_log_error_found_generic", {}

        return "OK", {} # Ошибок не найдено

    except Exception as e:
        logging.error(f"Исключение в check_bot_log_for_errors: {e}", exc_info=True)
        error_safe = str(e).replace('<', '&lt;').replace('>', '&gt;')
        return "watchdog_log_exception", {"error": error_safe}

def check_bot_service():
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state

    actual_state = "unknown"
    state_to_report = None
    alert_type = None
    message_key = None
    message_kwargs = {"bot_name": BOT_NAME}

    try:
        # Убран check=False, чтобы ошибка systemctl была поймана как исключение
        status_result = subprocess.run(
            ['systemctl', 'status', BOT_SERVICE_NAME],
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore' # Добавлен errors='ignore'
        )
        status_output_full = status_result.stdout.strip()

        # Определяем состояние (как и раньше)
        if "Active: active (running)" in status_output_full: actual_state = "active"
        elif "Active: activating" in status_output_full: actual_state = "activating"
        # inactive и failed теперь будут пойманы через returncode != 0 ниже

    # Ловим ошибки systemctl (включая inactive/failed)
    except subprocess.CalledProcessError as e:
        status_output_full = e.stdout.strip() if e.stdout else e.stderr.strip() # Используем вывод ошибки
        if "inactive (dead)" in status_output_full: actual_state = "inactive"
        elif "failed" in status_output_full: actual_state = "failed"
        else: # Другая ошибка systemctl status
            logging.error(f"Ошибка выполнения systemctl status: {e.stderr or e.stdout}")
            actual_state = "unknown" # Оставляем unknown
            status_output_full = e.stderr or e.stdout # Сохраняем вывод ошибки

    except FileNotFoundError:
        # Код обработки FileNotFoundError остается ниже
        raise # Передаем исключение дальше

    # --- Логика определения состояния и сообщения ---
    if actual_state == "active":
        logging.debug(f"Сервис бота '{BOT_SERVICE_NAME}' активен.")
        if bot_service_was_down_or_activating:
            logging.info("Сервис перешел в состояние 'active'. Проверка лога через 3 секунды...")
            time.sleep(3)
            log_status_key, log_kwargs = check_bot_log_for_errors()

            if log_status_key == "OK":
                logging.info("Проверка лога: OK.")
                state_to_report = "active_ok"
                alert_type = "bot_service_up_ok"
                message_key = "watchdog_status_active_ok"
            elif log_status_key is not None:
                log_details = _(log_status_key, WD_LANG, **log_kwargs)
                logging.warning(f"Проверка лога: ОБНАРУЖЕНЫ ОШИБКИ ({log_details}).")
                state_to_report = "active_error"
                alert_type = "bot_service_up_error"
                message_key = "watchdog_status_active_error"
                message_kwargs["details"] = log_details
            else: # log_status_key is None (файл лога не найден)
                logging.warning("Файл лога бота не найден.")
                state_to_report = "active_ok" # Считаем, что все ок
                alert_type = "bot_service_up_no_log_file" # Другой тип алерта
                message_key = "watchdog_status_active_log_fail" # Тот же ключ сообщения

            bot_service_was_down_or_activating = False

    elif actual_state == "activating":
        logging.info(f"Сервис бота '{BOT_SERVICE_NAME}' активируется...")
        state_to_report = "activating"
        alert_type = "bot_service_activating"
        message_key = "watchdog_status_activating"
        bot_service_was_down_or_activating = True

    else: # inactive, failed, unknown
        logging.warning(f"Сервис бота '{BOT_SERVICE_NAME}' НЕАКТИВЕН. Фактическое состояние: '{actual_state}'. Вывод: {status_output_full}")
        if os.path.exists(RESTART_FLAG_FILE):
            logging.info(f"Обнаружен плановый перезапуск ({os.path.basename(RESTART_FLAG_FILE)}). Alert-система не вмешивается.")
            return # Выходим, чтобы не отправлять 'down' и не пытаться перезапустить

        state_to_report = "down"
        alert_type = "bot_service_down"
        message_key = "watchdog_status_down"
        if actual_state == "failed":
              fail_reason_match = re.search(r"Failed with result '([^']*)'", status_output_full)
              if fail_reason_match:
                   reason = fail_reason_match.group(1)
                   message_kwargs["reason"] = f" ({_('watchdog_status_down_reason', WD_LANG)}: {reason})"
              else:
                   message_kwargs["reason"] = f" ({_('watchdog_status_down_failed', WD_LANG)})"
        else: # inactive / unknown
             message_kwargs["reason"] = ""

        if not bot_service_was_down_or_activating:
            logging.info(f"Первое обнаружение сбоя. Попытка перезапуска {BOT_SERVICE_NAME}...")
            try:
                # Используем check=True, чтобы поймать ошибку рестарта
                restart_result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', BOT_SERVICE_NAME],
                    capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
                )
                logging.info(f"Команда перезапуска для {BOT_SERVICE_NAME} отправлена успешно.")
            except subprocess.CalledProcessError as e:
                 error_msg = (e.stderr or e.stdout or str(e)).strip().replace('<', '&lt;').replace('>', '&gt;')
                 logging.error(f"Не удалось отправить команду перезапуска для {BOT_SERVICE_NAME}. Ошибка: {error_msg}")
                 send_or_edit_telegram_alert(
                     "watchdog_restart_fail",
                     "bot_restart_fail",
                     None,
                     service_name=BOT_SERVICE_NAME,
                     error=error_msg
                 )
            except Exception as e:
                 # Ловим другие возможные ошибки при запуске subprocess
                 error_msg = str(e).replace('<', '&lt;').replace('>', '&gt;')
                 logging.error(f"Неожиданная ошибка при попытке перезапуска {BOT_SERVICE_NAME}: {error_msg}")
                 send_or_edit_telegram_alert(
                     "watchdog_restart_fail",
                     "bot_restart_fail",
                     None,
                     service_name=BOT_SERVICE_NAME,
                     error=f"Unexpected error: {error_msg}"
                 )


        bot_service_was_down_or_activating = True # Устанавливаем флаг в любом случае при неактивном состоянии

    # --- Отправка или Редактирование Сообщения ---
    try:
        if state_to_report and state_to_report != current_reported_state:
            logging.info(f"Состояние изменилось: '{current_reported_state}' -> '{state_to_report}'. Отправка/редактирование сообщения.")

            # Если переходим в down или activating - всегда новое сообщение
            message_id_for_operation = status_alert_message_id if state_to_report.startswith("active") else None

            new_id = send_or_edit_telegram_alert(message_key, alert_type, message_id_for_operation, **message_kwargs)

            # Обновляем ID и последнее *отправленное* состояние
            if new_id is not None:
                status_alert_message_id = new_id
                current_reported_state = state_to_report
            # Если отправка не удалась (new_id is None), не меняем current_reported_state
            # status_alert_message_id мог стать None внутри send_or_edit...

            # Если сервис стал активен (OK или с ошибками), сбрасываем ID для следующего цикла,
            # чтобы при следующем падении создалось новое сообщение.
            # current_reported_state остается, чтобы не дублировать сообщение об ошибке или успехе
            # if state_to_report.startswith("active"): # Убрали сброс ID здесь, делаем его выше
            #      status_alert_message_id = None

        elif state_to_report and state_to_report == current_reported_state:
             logging.debug(f"Состояние '{state_to_report}' не изменилось с последней отправки. Пропуск.")
        # Случай, когда бот работал (active_*) и продолжает работать (state_to_report=None)
        elif not state_to_report and current_reported_state and current_reported_state.startswith("active"):
             logging.debug(f"Сервис продолжает работать в состоянии '{current_reported_state}'. Пропуск.")

    except FileNotFoundError: # Ловим ошибку systemctl
        logging.error("Команда systemctl не найдена. Не могу проверить статус сервиса.")
        if current_reported_state != "systemctl_error":
             send_or_edit_telegram_alert("watchdog_systemctl_not_found", "watchdog_config_error", None)
             current_reported_state = "systemctl_error"
             status_alert_message_id = None
        time.sleep(CHECK_INTERVAL_SECONDS * 5)
    except Exception as e: # Ловим все остальные ошибки
        logging.error(f"Ошибка при проверке сервиса бота или отправке уведомления: {e}", exc_info=True)
        if current_reported_state != "check_error":
            error_safe = str(e).replace('<', '&lt;').replace('>', '&gt;')
            send_or_edit_telegram_alert("watchdog_check_error", "watchdog_error", None, error=error_safe)
            current_reported_state = "check_error"
            status_alert_message_id = None


if __name__ == "__main__":
    if not ALERT_BOT_TOKEN:
        logging.error("FATAL: Telegram Bot Token (TG_BOT_TOKEN) not found or empty.")
        sys.exit(1)
    if not ALERT_ADMIN_ID:
        logging.error("FATAL: Telegram Admin ID (TG_ADMIN_ID) not found or empty.")
        sys.exit(1)
    try: # Проверка, что ADMIN_ID - число
        int(ALERT_ADMIN_ID)
    except ValueError:
         logging.error(f"FATAL: TG_ADMIN_ID ('{ALERT_ADMIN_ID}') is not a valid integer.")
         sys.exit(1)

    logging.info(f"Система оповещений (Alert) запущена. Отслеживание сервиса: {BOT_SERVICE_NAME}")
    # Отправляем стартовое сообщение
    send_or_edit_telegram_alert("watchdog_started", "watchdog_start", None, bot_name=BOT_NAME)

    # Главный цикл
    while True:
        check_bot_service()
        time.sleep(CHECK_INTERVAL_SECONDS)