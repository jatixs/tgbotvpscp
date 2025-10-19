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

BASE_DIR = os.path.dirname(__file__)
CONFIG_DIR = os.path.join(BASE_DIR, "config")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")

CHECK_INTERVAL_SECONDS = 5
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
bot_service_was_down = False
# --- [ИЗМЕНЕНИЕ] Переменная для хранения ID сообщения о статусе ---
status_alert_message_id = None
current_reported_state = None # Храним последнее *отправленное* состояние
# -----------------------------------------------------------------

# --- [ИЗМЕНЕНИЕ] Обновленная функция отправки/редактирования ---
def send_or_edit_telegram_alert(message, alert_type, message_id_to_edit=None):
    global last_alert_times, status_alert_message_id

    current_time = time.time()
    # Кулдаун применяется только к определенным типам (например, ошибки),
    # но не к основным статусам Down/Activating/Active
    apply_cooldown = alert_type in ["bot_restart_fail", "watchdog_config_error", "watchdog_error"]
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
                # new_message_id остается прежним
                if apply_cooldown: last_alert_times[alert_type] = current_time
            elif response.status_code == 400 and "message is not modified" in response.text:
                 logging.debug(f"Сообщение ID {message_id_to_edit} не изменено (текст совпадает).")
                 message_sent_or_edited = True # Считаем успешным, т.к. состояние актуально
            else:
                logging.warning(f"Не удалось отредактировать сообщение ID {message_id_to_edit}. Статус: {response.status_code}, Ответ: {response.text}. Попытка отправить новое.")
                # Ошибка редактирования - сбрасываем ID, чтобы отправить новое
                status_alert_message_id = None # Важно сбросить глобальный ID
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
# --- [КОНЕЦ ИЗМЕНЕНИЯ] ---

