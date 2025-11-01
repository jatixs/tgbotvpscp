# /opt-tg-bot/core/config.py
import os
import sys
import logging
# --- ДОБАВЛЕНО: Импортируем handlers для настройки логов ---
import logging.handlers
# --------------------------------------------------------
from datetime import datetime  # Добавляем импорт datetime

# --- Пути ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
# --- ИЗМЕНЕНО: Создаем базовую директорию логов ---
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)  # Добавлено создание CONFIG_DIR
# -------------------------------------------------
# --- ИЗМЕНЕНО: Определяем пути к поддиректориям логов ---
BOT_LOG_DIR = os.path.join(LOG_DIR, "bot")
WATCHDOG_LOG_DIR = os.path.join(LOG_DIR, "watchdog")
os.makedirs(BOT_LOG_DIR, exist_ok=True)       # Создаем поддиректорию для бота
# Создаем поддиректорию для watchdog
os.makedirs(WATCHDOG_LOG_DIR, exist_ok=True)
# -------------------------------------------------------

USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")
ALERTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "alerts_config.json")
USER_SETTINGS_FILE = os.path.join(CONFIG_DIR, "user_settings.json")
# --- LOG_FILE удален ---

# --- Загрузка .env ---
TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure")
# --- ДОБАВЛЕНО: Чтение DEPLOY_MODE ---
DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "systemd")
# ------------------------------------
ADMIN_USERNAME = os.environ.get("TG_ADMIN_USERNAME")

try:
    ADMIN_USER_ID = int(os.environ.get("TG_ADMIN_ID"))
except (ValueError, TypeError):
    # Используем print, т.к. логгер еще не настроен
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


DEFAULT_LANGUAGE = "ru"

# --- Настройки порогов и интервалов ---
TRAFFIC_INTERVAL = 5
RESOURCE_CHECK_INTERVAL = 60
CPU_THRESHOLD = 90.0
RAM_THRESHOLD = 90.0
DISK_THRESHOLD = 95.0
RESOURCE_ALERT_COOLDOWN = 1800

# --- Настройка логирования ---
# --- ИСПРАВЛЕНО: Функция setup_logging ---


def setup_logging(log_directory, log_filename_prefix):
    """Настраивает логирование с ежедневной ротацией."""
    log_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s')

    # Создаем ПОЛНЫЙ путь к основному файлу лога
    log_file_path = os.path.join(log_directory, f"{log_filename_prefix}.log")

    # Настройка обработчика с ротацией по времени (каждый день в полночь)
    rotating_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_path,  # ПЕРЕДАЕМ ПОЛНЫЙ ПУТЬ
        when="midnight",
        interval=1,
        backupCount=30,
        encoding='utf-8'
        # Убираем дублирующийся аргумент filename=
    )

    # Суффикс для старых (ротированных) файлов
    rotating_handler.suffix = "%Y-%m-%d"  # Обработчик сам добавит это к имени файла
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
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---
