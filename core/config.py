import os
import sys
import json
import logging
import logging.handlers
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

BOT_LOG_DIR = os.path.join(LOG_DIR, "bot")
WATCHDOG_LOG_DIR = os.path.join(LOG_DIR, "watchdog")
os.makedirs(BOT_LOG_DIR, exist_ok=True)
os.makedirs(WATCHDOG_LOG_DIR, exist_ok=True)

USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
NODES_FILE = os.path.join(CONFIG_DIR, "nodes.json")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")
ALERTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "alerts_config.json")
USER_SETTINGS_FILE = os.path.join(CONFIG_DIR, "user_settings.json")
SYSTEM_CONFIG_FILE = os.path.join(CONFIG_DIR, "system_config.json")
WEB_AUTH_FILE = os.path.join(CONFIG_DIR, "web_auth.txt") # <-- Добавлено

TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure")
DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "systemd")
ADMIN_USERNAME = os.environ.get("TG_ADMIN_USERNAME")
TG_BOT_NAME = os.environ.get("TG_BOT_NAME", "VPS Bot")

WEB_SERVER_HOST = os.environ.get("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.environ.get("WEB_SERVER_PORT", 8080))
ENABLE_WEB_UI = os.environ.get("ENABLE_WEB_UI", "true").lower() == "true"

try:
    ADMIN_USER_ID = int(os.environ.get("TG_ADMIN_ID"))
except (ValueError, TypeError):
    print("Error: TG_ADMIN_ID env var must be set and be an integer.")
    sys.exit(1)

if not TOKEN:
    print("Error: TG_BOT_TOKEN env var is not set.")
    sys.exit(1)

DEFAULT_LANGUAGE = "ru"

# Значения по умолчанию
DEFAULT_CONFIG = {
    "TRAFFIC_INTERVAL": 5,
    "RESOURCE_CHECK_INTERVAL": 60,
    "CPU_THRESHOLD": 90.0,
    "RAM_THRESHOLD": 90.0,
    "DISK_THRESHOLD": 95.0,
    "RESOURCE_ALERT_COOLDOWN": 1800,
    "NODE_OFFLINE_TIMEOUT": 20
}

# Инициализация глобальных переменных
TRAFFIC_INTERVAL = DEFAULT_CONFIG["TRAFFIC_INTERVAL"]
RESOURCE_CHECK_INTERVAL = DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"]
CPU_THRESHOLD = DEFAULT_CONFIG["CPU_THRESHOLD"]
RAM_THRESHOLD = DEFAULT_CONFIG["RAM_THRESHOLD"]
DISK_THRESHOLD = DEFAULT_CONFIG["DISK_THRESHOLD"]
RESOURCE_ALERT_COOLDOWN = DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"]
NODE_OFFLINE_TIMEOUT = DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"]

def load_system_config():
    """Загружает настройки из JSON и обновляет глобальные переменные."""
    global TRAFFIC_INTERVAL, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT
    
    try:
        if os.path.exists(SYSTEM_CONFIG_FILE):
            with open(SYSTEM_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                TRAFFIC_INTERVAL = data.get("TRAFFIC_INTERVAL", DEFAULT_CONFIG["TRAFFIC_INTERVAL"])
                RESOURCE_CHECK_INTERVAL = data.get("RESOURCE_CHECK_INTERVAL", DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"])
                CPU_THRESHOLD = data.get("CPU_THRESHOLD", DEFAULT_CONFIG["CPU_THRESHOLD"])
                RAM_THRESHOLD = data.get("RAM_THRESHOLD", DEFAULT_CONFIG["RAM_THRESHOLD"])
                DISK_THRESHOLD = data.get("DISK_THRESHOLD", DEFAULT_CONFIG["DISK_THRESHOLD"])
                RESOURCE_ALERT_COOLDOWN = data.get("RESOURCE_ALERT_COOLDOWN", DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"])
                NODE_OFFLINE_TIMEOUT = data.get("NODE_OFFLINE_TIMEOUT", DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"])
                logging.info("System config loaded successfully.")
    except Exception as e:
        logging.error(f"Error loading system config: {e}")

def save_system_config(new_config: dict):
    """Сохраняет настройки в JSON и обновляет текущие переменные."""
    global TRAFFIC_INTERVAL, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT
    
    try:
        # Обновляем переменные
        if "TRAFFIC_INTERVAL" in new_config: TRAFFIC_INTERVAL = int(new_config["TRAFFIC_INTERVAL"])
        if "NODE_OFFLINE_TIMEOUT" in new_config: NODE_OFFLINE_TIMEOUT = int(new_config["NODE_OFFLINE_TIMEOUT"])
        if "CPU_THRESHOLD" in new_config: CPU_THRESHOLD = float(new_config["CPU_THRESHOLD"])
        if "RAM_THRESHOLD" in new_config: RAM_THRESHOLD = float(new_config["RAM_THRESHOLD"])
        if "DISK_THRESHOLD" in new_config: DISK_THRESHOLD = float(new_config["DISK_THRESHOLD"])
        
        # Собираем полный конфиг для сохранения
        config_to_save = {
            "TRAFFIC_INTERVAL": TRAFFIC_INTERVAL,
            "RESOURCE_CHECK_INTERVAL": RESOURCE_CHECK_INTERVAL,
            "CPU_THRESHOLD": CPU_THRESHOLD,
            "RAM_THRESHOLD": RAM_THRESHOLD,
            "DISK_THRESHOLD": DISK_THRESHOLD,
            "RESOURCE_ALERT_COOLDOWN": RESOURCE_ALERT_COOLDOWN,
            "NODE_OFFLINE_TIMEOUT": NODE_OFFLINE_TIMEOUT
        }
        
        with open(SYSTEM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, indent=4)
        logging.info("System config saved.")
    except Exception as e:
        logging.error(f"Error saving system config: {e}")

# Загружаем конфиг при старте
load_system_config()

def setup_logging(log_directory, log_filename_prefix):
    log_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s')

    log_file_path = os.path.join(log_directory, f"{log_filename_prefix}.log")

    rotating_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )

    rotating_handler.suffix = "%Y-%m-%d"
    rotating_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(rotating_handler)
    logger.addHandler(console_handler)

    logging.info(
        f"Logging configured. Files will be saved in {log_directory} (e.g., {log_filename_prefix}.log)")