# /opt-tg-bot/core/utils.py
import os
import json
import logging
import requests
import re
import asyncio
import urllib.parse
import time
from datetime import datetime
from typing import Optional # <--- Добавлен Optional
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

# --- Импортируем i18n и config ---
from . import config
from .i18n import get_text, get_user_lang
# --- ДОБАВЛЕНО: Импорт режимов ---
from .config import INSTALL_MODE, DEPLOY_MODE
# --------------------------------

from .config import (
# ... (остальные импорты config)
# ... existing code ...
from .shared_state import ALERTS_CONFIG

# --- НОВАЯ ФУНКЦИЯ ---
def get_host_path(path: str) -> str:
    """
    Корректирует путь к файлу хоста, если бот запущен в режиме docker-root.
    """
    if DEPLOY_MODE == "docker" and INSTALL_MODE == "root":
        # В режиме docker-root ФС хоста смонтирована в /host
        # Убедимся, что путь начинается со слеша
        if not path.startswith('/'):
            path = '/' + path
        
        host_path = f"/host{path}"
        
        # Проверяем, существует ли путь в /host, если нет - пробуем оригинальный (для /proc и т.д.)
        if os.path.exists(host_path):
            return host_path
        elif os.path.exists(path):
            # Это для /proc/*, которые монтируются docker'ом, а не нами
            return path
        else:
            # Возвращаем путь в /host, даже если он не существует,
            # чтобы ошибка "file not found" показала правильный путь
            return host_path
    
    # В режимах systemd-* или docker-secure используем обычные пути
    return path
# --- КОНЕЦ НОВОЙ ФУНКЦИИ ---


def load_alerts_config():
# ... (existing code) ...
# ... (Весь остальной код файла 'core/utils.py' остается без изменений) ...
