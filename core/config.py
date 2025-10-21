# /opt/tg-bot/core/config.py
import os
import sys
import logging

# --- Пути ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")
ALERTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "alerts_config.json")
# --- ДОБАВЛЕНО ---
USER_SETTINGS_FILE = os.path.join(CONFIG_DIR, "user_settings.json")
# -----------------
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# --- Загрузка .env ---
TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure")
ADMIN_USERNAME = os.environ.get("TG_ADMIN_USERNAME")

try:
    ADMIN_USER_ID = int(os.environ.get("TG_ADMIN_ID"))
except (ValueError, TypeError):
    print("Ошибка: Переменная окружения TG_ADMIN_ID должна быть установлена и быть числом.")
    sys.exit(1)

if not TOKEN:
    print("Ошибка: Переменная окружения TG_BOT_TOKEN не установлена.")
    sys.exit(1)

if not ADMIN_USERNAME:
    print("-------------------------------------------------------")
    print("ВНИМАНИЕ: Переменная TG_ADMIN_USERNAME не установлена.")
    print("Кнопка 'Отправить ID' будет открывать ПРОФИЛЬ админа,")
    print("а не личный чат. Для открытия прямого чата, установите")
    print("эту переменную (указав свой юзернейм без @).")
    print("-------------------------------------------------------")

# --- ДОБАВЛЕНО: Настройки языка ---
DEFAULT_LANGUAGE = "ru"
# ---------------------------------

# --- Настройки порогов и интервалов ---
TRAFFIC_INTERVAL = 5
RESOURCE_CHECK_INTERVAL = 60 # Интервал проверки ресурсов (1 минута)
CPU_THRESHOLD = 90.0
RAM_THRESHOLD = 90.0
DISK_THRESHOLD = 95.0
RESOURCE_ALERT_COOLDOWN = 1800 # 30 минут (1800 сек) - как часто слать НАПОМИНАНИЯ

# --- Настройка логирования ---
def setup_logging():
    logging.basicConfig(level=logging.INFO, filename=LOG_FILE,
                        format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(console_handler)