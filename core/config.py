import asyncio
import os
import sys
import json
import logging
import logging.handlers
import re
from datetime import datetime
import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
BOT_LOG_DIR = os.path.join(LOG_DIR, "bot")
WATCHDOG_LOG_DIR = os.path.join(LOG_DIR, "watchdog")
NODE_LOG_DIR = os.path.join(LOG_DIR, "node")
TRAFFIC_BACKUP_DIR = os.path.join(LOG_DIR, "traffic_backups")
CONFIG_BACKUP_DIR = os.path.join(LOG_DIR, "config_backups")
LOGS_BACKUP_DIR = os.path.join(LOG_DIR, "logs_backups")
NODES_BACKUP_DIR = os.path.join(LOG_DIR, "nodes_backups")
os.makedirs(BOT_LOG_DIR, exist_ok=True)
os.makedirs(WATCHDOG_LOG_DIR, exist_ok=True)
os.makedirs(NODE_LOG_DIR, exist_ok=True)
os.makedirs(TRAFFIC_BACKUP_DIR, exist_ok=True)
os.makedirs(CONFIG_BACKUP_DIR, exist_ok=True)
os.makedirs(LOGS_BACKUP_DIR, exist_ok=True)
os.makedirs(NODES_BACKUP_DIR, exist_ok=True)

BOT_DB_PATH = os.path.join(CONFIG_DIR, "bot.db")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")


def load_or_create_key():
    raw_key = os.environ.get("DATA_ENCRYPTION_KEY")
    if not raw_key:
        raise RuntimeError(
            "DATA_ENCRYPTION_KEY env var is required. Refusing to start without an encryption key."
        )

    key = raw_key.strip().encode("utf-8")
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "DATA_ENCRYPTION_KEY must contain a valid Fernet key."
        ) from exc

    return key


DATA_ENCRYPTION_KEY = load_or_create_key()
CIPHER_SUITE = Fernet(DATA_ENCRYPTION_KEY)


def _run_async_compat(coro, operation_name: str):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        f"{operation_name} must be awaited in async code. "
        f"Use the async API instead of the sync compatibility wrapper."
    )


