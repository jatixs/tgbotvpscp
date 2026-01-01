# /opt-tg-bot/core/shared_state.py
import time
from collections import deque

ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {}
USER_SETTINGS = {}
NODES = {}
NODE_TRAFFIC_MONITORS = {}
AUTH_TOKENS = {}
RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}
AGENT_HISTORY = []

# --- WEB UI NOTIFICATIONS ---
WEB_NOTIFICATIONS = deque(maxlen=50)
WEB_UNREAD_COUNT = 0