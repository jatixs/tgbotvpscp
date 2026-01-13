import os
import sys
import json
import logging
import logging.handlers
import re
from datetime import datetime
from cryptography.fernet import Fernet

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
KEYBOARD_CONFIG_FILE = os.path.join(CONFIG_DIR, "keyboard_config.json")
WEB_AUTH_FILE = os.path.join(CONFIG_DIR, "web_auth.txt")
SECURITY_KEY_FILE = os.path.join(CONFIG_DIR, "security.key")


def load_or_create_key():
    if os.path.exists(SECURITY_KEY_FILE):
        with open(SECURITY_KEY_FILE, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(SECURITY_KEY_FILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(SECURITY_KEY_FILE, 0o600)
        except Exception:
            pass
        return key


DATA_ENCRYPTION_KEY = load_or_create_key()
CIPHER_SUITE = Fernet(DATA_ENCRYPTION_KEY)


def load_encrypted_json(path: str) -> dict | list:
    """
    Загружает JSON из файла.
    1. Пробует расшифровать (новый формат).
    2. Если не вышло — пробует загрузить как обычный JSON (старый формат, авто-миграция).
    """
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "rb") as f:
            data = f.read()

        if not data:
            return {}

        try:
            decrypted = CIPHER_SUITE.decrypt(data)
            return json.loads(decrypted.decode("utf-8"))
        except Exception:

            return json.loads(data.decode("utf-8"))

    except Exception as e:
        logging.error(f"Error loading secure config {path}: {e}")
        return {}


def save_encrypted_json(path: str, data: dict | list):
    """
    Сохраняет данные в файл, полностью шифруя JSON-контент.
    """
    try:
        json_str = json.dumps(data, indent=4, ensure_ascii=False)
        encrypted = CIPHER_SUITE.encrypt(json_str.encode("utf-8"))

        tmp_path = path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(encrypted)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)
    except Exception as e:
        logging.error(f"Error saving secure config {path}: {e}")


DEBUG_MODE = os.environ.get("DEBUG", "false").lower() == "true"
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

DEFAULT_CONFIG = {
    "TRAFFIC_INTERVAL": 5,
    "RESOURCE_CHECK_INTERVAL": 60,
    "CPU_THRESHOLD": 90.0,
    "RAM_THRESHOLD": 90.0,
    "DISK_THRESHOLD": 95.0,
    "RESOURCE_ALERT_COOLDOWN": 1800,
    "NODE_OFFLINE_TIMEOUT": 20
}

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
    "enable_nodes": True,
    "enable_optimize": True
}

TRAFFIC_INTERVAL = DEFAULT_CONFIG["TRAFFIC_INTERVAL"]
RESOURCE_CHECK_INTERVAL = DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"]
CPU_THRESHOLD = DEFAULT_CONFIG["CPU_THRESHOLD"]
RAM_THRESHOLD = DEFAULT_CONFIG["RAM_THRESHOLD"]
DISK_THRESHOLD = DEFAULT_CONFIG["DISK_THRESHOLD"]
RESOURCE_ALERT_COOLDOWN = DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"]
NODE_OFFLINE_TIMEOUT = DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"]

KEYBOARD_CONFIG = DEFAULT_KEYBOARD_CONFIG.copy()


