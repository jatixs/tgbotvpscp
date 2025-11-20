import time

ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {}
USER_SETTINGS = {}

NODES = {}

# --- НОВОЕ: Словарь для мониторов трафика нод ---
# Структура: {user_id: {"token": node_token, "message_id": msg_id, "last_update": timestamp}}
NODE_TRAFFIC_MONITORS = {}
# ------------------------------------------------

RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}