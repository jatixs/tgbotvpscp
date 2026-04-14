import logging
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
AGENT_FLAG = "🏳️"
AGENT_IP_CACHE = "Loading..."
AGENT_PING_CACHE = "n/a"
AGENT_PING_LAST_UPDATE = 0
AGENT_HISTORY = deque(maxlen=20000)
WEB_NOTIFICATIONS = deque(maxlen=50)
WEB_USER_LAST_READ = {}
RECENT_SSH_LOGINS = {}
IS_RESTARTING = False


def _history_settings():
    from . import config as current_config

    retention_days = max(1, int(getattr(current_config, "HISTORY_RETENTION_DAYS", 1)))
    interval = max(5, int(getattr(current_config, "MONITORING_INTERVAL", 5)))
    max_points = max(300, min(20000, int((retention_days * 86400) / interval) + 10))
    return current_config, retention_days, interval, max_points


def _normalize_point(point):
    if not isinstance(point, dict):
        return None
    try:
        return {
            "t": int(point.get("t", time.time())),
            "c": float(point.get("c", 0)),
            "r": float(point.get("r", 0)),
            "rx": int(point.get("rx", 0)),
            "tx": int(point.get("tx", 0)),
        }
    except Exception:
        return None


def prune_agent_history():
    _, retention_days, _, max_points = _history_settings()
    cutoff = int(time.time() - retention_days * 86400)
    filtered = []

    for point in list(AGENT_HISTORY):
        normalized = _normalize_point(point)
        if normalized and normalized["t"] >= cutoff:
            filtered.append(normalized)

    AGENT_HISTORY.clear()
    AGENT_HISTORY.extend(filtered[-max_points:])


def load_agent_history():
    current_config, retention_days, _, max_points = _history_settings()
    cutoff = int(time.time() - retention_days * 86400)
    raw_points = current_config.get_bot_config("monitoring_history", [])

    AGENT_HISTORY.clear()
    if not isinstance(raw_points, list):
        return

    for point in raw_points[-max_points:]:
        normalized = _normalize_point(point)
        if normalized and normalized["t"] >= cutoff:
            AGENT_HISTORY.append(normalized)


def persist_agent_history():
    current_config, _, _, _ = _history_settings()
    prune_agent_history()
    try:
        current_config.set_bot_config("monitoring_history", list(AGENT_HISTORY))
    except Exception as exc:
        logging.error(f"Failed to persist monitoring history: {exc}")


def clear_monitoring_history():
    current_config, _, _, _ = _history_settings()
    AGENT_HISTORY.clear()
    current_config.set_bot_config("monitoring_history", [])
