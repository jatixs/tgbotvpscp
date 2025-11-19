import time

ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {}
USER_SETTINGS = {}

NODES = {}

RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}