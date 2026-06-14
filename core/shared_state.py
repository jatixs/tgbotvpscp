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
ACTIVE_NODE_SPEEDTESTS = {}
AUTH_TOKENS = {}
RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}
AGENT_FLAG = "🏳️"
AGENT_IP_CACHE = "Loading..."
AGENT_PING_CACHE = "n/a"
AGENT_PING_LAST_UPDATE = 0
AGENT_HISTORY = deque(maxlen=60)
AGENT_BOT_START_TIME: float = time.time()
AGENT_AVAILABILITY: dict = {}
WEB_NOTIFICATIONS = deque(maxlen=50)
WEB_USER_LAST_READ = {}
RECENT_SSH_LOGINS = {}
IS_RESTARTING = False

# --- Memory Orchestrator ---
# Reference to the global orchestrator instance (set at startup in bot.py)
ORCHESTRATOR = None
