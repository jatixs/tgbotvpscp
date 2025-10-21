# /opt/tg-bot/watchdog.py
# --- ОРИГИНАЛЬНАЯ РАБОЧАЯ ВЕРСИЯ ---
import os
import time
import subprocess
import requests
import logging
import re # Добавлен re для парсинга статуса
import json
import sys

# --- Настройки ---
DOTENV_PATH = os.path.join(os.path.dirname(__file__), '.env')

def load_env(dotenv_path):
    env_vars = {}
    try:
        with open(dotenv_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Убираем кавычки, если они есть
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    env_vars[key.strip()] = value.strip()
    except FileNotFoundError:
        print(f"ERROR: .env file not found at {dotenv_path}")
    except Exception as e:
        print(f"ERROR: Could not read .env file: {e}")
    return env_vars

env_config = load_env(DOTENV_PATH)

ALERT_BOT_TOKEN = env_config.get("TG_BOT_TOKEN", None)
ALERT_ADMIN_ID = env_config.get("TG_ADMIN_ID", None)
BOT_SERVICE_NAME = "tg-bot.service"
BOT_NAME = env_config.get("TG_BOT_NAME", BOT_SERVICE_NAME) # Используем имя из .env или имя сервиса

BASE_DIR = os.path.dirname(__file__)
CONFIG_DIR = os.path.join(BASE_DIR, "config")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")

BOT_LOG_FILE = os.path.join(BASE_DIR, "logs", "bot.log")

CHECK_INTERVAL_SECONDS = 5 # Интервал проверки статуса
ALERT_COOLDOWN_SECONDS = 300 # Кулдаун для *повторных* алертов о сбое рестарта и т.д.

LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "watchdog.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(level=logging.INFO, filename=LOG_FILE,
                    format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

last_alert_times = {}
bot_service_was_down_or_activating = False # Флаг для отслеживания предыдущего нерабочего состояния
status_alert_message_id = None
current_reported_state = None # Храним последнее *отправленное* состояние ('down', 'activating', 'active_ok', 'active_error')

def send_or_edit_telegram_alert(message, alert_type, message_id_to_edit=None):
    global last_alert_times, status_alert_message_id

    current_time = time.time()
    # Кулдаун применяется только к определенным типам (например, ошибки),
    # но не к основным статусам Down/Activating/Active
    apply_cooldown = alert_type in ["bot_restart_fail", "watchdog_config_error", "watchdog_error", "bot_service_error_on_start"]
    if apply_cooldown and current_time - last_alert_times.get(alert_type, 0) < ALERT_COOLDOWN_SECONDS:
        logging.warning(f"Активен кулдаун для '{alert_type}', пропуск уведомления.")
        return message_id_to_edit # Возвращаем старый ID, если он был

    text_to_send = f"🚨 <b>Система оповещений (Alert):</b>\n\n{message}"

    message_sent_or_edited = False
    new_message_id = message_id_to_edit # По умолчанию сохраняем старый

    # 1. Попытка Редактирования (если есть ID)
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
            if response.status_code == 200:
                logging.info(f"Telegram-сообщение ID {message_id_to_edit} успешно отредактировано (тип '{alert_type}').")
                message_sent_or_edited = True
                if apply_cooldown: last_alert_times[alert_type] = current_time
            elif response.status_code == 400 and "message is not modified" in response.text:
                 logging.debug(f"Сообщение ID {message_id_to_edit} не изменено (текст совпадает).")
                 message_sent_or_edited = True # Считаем успешным, т.к. состояние актуально
            else:
                logging.warning(f"Не удалось отредактировать сообщение ID {message_id_to_edit}. Статус: {response.status_code}, Ответ: {response.text}. Попытка отправить новое.")
                status_alert_message_id = None
                new_message_id = None
        except Exception as e:
            logging.error(f"Исключение при редактировании Telegram-сообщения ID {message_id_to_edit}: {e}. Попытка отправить новое.")
            status_alert_message_id = None
            new_message_id = None

    # 2. Отправка Нового Сообщения (если редактирование не удалось или не требовалось)
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
                new_message_id = None # Не удалось отправить
        except Exception as e:
            logging.error(f"Исключение при отправке Telegram-оповещения '{alert_type}': {e}")
            new_message_id = None

    return new_message_id

def check_bot_log_for_errors():
    """Читает последние 20 строк лога бота и ищет ошибки."""
    try:
        if not os.path.exists(BOT_LOG_FILE):
            logging.warning(f"Лог-файл бота {BOT_LOG_FILE} не найден. Не могу проверить на ошибки.")
            return None # Не ошибка, просто файла нет

        result = subprocess.run(
            ['tail', '-n', '20', BOT_LOG_FILE],
            capture_output=True, text=True, check=False, encoding='utf-8'
        )

        if result.returncode != 0:
            logging.error(f"Не удалось прочитать {BOT_LOG_FILE} через tail: {result.stderr}")
            return f"Ошибка чтения лога: {result.stderr}"

        log_content = result.stdout
        log_content_lower = log_content.lower()

        if "critical" in log_content_lower or "error" in log_content_lower:
            last_error_line = ""
            for line in log_content.splitlines():
                 if "ERROR" in line or "CRITICAL" in line:
                      last_error_line = line

            if last_error_line:
                 # Возвращаем последнюю строку с ошибкой (кратко), экранируем HTML
                 last_error_safe = last_error_line.replace('<', '&lt;').replace('>', '&gt;')
                 return f"Обнаружена ОШИБКА: ...{last_error_safe[-150:]}"

            return "Обнаружены ошибки (ERROR/CRITICAL) в логе"

        return "OK" # Ошибок не найдено

    except Exception as e:
        logging.error(f"Исключение в check_bot_log_for_errors: {e}", exc_info=True)
        return f"Исключение при чтении лога: {str(e).replace('<', '&lt;').replace('>', '&gt;')}"


def check_bot_service():
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state

    actual_state = "unknown" # Фактическое состояние сервиса ('active', 'activating', 'inactive', 'failed', 'unknown')
    state_to_report = None # Состояние, которое мы хотим *отобразить* пользователю ('active_ok', 'active_error', 'activating', 'down')
    alert_type = None      # Тип алерта для логов/кулдауна
    message_text = None    # Текст сообщения

    try:
        status_result = subprocess.run(['systemctl', 'status', BOT_SERVICE_NAME], capture_output=True, text=True, check=False)
        status_output_full = status_result.stdout.strip()

        # Определяем фактическое состояние
        if "Active: active (running)" in status_output_full:
            actual_state = "active"
        elif "Active: activating" in status_output_full:
             actual_state = "activating"
        elif "Active: inactive (dead)" in status_output_full:
             actual_state = "inactive"
        elif "Active: failed" in status_output_full:
             actual_state = "failed"


        # --- Логика определения состояния для ОТПРАВКИ/РЕДАКТИРОВАНИЯ ---

        # 1. Сервис работает (active)
        if actual_state == "active":
            logging.debug(f"Сервис бота '{BOT_SERVICE_NAME}' активен.")
            # Если он *был* неактивен ИЛИ активировался
            if bot_service_was_down_or_activating:
                logging.info("Сервис перешел в состояние 'active'. Проверка лога через 3 секунды...")
                time.sleep(3) # Даем боту время дописать ошибки в лог
                log_status = check_bot_log_for_errors()

                if log_status == "OK":
                    logging.info("Проверка лога: OK.")
                    state_to_report = "active_ok"
                    alert_type = "bot_service_up_ok"
                    message_text = f"Сервис <b>{BOT_NAME}</b>: Активен 🟢"
                elif log_status is not None:
                    logging.warning(f"Проверка лога: ОБНАРУЖЕНЫ ОШИБКИ ({log_status}).")
                    state_to_report = "active_error"
                    alert_type = "bot_service_up_error"
                    message_text = f"Сервис <b>{BOT_NAME}</b>: Активен с ошибками 🟠\n\n<b>Детали:</b> {log_status}\n\nРекомендуется проверить `bot.log`."
                else: # Не удалось прочитать лог
                    logging.warning("Не удалось проверить лог бота.")
                    state_to_report = "active_ok" # Считаем, что все ок, но добавляем пометку
                    alert_type = "bot_service_up_no_log_check"
                    message_text = f"Сервис <b>{BOT_NAME}</b>: Активен 🟢 (Проверка лога не удалась)"

                bot_service_was_down_or_activating = False # Сбрасываем флаг

        # 2. Сервис запускается (activating)
        elif actual_state == "activating":
            logging.info(f"Сервис бота '{BOT_SERVICE_NAME}' активируется...")
            state_to_report = "activating" # Хотим показать этот статус
            alert_type = "bot_service_activating"
            message_text = f"Сервис <b>{BOT_NAME}</b>: Запускается 🟡"
            bot_service_was_down_or_activating = True # Устанавливаем флаг

        # 3. Сервис НЕ работает (inactive, failed, unknown)
        else:
            logging.warning(f"Сервис бота '{BOT_SERVICE_NAME}' НЕАКТИВЕН. Фактическое состояние: '{actual_state}'.")
            if os.path.exists(RESTART_FLAG_FILE):
                logging.info(f"Обнаружен плановый перезапуск (restart_flag.txt). Alert-система не вмешивается.")
                # Если было сообщение о сбое, оно будет обновлено при успешном старте бота
                return

            state_to_report = "down" # Хотим показать этот статус
            alert_type = "bot_service_down"
            message_text = f"Сервис <b>{BOT_NAME}</b>: Недоступен 🔴"
            if actual_state == "failed":
                  fail_reason_match = re.search(r"Failed with result '([^']*)'", status_output_full)
                  if fail_reason_match:
                       message_text += f"\n(Причина: {fail_reason_match.group(1)})"
                  else:
                       message_text += "\n(Статус: failed)"

            # Перезапускаем только если он *не был* уже помечен как down/activating
            if not bot_service_was_down_or_activating:
                logging.info(f"Первое обнаружение сбоя. Попытка перезапуска {BOT_SERVICE_NAME}...")
                restart_result = subprocess.run(['sudo', 'systemctl', 'restart', BOT_SERVICE_NAME], capture_output=True, text=True, check=False)
                if restart_result.returncode != 0:
                     error_msg = restart_result.stderr.strip().replace('<', '&lt;').replace('>', '&gt;')
                     logging.error(f"Не удалось отправить команду перезапуска для {BOT_SERVICE_NAME}. Ошибка: {error_msg}")
                     # Отправляем отдельное сообщение об ошибке рестарта
                     send_or_edit_telegram_alert(f"⚠️ Alert-система НЕ СМОГЛА отправить команду перезапуска для <b>{BOT_SERVICE_NAME}</b>. Требуется ручная проверка.\nОшибка: {error_msg}", "bot_restart_fail", None)

            bot_service_was_down_or_activating = True # Устанавливаем флаг


        # --- Отправка или Редактирование Сообщения ---
        if state_to_report and state_to_report != current_reported_state:
            logging.info(f"Состояние изменилось: '{current_reported_state}' -> '{state_to_report}'. Отправка/редактирование сообщения.")

            # Если переходим в down - всегда новое сообщение, чтобы не редактировать старое "активен"
            message_id_for_operation = status_alert_message_id if state_to_report != "down" else None

            new_id = send_or_edit_telegram_alert(message_text, alert_type, message_id_for_operation)

            # Обновляем ID и последнее отправленное состояние
            # Если new_id = None (ошибка отправки), status_alert_message_id останется старым или станет None
            status_alert_message_id = new_id if new_id is not None else status_alert_message_id
            current_reported_state = state_to_report

            # Если сервис стал активен (OK или с ошибками), сбрасываем ID для следующего цикла,
            # чтобы при следующем падении создалось новое сообщение.
            if state_to_report == "active_ok" or state_to_report == "active_error":
                 status_alert_message_id = None
                 # current_reported_state остается, чтобы не дублировать сообщение об ошибке или успехе

        elif state_to_report and state_to_report == current_reported_state:
             logging.debug(f"Состояние '{state_to_report}' не изменилось с последней отправки. Пропуск.")
        elif not state_to_report and current_reported_state and current_reported_state.startswith("active"):
             # Если бот работал (active_ok или active_error) и продолжает работать,
             # current_reported_state остается, state_to_report=None, ничего не делаем.
             logging.debug(f"Сервис продолжает работать в состоянии '{current_reported_state}'. Пропуск.")


    except FileNotFoundError:
        logging.error("Команда systemctl не найдена. Не могу проверить статус сервиса.")
        # Отправляем как новое сообщение, только если еще не сообщали об этой ошибке
        if current_reported_state != "systemctl_error":
             send_or_edit_telegram_alert("⚠️ <code>systemctl</code> не найден. Не могу проверить статус сервиса.", "watchdog_config_error", None)
             current_reported_state = "systemctl_error" # Запоминаем, что сообщили
             status_alert_message_id = None # Сбрасываем ID
        time.sleep(CHECK_INTERVAL_SECONDS * 5)
    except Exception as e:
        logging.error(f"Ошибка при проверке сервиса бота: {e}", exc_info=True)
        # Отправляем как новое сообщение, только если еще не сообщали об этой ошибке
        if current_reported_state != "check_error":
            send_or_edit_telegram_alert(f"⚠️ Ошибка проверки статуса сервиса: {str(e).replace('<', '&lt;').replace('>', '&gt;')}", "watchdog_error", None)
            current_reported_state = "check_error" # Запоминаем, что сообщили
            status_alert_message_id = None # Сбрасываем ID


if __name__ == "__main__":
    # Проверки токена и ID админа
    if not ALERT_BOT_TOKEN:
        logging.error("FATAL: Telegram Bot Token (TG_BOT_TOKEN) not found or empty in .env file.")
        sys.exit(1)
    if not ALERT_ADMIN_ID:
        logging.error("FATAL: Telegram Admin ID (TG_ADMIN_ID) not found or empty in .env file.")
        sys.exit(1)
    try:
        int(ALERT_ADMIN_ID)
    except ValueError:
        logging.error(f"FATAL: TG_ADMIN_ID in .env file ('{ALERT_ADMIN_ID}') is not a valid integer.")
        sys.exit(1)

    # Стартовое сообщение
    logging.info(f"Система оповещений (Alert) запущена. Отслеживание сервиса: {BOT_SERVICE_NAME}")
    send_or_edit_telegram_alert(f"🚨 Внутренний сервис 'Система оповещений (Alert)' запущен.\nОтслеживание: <b>{BOT_NAME}</b>", "watchdog_start", None)

    # Главный цикл
    while True:
        check_bot_service()
        time.sleep(CHECK_INTERVAL_SECONDS)