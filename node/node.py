import os
import time
import json
import logging
import platform
import asyncio
import requests
import psutil
from logging.handlers import RotatingFileHandler

# --- ИЗМЕНЕНО: Default interval 5s ---
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8080")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
NODE_UPDATE_INTERVAL = int(os.environ.get("NODE_UPDATE_INTERVAL", 5))
# -------------------------------------

# --- Настройка путей ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs", "node")
os.makedirs(LOG_DIR, exist_ok=True)

# --- Логирование ---
log_file = os.path.join(LOG_DIR, "node.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=2),
        logging.StreamHandler()
    ]
)

def get_system_stats():
    """Собирает статистику системы."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        
        # Uptime
        uptime_seconds = time.time() - psutil.boot_time()
        
        # Форматирование uptime
        days = int(uptime_seconds // (24 * 3600))
        hours = int((uptime_seconds % (24 * 3600)) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        uptime_str = f"{days}d {hours}h {minutes}m"

        return {
            "cpu": cpu,
            "ram": mem,
            "disk": disk,
            "uptime": uptime_str,
            "uptime_sec": uptime_seconds
        }
    except Exception as e:
        logging.error(f"Ошибка сбора статистики: {e}")
        return {}

def perform_task(task):
    """Выполняет команду, присланную Агентом."""
    cmd = task.get("command")
    logging.info(f"Получена команда: {cmd}")
    
    if cmd == "reboot":
        logging.warning("Выполняется перезагрузка по команде Агента...")
        os.system("(sleep 2 && /sbin/reboot) &")

def send_heartbeat():
    """Отправляет данные на Агент."""
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    stats = get_system_stats()
    
    payload = {
        "token": AGENT_TOKEN,
        "stats": stats
    }
    
    try:
        response = requests.post(url, json=payload, timeout=3) # Timeout меньше интервала
        if response.status_code == 200:
            logging.info(f"Heartbeat OK. CPU: {stats.get('cpu')}%")
            data = response.json()
            
            # Проверка задач
            tasks = data.get("tasks", [])
            for task in tasks:
                perform_task(task)
        else:
            logging.error(f"Ошибка сервера: {response.status_code} - {response.text}")
    except requests.exceptions.ConnectionError:
        logging.error(f"Не удалось подключиться к Агенту ({url}). Сервер недоступен?")
    except Exception as e:
        logging.error(f"Ошибка отправки heartbeat: {e}")

def main():
    if not AGENT_TOKEN:
        logging.critical("AGENT_TOKEN не установлен! Проверьте .env")
        return

    logging.info(f"Node Agent запущен.")
    logging.info(f"Target: {AGENT_BASE_URL}")
    logging.info(f"Interval: {NODE_UPDATE_INTERVAL}s")

    while True:
        send_heartbeat()
        time.sleep(NODE_UPDATE_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Остановка Node Agent.")