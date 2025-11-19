import os
import time
import json
import logging
import platform
import asyncio
import requests
import psutil
import subprocess
from logging.handlers import RotatingFileHandler

# --- Настройки ---
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8080")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
NODE_UPDATE_INTERVAL = int(os.environ.get("NODE_UPDATE_INTERVAL", 5))

# --- Пути и Логи ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs", "node")
os.makedirs(LOG_DIR, exist_ok=True)

log_file = os.path.join(LOG_DIR, "node.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=2),
        logging.StreamHandler()
    ]
)

# Очередь результатов для отправки: [{ "user_id": 123, "command": "selftest", "result": "..." }]
RESULTS_QUEUE = []

def get_uptime_str():
    uptime_seconds = time.time() - psutil.boot_time()
    days = int(uptime_seconds // (24 * 3600))
    hours = int((uptime_seconds % (24 * 3600)) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    return f"{days}d {hours}h {minutes}m"

def cmd_selftest():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    uptime = get_uptime_str()
    
    # Пробуем получить внешний IP
    try:
        ip = requests.get("https://api.ipify.org", timeout=2).text
    except:
        ip = "Unknown"

    return (
        f"🛠 <b>Node System Status:</b>\n\n"
        f"📊 CPU: <b>{cpu}%</b>\n"
        f"💾 RAM: <b>{mem}%</b>\n"
        f"💽 Disk: <b>{disk}%</b>\n"
        f"⏱ Uptime: <b>{uptime}</b>\n"
        f"🌐 IP: <code>{ip}</code>"
    )

def cmd_top():
    try:
        # ps aux, сортировка по CPU, топ 10
        cmd = "ps aux --sort=-%cpu | head -n 11"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        return f"🔥 <b>Top Processes:</b>\n<pre>{result}</pre>"
    except Exception as e:
        return f"Error running top: {e}"

def perform_task(task):
    """Выполняет команду и сохраняет результат в очередь."""
    cmd = task.get("command")
    user_id = task.get("user_id")
    logging.info(f"Выполнение команды: {cmd} для {user_id}")
    
    output = ""
    
    if cmd == "selftest":
        output = cmd_selftest()
    elif cmd == "uptime":
        output = f"⏱ <b>Uptime:</b> {get_uptime_str()}"
    elif cmd == "top":
        output = cmd_top()
    elif cmd == "reboot":
        output = "🔄 <b>Node is rebooting...</b> connection will be lost."
        # Добавляем результат СРАЗУ, чтобы успеть отправить до ребута
        RESULTS_QUEUE.append({
            "user_id": user_id,
            "command": cmd,
            "result": output
        })
        # Форсируем отправку перед смертью
        send_heartbeat()
        logging.warning("REBOOTING SYSTEM...")
        os.system("(sleep 3 && /sbin/reboot) &")
        return # Уже отправили
    else:
        output = f"⚠️ Unknown command: {cmd}"

    if output:
        RESULTS_QUEUE.append({
            "user_id": user_id,
            "command": cmd,
            "result": output
        })

def get_stats_short():
    """Легкая статистика для хартбита."""
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent,
        "uptime": get_uptime_str()
    }

def send_heartbeat():
    """Отправляет данные и результаты выполнения команд на Агент."""
    global RESULTS_QUEUE
    
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    stats = get_stats_short()
    
    payload = {
        "token": AGENT_TOKEN,
        "stats": stats,
        "results": RESULTS_QUEUE # Отправляем накопленные ответы
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            # Если успешно отправили - очищаем очередь результатов
            if RESULTS_QUEUE:
                logging.info(f"Sent {len(RESULTS_QUEUE)} command results.")
                RESULTS_QUEUE = []
            
            data = response.json()
            # Выполняем новые задачи
            tasks = data.get("tasks", [])
            for task in tasks:
                perform_task(task)
        else:
            logging.error(f"Server returned {response.status_code}: {response.text}")
            
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection failed to {AGENT_BASE_URL}")
    except Exception as e:
        logging.error(f"Heartbeat error: {e}")

def main():
    if not AGENT_TOKEN:
        logging.critical("AGENT_TOKEN is missing in .env!")
        return

    logging.info(f"Node started. Target: {AGENT_BASE_URL}")
    
    # Первый прогон для инициализации psutil
    psutil.cpu_percent(interval=None)

    while True:
        send_heartbeat()
        time.sleep(NODE_UPDATE_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass