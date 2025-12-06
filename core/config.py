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
NODE_LOG_DIR = os.path.join(LOG_DIR, "node")

os.makedirs(BOT_LOG_DIR, exist_ok=True)
os.makedirs(WATCHDOG_LOG_DIR, exist_ok=True)
os.makedirs(NODE_LOG_DIR, exist_ok=True)

USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
NODES_FILE = os.path.join(CONFIG_DIR, "nodes.json")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")
ALERTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "alerts_config.json")
USER_SETTINGS_FILE = os.path.join(CONFIG_DIR, "user_settings.json")
SYSTEM_CONFIG_FILE = os.path.join(CONFIG_DIR, "system_config.json")
KEYBOARD_CONFIG_FILE = os.path.join(CONFIG_DIR, "keyboard_config.json") # NEW
WEB_AUTH_FILE = os.path.join(CONFIG_DIR, "web_auth.txt")

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

# Значения по умолчанию для системы
DEFAULT_CONFIG = {
    "TRAFFIC_INTERVAL": 5,
    "RESOURCE_CHECK_INTERVAL": 60,
    "CPU_THRESHOLD": 90.0,
    "RAM_THRESHOLD": 90.0,
    "DISK_THRESHOLD": 95.0,
    "RESOURCE_ALERT_COOLDOWN": 1800,
    "NODE_OFFLINE_TIMEOUT": 20
}

# Значения по умолчанию для модулей (клавиатуры)
DEFAULT_KEYBOARD_CONFIG = {
    "enable_selftest": True,
    "enable_uptime": True,
    "enable_speedtest": True,
    "enable_traffic": True,
    "enable_top": True,
    "enable_sshlog": True,
    "enable_fail2ban": True,
    "enable_logs": True,
    "enable_vless": True,
    "enable_xray": True,
    "enable_update": True,
    "enable_restart": True,
    "enable_reboot": True,
    "enable_notifications": True,
    "enable_users": True,
    "enable_optimize": True
}

# Глобальные переменные
TRAFFIC_INTERVAL = DEFAULT_CONFIG["TRAFFIC_INTERVAL"]
RESOURCE_CHECK_INTERVAL = DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"]
CPU_THRESHOLD = DEFAULT_CONFIG["CPU_THRESHOLD"]
RAM_THRESHOLD = DEFAULT_CONFIG["RAM_THRESHOLD"]
DISK_THRESHOLD = DEFAULT_CONFIG["DISK_THRESHOLD"]
RESOURCE_ALERT_COOLDOWN = DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"]
NODE_OFFLINE_TIMEOUT = DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"]

KEYBOARD_CONFIG = DEFAULT_KEYBOARD_CONFIG.copy()

def load_system_config():
    """Загружает системные настройки."""
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
    """Сохраняет системные настройки."""
    global TRAFFIC_INTERVAL, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT

    try:
        if "TRAFFIC_INTERVAL" in new_config: TRAFFIC_INTERVAL = int(new_config["TRAFFIC_INTERVAL"])
        if "NODE_OFFLINE_TIMEOUT" in new_config: NODE_OFFLINE_TIMEOUT = int(new_config["NODE_OFFLINE_TIMEOUT"])
        if "CPU_THRESHOLD" in new_config: CPU_THRESHOLD = float(new_config["CPU_THRESHOLD"])
        if "RAM_THRESHOLD" in new_config: RAM_THRESHOLD = float(new_config["RAM_THRESHOLD"])
        if "DISK_THRESHOLD" in new_config: DISK_THRESHOLD = float(new_config["DISK_THRESHOLD"])

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

def load_keyboard_config():
    """Загружает настройки клавиатуры."""
    global KEYBOARD_CONFIG
    try:
        if os.path.exists(KEYBOARD_CONFIG_FILE):
            with open(KEYBOARD_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Обновляем только существующие ключи, чтобы не потерять дефолтные при обновлении структуры
                KEYBOARD_CONFIG.update(data)
            logging.info("Keyboard config loaded.")
        else:
            logging.info("Keyboard config not found, using defaults.")
    except Exception as e:
        logging.error(f"Error loading keyboard config: {e}")

def save_keyboard_config(new_config: dict):
    """Сохраняет настройки клавиатуры."""
    global KEYBOARD_CONFIG
    try:
        # Обновляем только те ключи, которые есть в дефолтном конфиге (безопасность)
        for key in DEFAULT_KEYBOARD_CONFIG:
            if key in new_config:
                KEYBOARD_CONFIG[key] = bool(new_config[key])
        
        with open(KEYBOARD_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(KEYBOARD_CONFIG, f, indent=4)
        logging.info("Keyboard config saved.")
    except Exception as e:
        logging.error(f"Error saving keyboard config: {e}")

# Загружаем конфиги при старте модуля
load_system_config()
load_keyboard_config()

def setup_logging(log_directory, log_filename_prefix):
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    log_file_path = os.path.join(log_directory, f"{log_filename_prefix}.log")
    rotating_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=30, encoding='utf-8'
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
    logging.info(f"Logging configured. Files will be saved in {log_directory}")