def check_bot_service():
    global bot_service_was_down, status_alert_message_id, current_reported_state
    
    actual_state = "unknown" # Фактическое состояние сервиса
    state_to_report = None # Состояние, которое мы хотим *отобразить* пользователю
    alert_type = None      # Тип алерта для логов/кулдауна
    message_text = None    # Текст сообщения

    try:
        # Получаем полный статус
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
        
        # --- [ИЗМЕНЕНИЕ] Логика определения состояния для ОТПРАВКИ/РЕДАКТИРОВАНИЯ ---
        
        # 1. Сервис работает
        if actual_state == "active":
            logging.debug(f"Сервис бота '{BOT_SERVICE_NAME}' активен.")
            if bot_service_was_down: # Если он *был* неактивен
                state_to_report = "active"
                alert_type = "bot_service_up"
                message_text = f"Сервис бота <b>{BOT_SERVICE_NAME}</b> Активен 🟢"
                bot_service_was_down = False # Сбрасываем флаг "был недоступен"
            # Если он и так работал, ничего не сообщаем

        # 2. Сервис запускается
        elif actual_state == "activating":
            logging.info(f"Сервис бота '{BOT_SERVICE_NAME}' активируется...")
            if bot_service_was_down: # Если он был недоступен, обновляем статус
                 state_to_report = "activating"
                 alert_type = "bot_service_activating"
                 message_text = f"Сервис бота <b>{BOT_SERVICE_NAME}</b> Активируется 🟡"
            # Если он не был down (например, просто перезапуск), не шлем промежуточный статус

        # 3. Сервис НЕ работает (inactive, failed, unknown)
        else:
            logging.warning(f"Сервис бота '{BOT_SERVICE_NAME}' НЕАКТИВЕН. Фактическое состояние: '{actual_state}'.")
            
            # Проверка на плановый перезапуск (остается важной!)
            if os.path.exists(RESTART_FLAG_FILE):
                logging.info(f"Обнаружен плановый перезапуск. Alert-система не вмешивается.")
                # Если было сообщение о сбое, нужно его обновить или удалить?
                # Пока просто выходим, бот сам обновит при старте.
                # Если нужно убирать старое сообщение о сбое при плановом рестарте - нужна доп. логика
                return 

            # Это настоящий сбой
            if not bot_service_was_down: # Если это *первое* обнаружение сбоя
                state_to_report = "down"
                alert_type = "bot_service_down"
                message_text = f"Сервис бота <b>{BOT_SERVICE_NAME}</b> Недоступен 🔴"
                if actual_state == "failed":
                      fail_reason_match = re.search(r"Failed with result '([^']*)'", status_output_full)
                      if fail_reason_match:
                           message_text += f" (Причина: {fail_reason_match.group(1)})"
                      else:
                           message_text += " (Статус: failed)"
                bot_service_was_down = True # Устанавливаем флаг "был недоступен"
                # Запускаем попытку перезапуска ТОЛЬКО при первом обнаружении
                logging.info(f"Попытка перезапуска {BOT_SERVICE_NAME}...")
                restart_result = subprocess.run(['sudo', 'systemctl', 'restart', BOT_SERVICE_NAME], capture_output=True, text=True, check=False)
                if restart_result.returncode != 0:
                     error_msg = restart_result.stderr.strip()
                     logging.error(f"Не удалось отправить команду перезапуска для {BOT_SERVICE_NAME}. Ошибка: {error_msg}")
                     # Отправляем отдельное сообщение об ошибке рестарта, оно не будет редактироваться
                     send_or_edit_telegram_alert(f"⚠️ Alert-система НЕ СМОГЛА отправить команду перезапуска для <b>{BOT_SERVICE_NAME}</b>. Требуется ручная проверка.\nОшибка: {error_msg}", "bot_restart_fail", None)

            # Если он уже был down, и все еще down - ничего не делаем (не спамим)
            # state_to_report остается None

        # --- Отправка или Редактирование Сообщения ---
        if state_to_report and state_to_report != current_reported_state:
            logging.info(f"Состояние изменилось на '{state_to_report}'. Отправка/редактирование сообщения.")
            
            # Если переходим в down - всегда новое сообщение
            message_id_for_operation = status_alert_message_id if state_to_report != "down" else None
            
            new_id = send_or_edit_telegram_alert(message_text, alert_type, message_id_for_operation)

            # Обновляем ID и последнее отправленное состояние
            status_alert_message_id = new_id
            current_reported_state = state_to_report

            # Если сервис стал активен, сбрасываем ID для следующего цикла
            if state_to_report == "active":
                 status_alert_message_id = None
                 current_reported_state = None # Готовы к новому циклу сбоя
        
        elif state_to_report and state_to_report == current_reported_state:
             logging.debug(f"Состояние '{state_to_report}' не изменилось с последней отправки. Пропуск.")

        # --- [КОНЕЦ ИЗМЕНЕНИЯ] ---

    except FileNotFoundError:
        # Обработка ошибки systemctl (остается)
        logging.error("Команда systemctl не найдена. Не могу проверить статус сервиса.")
        # Отправляем как новое сообщение, не редактируем статус
        send_or_edit_telegram_alert("⚠️ <code>systemctl</code> не найден. Не могу проверить статус сервиса.", "watchdog_config_error", None)
        time.sleep(CHECK_INTERVAL_SECONDS * 5)
    except Exception as e:
        # Обработка других ошибок (остается)
        logging.error(f"Ошибка при проверке сервиса бота: {e}", exc_info=True)
        # Отправляем как новое сообщение
        send_or_edit_telegram_alert(f"⚠️ Ошибка проверки статуса сервиса: {e}", "watchdog_error", None)


if __name__ == "__main__":
    # Проверки токена и ID админа (остаются)
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

    # Стартовое сообщение (остается)
    logging.info("Система оповещений (Alert) запущена.")
    send_or_edit_telegram_alert("🚨 Внутренний сервис 'Система оповещений (Alert)' запущен.", "watchdog_start", None)

    # Главный цикл (остается)
    while True:
        check_bot_service()
        time.sleep(CHECK_INTERVAL_SECONDS)