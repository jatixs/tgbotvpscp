import time
import json
import psutil
import requests
import logging
import os
import sys
import subprocess
import shlex

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/opt/tg-bot/logs/node/node.log"),
        logging.StreamHandler()
    ]
)

# Загрузка конфигурации
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, '.env')


def load_config():
    config = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip().strip('"').strip("'")
                    config[key.strip()] = value
    return config


CONF = load_config()
AGENT_BASE_URL = CONF.get("AGENT_BASE_URL")
AGENT_TOKEN = CONF.get("AGENT_TOKEN")
UPDATE_INTERVAL = int(CONF.get("NODE_UPDATE_INTERVAL", 5))

if not AGENT_BASE_URL or not AGENT_TOKEN:
    logging.error("CRITICAL: AGENT_BASE_URL or AGENT_TOKEN not found in .env")
    sys.exit(1)

# Хранилище результатов команд для отправки
PENDING_RESULTS = []


def get_system_stats():
    try:
        net = psutil.net_io_counters()
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent,
            "net_rx": net.bytes_recv,
            "net_tx": net.bytes_sent,
            "uptime": int(time.time() - psutil.boot_time())
        }
    except Exception as e:
        logging.error(f"Error gathering stats: {e}")
        return {}


def execute_command(task):
    cmd = task.get("command")
    user_id = task.get("user_id")
    logging.info(f"Executing command: {cmd}")

    result_text = ""
    try:
        if cmd == "uptime":
            uptime_sec = int(time.time() - psutil.boot_time())
            m, s = divmod(uptime_sec, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            result_text = f"⏱ Uptime: {d}d {h}h {m}m"

        elif cmd == "traffic":
            net = psutil.net_io_counters()
            rx_mb = net.bytes_recv / (1024 * 1024)
            tx_mb = net.bytes_sent / (1024 * 1024)
            result_text = f"📡 Traffic:\n⬇️ RX: {rx_mb:.2f} MB\n⬆️ TX: {tx_mb:.2f} MB"

        elif cmd == "top":
            # Вывод топ 10 процессов по CPU
            try:
                res = subprocess.check_output(
                    "ps aux --sort=-%cpu | head -n 11", shell=True).decode()
                result_text = f"<pre>{res}</pre>"
            except Exception as e:
                result_text = f"Error running top: {e}"

        elif cmd == "selftest":
            # Краткая сводка
            stats = get_system_stats()
            result_text = (
                f"✅ Node Active\n"
                f"CPU: {stats.get('cpu')}% | RAM: {stats.get('ram')}%\n"
                f"Disk: {stats.get('disk')}%")

        elif cmd == "speedtest":
            # Запуск iperf3 клиента (требуется публичный сервер, здесь упрощенно ping 8.8.8.8)
            # Для полноценного теста нужно знать сервер iperf3.
            # Пока реализуем ping как базовую проверку сети.
            try:
                res = subprocess.check_output(
                    "ping -c 3 8.8.8.8", shell=True).decode()
                result_text = f"🚀 Network Check (Ping 8.8.8.8):\n<pre>{res}</pre>"
            except Exception as e:
                result_text = f"Ping error: {e}"

        elif cmd == "reboot":
            result_text = "🔄 Reboot command received. Rebooting..."
            # Добавляем результат перед ребутом
            PENDING_RESULTS.append(
                {"command": cmd, "user_id": user_id, "result": result_text})
            send_heartbeat()  # Попытка отправить ответ сразу
            os.system("reboot")
            return

        else:
            result_text = f"Unknown command: {cmd}"

    except Exception as e:
        logging.error(f"Command execution failed: {e}")
        result_text = f"❌ Error: {str(e)}"

    if result_text:
        PENDING_RESULTS.append({
            "command": cmd,
            "user_id": user_id,
            "result": result_text
        })


def send_heartbeat():
    global PENDING_RESULTS
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    payload = {
        "token": AGENT_TOKEN,
        "stats": get_system_stats(),
        "results": PENDING_RESULTS
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Очищаем отправленные результаты только при успехе
            PENDING_RESULTS = []

            # Обработка задач от сервера
            tasks = data.get("tasks", [])
            for task in tasks:
                execute_command(task)
        else:
            logging.warning(f"Server returned status: {response.status_code}")
    except Exception as e:
        logging.error(f"Connection error: {e}")


def main():
    logging.info(f"Node Agent started. Target: {AGENT_BASE_URL}")
    # Первый запуск psutil для инициализации счетчиков CPU
    psutil.cpu_percent(interval=None)

    while True:
        send_heartbeat()
        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