def _normalize_db_blob(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _decode_config_blob(config_key: str, raw_value):
    raw_bytes = _normalize_db_blob(raw_value)

    try:
        decrypted = CIPHER_SUITE.decrypt(raw_bytes)
        return json.loads(decrypted.decode("utf-8"))
    except InvalidToken:
        try:
            return json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Config value '{config_key}' is neither valid Fernet ciphertext nor valid JSON."
            ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Config value '{config_key}' could not be decoded.") from exc


async def init_bot_db():
    try:
        async with aiosqlite.connect(BOT_DB_PATH) as conn:
            await conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS bot_config (
                    key TEXT PRIMARY KEY,
                    value BLOB
                )
                '''
            )
            await conn.commit()
    except Exception as exc:
        logging.critical("Error initializing bot.db: %s", exc)
        raise RuntimeError("Failed to initialize bot.db") from exc


def init_bot_db_sync():
    return _run_async_compat(init_bot_db(), "init_bot_db()")


async def get_bot_config(key: str, default=None):
    try:
        async with aiosqlite.connect(BOT_DB_PATH) as conn:
            async with conn.execute(
                "SELECT value FROM bot_config WHERE key = ?",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()
        if row:
            return _decode_config_blob(key, row[0])
    except Exception as e:
        logging.error(f"Error loading bot config {key}: {e}")
    return default if default is not None else {}


def get_bot_config_sync(key: str, default=None):
    return _run_async_compat(get_bot_config(key, default), f"get_bot_config({key!r})")


async def set_bot_config(key: str, data: dict | list):
    try:
        json_str = json.dumps(data, indent=4, ensure_ascii=False)
        encrypted = CIPHER_SUITE.encrypt(json_str.encode("utf-8"))
        async with aiosqlite.connect(BOT_DB_PATH) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)",
                (key, encrypted),
            )
            await conn.commit()
    except Exception as e:
        logging.error(f"Error saving bot config {key}: {e}")
        raise


def set_bot_config_sync(key: str, data: dict | list):
    return _run_async_compat(set_bot_config(key, data), f"set_bot_config({key!r}, ...)")

def _migrate_json_to_db():
    migration_map = {
        "users": os.path.join(CONFIG_DIR, "users.json"),
        "alerts_config": os.path.join(CONFIG_DIR, "alerts_config.json"),
        "services": os.path.join(CONFIG_DIR, "services.json"),
        "user_settings": os.path.join(CONFIG_DIR, "user_settings.json"),
        "system_config": os.path.join(CONFIG_DIR, "system_config.json"),
        "keyboard_config": os.path.join(CONFIG_DIR, "keyboard_config.json"),
        "security_settings": os.path.join(CONFIG_DIR, "security_settings.json"),
        "terminal_creds": os.path.join(CONFIG_DIR, "terminal_creds.json"),
        "dashboard_config": os.path.join(CONFIG_DIR, "dashboard_config.json"),
    }
    for key, file_path in migration_map.items():
        if os.path.exists(file_path):
            try:
                data = {}
                with open(file_path, "rb") as f:
                    raw = f.read()
                if not raw: continue
                try:
                    decrypted = CIPHER_SUITE.decrypt(raw)
                    data = json.loads(decrypted.decode("utf-8"))
                except Exception:
                    data = json.loads(raw.decode("utf-8"))
                
                set_bot_config_sync(key, data)
                os.rename(file_path, file_path + ".bak")
                logging.info(f"Migrated {file_path} to DB key '{key}'")
            except Exception as e:
                logging.error(f"Failed to migrate {file_path}: {e}")

init_bot_db_sync()
_migrate_json_to_db()

DEBUG_MODE = os.environ.get("DEBUG", "false").lower() == "true"
UNSAFE_LOGGING = os.environ.get("UNSAFE_LOGGING", "false").lower() == "true"
TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure")
DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "systemd")
ADMIN_USERNAME = os.environ.get("TG_ADMIN_USERNAME")
TG_BOT_NAME = os.environ.get("TG_BOT_NAME", "VPS Bot")
INSTALLED_VERSION = os.environ.get("INSTALLED_VERSION")
WEB_SERVER_HOST = os.environ.get("WEB_SERVER_HOST", "127.0.0.1")
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
    "BACKUP_INTERVAL": 300,
    "BACKUP_LAST_INTERVAL": 300,
    "SERVICES_INTERVAL": 5,
    "PING_INTERVAL": 30,
    "PING_MODE": "http",
    "PING_TARGET": "google",
    "RESOURCE_CHECK_INTERVAL": 60,
    "CPU_THRESHOLD": 90.0,
    "RAM_THRESHOLD": 90.0,
    "DISK_THRESHOLD": 95.0,
    "RESOURCE_ALERT_COOLDOWN": 1800,
    "NODE_OFFLINE_TIMEOUT": 20,
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
    "enable_optimize": True,
    "enable_services": True,
    "enable_billing": True,
}

# --- MANAGED SERVICES CONFIG ---
# This list acts as a whitelist of services to monitor.
# Only services that physically exist (installed/loaded) on the system will be displayed.
MANAGED_SERVICES = [
    # Core Services
    {"name": "ssh", "type": "systemd"},
    {"name": "sshd", "type": "systemd"},
    {"name": "cron", "type": "systemd"},
    {"name": "docker", "type": "systemd"},
    {"name": "ufw", "type": "systemd"},
    {"name": "fail2ban", "type": "systemd"},
    
    # Web Servers
    {"name": "nginx", "type": "systemd"},
    {"name": "apache2", "type": "systemd"},
    {"name": "httpd", "type": "systemd"},
    {"name": "caddy", "type": "systemd"},
    
    # Databases
    {"name": "mysql", "type": "systemd"},
    {"name": "mariadb", "type": "systemd"},
    {"name": "postgresql", "type": "systemd"},
    {"name": "redis-server", "type": "systemd"},
    {"name": "redis", "type": "systemd"},
    {"name": "mongodb", "type": "systemd"},
    {"name": "mongod", "type": "systemd"},
    
    # VPN / Proxy
    {"name": "xray", "type": "systemd"},
    {"name": "v2ray", "type": "systemd"},
    {"name": "wg-quick@wg0", "type": "systemd"},
    
    # Docker Containers (Common)
    {"name": "portainer", "type": "docker"},
    {"name": "nginx-proxy-manager", "type": "docker"},
    {"name": "watchtower", "type": "docker"},
    
    # Bot itself if in docker
    {"name": "bot-core", "type": "docker"},
]
# ------------------------------
TRAFFIC_INTERVAL = DEFAULT_CONFIG["TRAFFIC_INTERVAL"]
BACKUP_INTERVAL = DEFAULT_CONFIG["BACKUP_INTERVAL"]
BACKUP_LAST_INTERVAL = DEFAULT_CONFIG["BACKUP_LAST_INTERVAL"]
SERVICES_INTERVAL = DEFAULT_CONFIG["SERVICES_INTERVAL"]
PING_INTERVAL = DEFAULT_CONFIG["PING_INTERVAL"]
PING_MODE = DEFAULT_CONFIG["PING_MODE"]
PING_TARGET = DEFAULT_CONFIG["PING_TARGET"]
RESOURCE_CHECK_INTERVAL = DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"]
CPU_THRESHOLD = DEFAULT_CONFIG["CPU_THRESHOLD"]
RAM_THRESHOLD = DEFAULT_CONFIG["RAM_THRESHOLD"]
DISK_THRESHOLD = DEFAULT_CONFIG["DISK_THRESHOLD"]
RESOURCE_ALERT_COOLDOWN = DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"]
NODE_OFFLINE_TIMEOUT = DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"]
KEYBOARD_CONFIG = DEFAULT_KEYBOARD_CONFIG.copy()

# --- NEW: WEB METADATA STORAGE ---
WEB_METADATA = {}
# ---------------------------------

def _apply_system_config(data):
    global TRAFFIC_INTERVAL, BACKUP_INTERVAL, BACKUP_LAST_INTERVAL, SERVICES_INTERVAL, PING_INTERVAL, PING_MODE, PING_TARGET, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT, WEB_METADATA
    if not data:
        return

    TRAFFIC_INTERVAL = data.get("TRAFFIC_INTERVAL", DEFAULT_CONFIG["TRAFFIC_INTERVAL"])
    BACKUP_INTERVAL = data.get("BACKUP_INTERVAL", DEFAULT_CONFIG["BACKUP_INTERVAL"])
    BACKUP_LAST_INTERVAL = data.get("BACKUP_LAST_INTERVAL", DEFAULT_CONFIG["BACKUP_LAST_INTERVAL"])
    SERVICES_INTERVAL = data.get("SERVICES_INTERVAL", DEFAULT_CONFIG["SERVICES_INTERVAL"])
    PING_INTERVAL = data.get("PING_INTERVAL", DEFAULT_CONFIG["PING_INTERVAL"])
    PING_MODE = data.get("PING_MODE", DEFAULT_CONFIG["PING_MODE"])
    PING_TARGET = data.get("PING_TARGET", DEFAULT_CONFIG["PING_TARGET"])
    RESOURCE_CHECK_INTERVAL = data.get("RESOURCE_CHECK_INTERVAL", DEFAULT_CONFIG["RESOURCE_CHECK_INTERVAL"])
    CPU_THRESHOLD = data.get("CPU_THRESHOLD", DEFAULT_CONFIG["CPU_THRESHOLD"])
    RAM_THRESHOLD = data.get("RAM_THRESHOLD", DEFAULT_CONFIG["RAM_THRESHOLD"])
    DISK_THRESHOLD = data.get("DISK_THRESHOLD", DEFAULT_CONFIG["DISK_THRESHOLD"])
    RESOURCE_ALERT_COOLDOWN = data.get("RESOURCE_ALERT_COOLDOWN", DEFAULT_CONFIG["RESOURCE_ALERT_COOLDOWN"])
    NODE_OFFLINE_TIMEOUT = data.get("NODE_OFFLINE_TIMEOUT", DEFAULT_CONFIG["NODE_OFFLINE_TIMEOUT"])
    WEB_METADATA = data.get("WEB_METADATA", {})


async def load_system_config_async():
    try:
        data = await get_bot_config("system_config", {})
        if data:
            _apply_system_config(data)
            logging.info("System config loaded successfully from bot.db.")
    except Exception as e:
        logging.error(f"Error loading system config: {e}")


def load_system_config():
    # Sync compatibility for CLI/import paths. Async runtime should use await load_system_config_async().
    return _run_async_compat(load_system_config_async(), "load_system_config_async()")


async def save_system_config_async(new_config: dict):
    global TRAFFIC_INTERVAL, BACKUP_INTERVAL, BACKUP_LAST_INTERVAL, SERVICES_INTERVAL, PING_INTERVAL, PING_MODE, PING_TARGET, RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD, RESOURCE_ALERT_COOLDOWN, NODE_OFFLINE_TIMEOUT, WEB_METADATA
    try:
        if "TRAFFIC_INTERVAL" in new_config:
            TRAFFIC_INTERVAL = int(new_config["TRAFFIC_INTERVAL"])
        if "BACKUP_INTERVAL" in new_config:
            BACKUP_INTERVAL = int(new_config["BACKUP_INTERVAL"])
        if "BACKUP_LAST_INTERVAL" in new_config:
            BACKUP_LAST_INTERVAL = int(new_config["BACKUP_LAST_INTERVAL"])
        if "SERVICES_INTERVAL" in new_config:
            SERVICES_INTERVAL = int(new_config["SERVICES_INTERVAL"])
        if "PING_INTERVAL" in new_config:
            PING_INTERVAL = int(new_config["PING_INTERVAL"])
        if "PING_MODE" in new_config:
            PING_MODE = str(new_config["PING_MODE"])
        if "PING_TARGET" in new_config:
            PING_TARGET = str(new_config["PING_TARGET"])
        if "RESOURCE_CHECK_INTERVAL" in new_config:
            RESOURCE_CHECK_INTERVAL = int(new_config["RESOURCE_CHECK_INTERVAL"])
        if "NODE_OFFLINE_TIMEOUT" in new_config:
            NODE_OFFLINE_TIMEOUT = int(new_config["NODE_OFFLINE_TIMEOUT"])
        if "CPU_THRESHOLD" in new_config:
            CPU_THRESHOLD = float(new_config["CPU_THRESHOLD"])
        if "RAM_THRESHOLD" in new_config:
            RAM_THRESHOLD = float(new_config["RAM_THRESHOLD"])
        if "DISK_THRESHOLD" in new_config:
            DISK_THRESHOLD = float(new_config["DISK_THRESHOLD"])
        if "RESOURCE_ALERT_COOLDOWN" in new_config:
            RESOURCE_ALERT_COOLDOWN = int(new_config["RESOURCE_ALERT_COOLDOWN"])
        
        # --- UPDATE METADATA ---
        if "WEB_METADATA" in new_config:
            WEB_METADATA = new_config["WEB_METADATA"]
        # -----------------------

        config_to_save = {
            "TRAFFIC_INTERVAL": TRAFFIC_INTERVAL,
            "BACKUP_INTERVAL": BACKUP_INTERVAL,
            "BACKUP_LAST_INTERVAL": BACKUP_LAST_INTERVAL,
            "SERVICES_INTERVAL": SERVICES_INTERVAL,
            "PING_INTERVAL": PING_INTERVAL,
            "PING_MODE": PING_MODE,
            "PING_TARGET": PING_TARGET,
            "RESOURCE_CHECK_INTERVAL": RESOURCE_CHECK_INTERVAL,
            "CPU_THRESHOLD": CPU_THRESHOLD,
            "RAM_THRESHOLD": RAM_THRESHOLD,
            "DISK_THRESHOLD": DISK_THRESHOLD,
            "RESOURCE_ALERT_COOLDOWN": RESOURCE_ALERT_COOLDOWN,
            "NODE_OFFLINE_TIMEOUT": NODE_OFFLINE_TIMEOUT,
            "WEB_METADATA": WEB_METADATA,
        }
        await set_bot_config("system_config", config_to_save)
        logging.info("System config saved.")
    except Exception as e:
        logging.error(f"Error saving system config: {e}")


def save_system_config(new_config: dict):
    # Sync compatibility for CLI/import paths. Async runtime should use await save_system_config_async(...).
    return _run_async_compat(save_system_config_async(new_config), "save_system_config_async(...)")


async def load_keyboard_config_async():
    global KEYBOARD_CONFIG
    try:
        data = await get_bot_config("keyboard_config", {})
        if data:
            new_config = KEYBOARD_CONFIG.copy()
            new_config.update(data)
            if "enable_nodes" not in new_config:
                new_config["enable_nodes"] = True
            KEYBOARD_CONFIG = new_config            
            logging.info("Keyboard config loaded from bot.db.")
        else:
            logging.info("Keyboard config not found or empty, using defaults.")
    except Exception as e:
        logging.error(f"Error loading keyboard config: {e}")


def load_keyboard_config():
    # Sync compatibility for CLI/import paths. Async runtime should use await load_keyboard_config_async().
    return _run_async_compat(load_keyboard_config_async(), "load_keyboard_config_async()")


async def save_keyboard_config_async(new_config: dict):
    try:
        for key in DEFAULT_KEYBOARD_CONFIG:
            if key in new_config:
                KEYBOARD_CONFIG[key] = bool(new_config[key])
        await set_bot_config("keyboard_config", KEYBOARD_CONFIG)
        logging.info("Keyboard config saved to bot.db.")
    except Exception as e:
        logging.error(f"Error saving keyboard config: {e}")


def save_keyboard_config(new_config: dict):
    # Sync compatibility for CLI/import paths. Async runtime should use await save_keyboard_config_async(...).
    return _run_async_compat(save_keyboard_config_async(new_config), "save_keyboard_config_async(...)")


load_system_config()
load_keyboard_config()


class RedactingFormatter(logging.Formatter):

    def __init__(self, orig_formatter):
        self.orig_formatter = orig_formatter
        self._datefmt = orig_formatter.datefmt

    def format(self, record):
        msg = self.orig_formatter.format(record)
        if UNSAFE_LOGGING:
            return msg
        msg = re.sub("\\d{8,10}:[\\w-]{35}", "[TOKEN_REDACTED]", msg)
        ip_pattern = "\\b(?!(?:127\\.0\\.0\\.1|0\\.0\\.0\\.0|localhost))(?:\\d{1,3}\\.){3}\\d{1,3}\\b"
        msg = re.sub(ip_pattern, "[IP_REDACTED]", msg)
        msg = re.sub("\\b[a-fA-F0-9]{32,64}\\b", "[HASH_REDACTED]", msg)
        msg = re.sub("\\b(id|user_id|chat_id|user)=(\\d+)\\b", "\\1=[ID_REDACTED]", msg)
        msg = re.sub("@[\\w_]{5,}", "@[USERNAME_REDACTED]", msg)
        return msg

    def __getattr__(self, attr):
        return getattr(self.orig_formatter, attr)


def setup_logging(log_directory, log_filename_prefix):
    log_format_str = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    base_formatter = logging.Formatter(log_format_str)
    secure_formatter = RedactingFormatter(base_formatter)
    log_file_path = os.path.join(log_directory, f"{log_filename_prefix}.log")
    rotating_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=30, encoding="utf-8"
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
        f"Logging initialized. Mode: {mode_name}. Sensitive data redaction: {('OFF' if UNSAFE_LOGGING else 'ON')}"
    )


SENTRY_DSN = os.environ.get("SENTRY_DSN")

OLD_DB_URL = os.path.join(CONFIG_DIR, 'nodes.db')
NEW_DB_URL = os.path.join(CONFIG_DIR, 'node.db')
if os.path.exists(OLD_DB_URL) and not os.path.exists(NEW_DB_URL):
    try:
        os.rename(OLD_DB_URL, NEW_DB_URL)
        logging.info(f"Database renamed from {OLD_DB_URL} to {NEW_DB_URL}")
    except Exception as e:
        logging.error(f"Failed to rename nodes.db: {e}")
        NEW_DB_URL = OLD_DB_URL

DB_URL = f"sqlite://{NEW_DB_URL}"
TORTOISE_ORM = {
    "connections": {"default": DB_URL},
    "apps": {
        "models": {
            "models": ["core.models", "aerich.models"],
            "default_connection": "default",
        }
    },
}
