import time

ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {}
USER_SETTINGS = {}

NODES = {}

# Словарь для мониторов трафика нод
NODE_TRAFFIC_MONITORS = {}

# --- НОВОЕ: Временные токены для Magic Link авторизации ---
# Структура: {token: {"user_id": int, "created_at": float}}
AUTH_TOKENS = {}
# ----------------------------------------------------------

RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}