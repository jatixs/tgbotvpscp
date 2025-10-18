import os
import time
import subprocess
import requests
import logging
import psutil
import json

# --- Настройки ---
# Прочитаем переменные из .env файла бота, чтобы не дублировать
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

# Значения по умолчанию, если .env не найден или переменные отсутствуют
ALERT_BOT_TOKEN = env_config.get("TG_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE") # Токен бота
ALERT_ADMIN_ID = env_config.get("TG_ADMIN_ID", "YOUR_ADMIN_ID_HERE")    # ID админа для алертов
BOT_SERVICE_NAME = "tg-bot.service"   # Имя systemd-сервиса основного бота

# Пороги для ресурсов
CPU_THRESHOLD = 90.0         # %
RAM_THRESHOLD = 90.0         # %
DISK_THRESHOLD = 95.0        # % (для '/')

CHECK_INTERVAL_SECONDS = 60      # Как часто проверять (раз в минуту)
ALERT_COOLDOWN_SECONDS = 300     # Не спамить алертами чаще, чем раз в 5 минут

LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "watchdog.log") # Лог в подпапке logs
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, filename=LOG_FILE,
                    format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

# --- Глобальные переменные состояния ---
last_alert_times = {} # Словарь для кулдаунов по типам алертов
bot_service_was_down = False # Флаг, что сервис бота был недоступен

# --- Функции ---
def send_telegram_alert(message, alert_type):
    global last_alert_times
    current_time = time.time()

    if current_time - last_alert_times.get(alert_type, 0) < ALERT_COOLDOWN_SECONDS:
        logging.warning(f"Alert cooldown active for type '{alert_type}', skipping notification.")
        return

    url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': ALERT_ADMIN_ID,
        'text': f"🐶 <b>Watchdog Alert:</b>\n\n{message}",
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            logging.info(f"Telegram alert '{alert_type}' sent successfully.")
            last_alert_times[alert_type] = current_time
        else:
            logging.error(f"Failed to send Telegram alert '{alert_type}'. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        logging.error(f"Exception while sending Telegram alert '{alert_type}': {e}")

def check_resources():
    alerts = []
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent

        logging.debug(f"Resource check: CPU={cpu:.1f}%, RAM={ram:.1f}%, Disk={disk:.1f}%")

        if cpu >= CPU_THRESHOLD:
            alerts.append({"type": "cpu_high", "msg": f"🔥 CPU usage high: <b>{cpu:.1f}%</b> (Threshold: {CPU_THRESHOLD}%)"})
        if ram >= RAM_THRESHOLD:
            alerts.append({"type": "ram_high", "msg": f"💾 RAM usage high: <b>{ram:.1f}%</b> (Threshold: {RAM_THRESHOLD}%)"})
        if disk >= DISK_THRESHOLD:
            alerts.append({"type": "disk_high", "msg": f"💽 Disk usage high: <b>{disk:.1f}%</b> (Threshold: {DISK_THRESHOLD}%)"})

    except Exception as e:
        logging.error(f"Error checking resources: {e}")
        alerts.append({"type": "check_error", "msg": f"⚠️ Error checking resources: {e}"})
    return alerts

def check_bot_service():
    global bot_service_was_down
    try:
        # Проверяем статус systemd сервиса
        result = subprocess.run(['systemctl', 'is-active', BOT_SERVICE_NAME], capture_output=True, text=True)
        is_active = result.stdout.strip() == 'active'

        if not is_active:
            logging.warning(f"Bot service '{BOT_SERVICE_NAME}' is INACTIVE.")
            if not bot_service_was_down: # Отправляем алерт только при первом обнаружении
                 send_telegram_alert(f"🚨 Bot service <b>{BOT_SERVICE_NAME}</b> is DOWN!", "bot_service_down")
                 bot_service_was_down = True
            # Попытка перезапуска
            logging.info(f"Attempting to restart {BOT_SERVICE_NAME}...")
            restart_result = subprocess.run(['sudo', 'systemctl', 'restart', BOT_SERVICE_NAME], capture_output=True, text=True)
            if restart_result.returncode == 0:
                logging.info(f"Restart command sent for {BOT_SERVICE_NAME}.")
                # Даем время на запуск перед следующей проверкой
                time.sleep(5)
                # Проверяем снова после перезапуска
                result_after = subprocess.run(['systemctl', 'is-active', BOT_SERVICE_NAME], capture_output=True, text=True)
                if result_after.stdout.strip() == 'active':
                    logging.info(f"{BOT_SERVICE_NAME} restarted successfully.")
                    send_telegram_alert(f"✅ Bot service <b>{BOT_SERVICE_NAME}</b> was restarted successfully.", "bot_service_restart")
                    bot_service_was_down = False # Сбрасываем флаг после успешного перезапуска
                else:
                    logging.error(f"Failed to restart {BOT_SERVICE_NAME} successfully. Still inactive.")
                    # Алерт о неудачном перезапуске можно добавить, но может спамить
            else:
                logging.error(f"Failed to send restart command for {BOT_SERVICE_NAME}. Error: {restart_result.stderr}")
                send_telegram_alert(f"⚠️ Failed to send restart command for <b>{BOT_SERVICE_NAME}</b>. Manual check required.", "bot_restart_fail")

        else:
            logging.debug(f"Bot service '{BOT_SERVICE_NAME}' is active.")
            if bot_service_was_down: # Если сервис поднялся после падения
                send_telegram_alert(f"✅ Bot service <b>{BOT_SERVICE_NAME}</b> is now ACTIVE again.", "bot_service_up")
                bot_service_was_down = False # Сбрасываем флаг

    except FileNotFoundError:
        logging.error("systemctl command not found. Cannot check service status.")
        send_telegram_alert("⚠️ <code>systemctl</code> not found. Cannot check bot service status.", "watchdog_config_error")
    except Exception as e:
        logging.error(f"Error checking bot service: {e}")
        send_telegram_alert(f"⚠️ Error checking bot service status: {e}", "watchdog_error")

# --- Основной цикл ---
if __name__ == "__main__":
    if not ALERT_BOT_TOKEN or "YOUR_BOT_TOKEN_HERE" in ALERT_BOT_TOKEN:
        logging.error("FATAL: Telegram Bot Token is not configured in .env file.")
        sys.exit(1)
    if not ALERT_ADMIN_ID or "YOUR_ADMIN_ID_HERE" in ALERT_ADMIN_ID:
        logging.error("FATAL: Telegram Admin ID is not configured in .env file.")
        sys.exit(1)

    logging.info("Watchdog started.")
    send_telegram_alert("🐶 Internal Watchdog service started.", "watchdog_start") # Оповещение о запуске

    while True:
        # 1. Проверка ресурсов
        resource_alerts = check_resources()
        for alert in resource_alerts:
            send_telegram_alert(alert["msg"], alert["type"])

        # 2. Проверка сервиса бота
        check_bot_service()

        # Пауза перед следующей проверкой
        time.sleep(CHECK_INTERVAL_SECONDS)