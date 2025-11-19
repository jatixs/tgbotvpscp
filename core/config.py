import os
import sys
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

TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure")
DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "systemd")
ADMIN_USERNAME = os.environ.get("TG_ADMIN_USERNAME")
TG_BOT_NAME = os.environ.get("TG_BOT_NAME", "VPS Bot")

WEB_SERVER_HOST = os.environ.get("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.environ.get("WEB_SERVER_PORT", 8080))

try:
    ADMIN_USER_ID = int(os.environ.get("TG_ADMIN_ID"))
except (ValueError, TypeError):
    print("Error: TG_ADMIN_ID env var must be set and be an integer.")
    sys.exit(1)

if not TOKEN:
    print("Error: TG_BOT_TOKEN env var is not set.")
    sys.exit(1)

DEFAULT_LANGUAGE = "ru"

TRAFFIC_INTERVAL = 5
RESOURCE_CHECK_INTERVAL = 60
CPU_THRESHOLD = 90.0
RAM_THRESHOLD = 90.0
DISK_THRESHOLD = 95.0
RESOURCE_ALERT_COOLDOWN = 1800
# --- ИЗМЕНЕНО: Таймаут уменьшен до 20 сек (4 хартбита по 5 сек) ---
NODE_OFFLINE_TIMEOUT = 20
# ------------------------------------------------------------------

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