def load_system_config():
    global TRAFFIC_INTERVAL, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT
    try:
        if os.path.exists(SYSTEM_CONFIG_FILE):
            with open(SYSTEM_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                TRAFFIC_INTERVAL = data.get(
                    "TRAFFIC_INTERVAL", DEFAULT_CONFIG["TRAFFIC_INTERVAL"])
                RESOURCE_CHECK_INTERVAL = data.get(
                    "RESOURCE_CHECK_INTERVAL",
                    DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"])
                CPU_THRESHOLD = data.get(
                    "CPU_THRESHOLD", DEFAULT_CONFIG["CPU_THRESHOLD"])
                RAM_THRESHOLD = data.get(
                    "RAM_THRESHOLD", DEFAULT_CONFIG["RAM_THRESHOLD"])
                DISK_THRESHOLD = data.get(
                    "DISK_THRESHOLD", DEFAULT_CONFIG["DISK_THRESHOLD"])
                RESOURCE_ALERT_COOLDOWN = data.get(
                    "RESOURCE_ALERT_COOLDOWN",
                    DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"])
                NODE_OFFLINE_TIMEOUT = data.get(
                    "NODE_OFFLINE_TIMEOUT", DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"])
                logging.info("System config loaded successfully.")
    except Exception as e:
        logging.error(f"Error loading system config: {e}")


def save_system_config(new_config: dict):
    global TRAFFIC_INTERVAL, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT
    try:
        if "TRAFFIC_INTERVAL" in new_config:
            TRAFFIC_INTERVAL = int(new_config["TRAFFIC_INTERVAL"])
        if "NODE_OFFLINE_TIMEOUT" in new_config:
            NODE_OFFLINE_TIMEOUT = int(new_config["NODE_OFFLINE_TIMEOUT"])
        if "CPU_THRESHOLD" in new_config:
            CPU_THRESHOLD = float(new_config["CPU_THRESHOLD"])
        if "RAM_THRESHOLD" in new_config:
            RAM_THRESHOLD = float(new_config["RAM_THRESHOLD"])
        if "DISK_THRESHOLD" in new_config:
            DISK_THRESHOLD = float(new_config["DISK_THRESHOLD"])

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
    global KEYBOARD_CONFIG
    try:

        data = load_encrypted_json(KEYBOARD_CONFIG_FILE)
        if data:
            KEYBOARD_CONFIG.update(data)
            if "enable_nodes" not in KEYBOARD_CONFIG:
                KEYBOARD_CONFIG["enable_nodes"] = True
            logging.info("Keyboard config loaded (secure).")
        else:
            logging.info("Keyboard config not found or empty, using defaults.")
    except Exception as e:
        logging.error(f"Error loading keyboard config: {e}")


def save_keyboard_config(new_config: dict):
    global KEYBOARD_CONFIG
    try:
        for key in DEFAULT_KEYBOARD_CONFIG:
            if key in new_config:
                KEYBOARD_CONFIG[key] = bool(new_config[key])

        save_encrypted_json(KEYBOARD_CONFIG_FILE, KEYBOARD_CONFIG)
        logging.info("Keyboard config saved (secure).")
    except Exception as e:
        logging.error(f"Error saving keyboard config: {e}")


load_system_config()
load_keyboard_config()


class RedactingFormatter(logging.Formatter):
    def __init__(self, orig_formatter):
        self.orig_formatter = orig_formatter
        self._datefmt = orig_formatter.datefmt

    def format(self, record):
        msg = self.orig_formatter.format(record)
        if DEBUG_MODE:
            return msg

        msg = re.sub(r'\d{8,10}:[\w-]{35}', '[TOKEN_REDACTED]', msg)
        ip_pattern = r'\b(?!(?:127\.0\.0\.1|0\.0\.0\.0|localhost))(?:\d{1,3}\.){3}\d{1,3}\b'
        msg = re.sub(ip_pattern, '[IP_REDACTED]', msg)
        msg = re.sub(r'\b[a-fA-F0-9]{32,64}\b', '[HASH_REDACTED]', msg)
        msg = re.sub(
            r'\b(id|user_id|chat_id|user)=(\d+)\b',
            r'\1=[ID_REDACTED]',
            msg)
        msg = re.sub(r'@[\w_]{5,}', '@[USERNAME_REDACTED]', msg)

        return msg

    def __getattr__(self, attr):
        return getattr(self.orig_formatter, attr)


def setup_logging(log_directory, log_filename_prefix):
    log_format_str = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    base_formatter = logging.Formatter(log_format_str)

    secure_formatter = RedactingFormatter(base_formatter)

    log_file_path = os.path.join(log_directory, f"{log_filename_prefix}.log")

    rotating_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=30, encoding='utf-8'
    )
    rotating_handler.suffix = "%Y-%m-%d"
    rotating_handler.setFormatter(secure_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(secure_formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(rotating_handler)
    logger.addHandler(console_handler)

    mode_name = "DEBUG" if DEBUG_MODE else "RELEASE"
logging.info(
        f"Logging initialized. Mode: {mode_name}. Sensitive data redaction: {'OFF' if DEBUG_MODE else 'ON'}"
    )


SENTRY_DSN = os.environ.get("SENTRY_DSN")

DB_URL = f"sqlite://{os.path.join(CONFIG_DIR, 'nodes.db')}"

TORTOISE_ORM = {
    "connections": {"default": DB_URL},
    "apps": {
        "models": {
            "models": ["core.models", "aerich.models"],
            "default_connection": "default",
        }
    },
}
