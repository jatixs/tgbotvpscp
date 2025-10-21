# /opt/tg-bot/core/shared_state.py
import time

# Состояния, которые раньше были глобальными
ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {}
RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}

# Карта для кнопок главного меню
BUTTONS_MAP = {
    "user": [],
    "admin": [],
    "root": []
}