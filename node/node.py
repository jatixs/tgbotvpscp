import os
import time
import json
import logging
import requests
import psutil
import subprocess
import threading
from logging.handlers import RotatingFileHandler
from queue import Queue, Empty

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

# Очередь для результатов, которые нужно отправить Агенту
RESULTS_QUEUE = []
RESULTS_LOCK = threading.Lock()

# Словарь для отслеживания времени последнего обновления по каждой задаче (для троттлинга)
# Key: (user_id, command), Value: timestamp
LAST_UPDATE_TIME = {}
UPDATE_THROTTLE_SEC = 2.0

def add_result(user_id, command, result, is_final=False):
    """Добавляет результат в очередь с учетом троттлинга."""
    key = (user_id, command)
    now = time.time()
    last = LAST_UPDATE_TIME.get(key, 0)

    # Если это не финальный результат и прошло мало времени, пропускаем (кроме самого первого)
    if not is_final and (now - last < UPDATE_THROTTLE_SEC) and last != 0:
        return

    with RESULTS_LOCK:
        # Удаляем предыдущие промежуточные статусы этой же команды для этого юзера, чтобы не спамить
        # Оставляем только если это разные команды
        # Но проще просто добавить, а сервер разберется. 
        # Для оптимизации трафика можно заменять последний элемент, если он для того же юзера/команды.
        RESULTS_QUEUE.append({
            "user_id": user_id,
            "command": command,
            "result": result,
            "is_final": is_final
        })
    
    LAST_UPDATE_TIME[key] = now
    
    # Если финальный, удаляем из трекера времени
    if is_final:
        LAST_UPDATE_TIME.pop(key, None)
        # Форсируем отправку хартбита
        # (В простой реализации ждем следующего цикла, чтобы не усложнять)

def get_uptime_str():
    uptime_seconds = time.time() - psutil.boot_time()
    days = int(uptime_seconds // (24 * 3600))
    hours = int((uptime_seconds % (24 * 3600)) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    return f"{days}d {hours}h {minutes}m"

def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"

# --- Команды (выполняются в потоках) ---

def run_selftest(user_id):
    add_result(user_id, "selftest", "🔍 <b>Collecting info...</b>")
    
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    uptime = get_uptime_str()
    try:
        ip = requests.get("https://api.ipify.org", timeout=2).text
    except:
        ip = "Unknown"

    res = (
        f"🛠 <b>Node System Status:</b>\n\n"
        f"📊 CPU: <b>{cpu:.1f}%</b>\n"
        f"💾 RAM: <b>{mem:.1f}%</b>\n"
        f"💽 Disk: <b>{disk:.1f}%</b>\n"
        f"⏱ Uptime: <b>{uptime}</b>\n"
        f"🌐 IP: <code>{ip}</code>"
    )
    add_result(user_id, "selftest", res, is_final=True)

def run_top(user_id):
    try:
        cmd = "ps aux --sort=-%cpu | head -n 11"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        if len(result) > 3000: result = result[:3000] + "\n..."
        res = f"🔥 <b>Top Processes:</b>\n<pre>{result}</pre>"
    except Exception as e:
        res = f"Error running top: {e}"
    add_result(user_id, "top", res, is_final=True)

def run_traffic(user_id):
    add_result(user_id, "traffic", "📡 <b>Measuring traffic (1s)...</b>")
    try:
        c1 = psutil.net_io_counters()
        time.sleep(1)
        c2 = psutil.net_io_counters()
        
        rx_speed = c2.bytes_recv - c1.bytes_recv
        tx_speed = c2.bytes_sent - c1.bytes_sent
        
        res = (
            f"📡 <b>Network Traffic:</b>\n"
            f"⬇️ Total RX: {format_bytes(c2.bytes_recv)}\n"
            f"⬆️ Total TX: {format_bytes(c2.bytes_sent)}\n\n"
            f"⚡️ <b>Speed (1 sec):</b>\n"
            f"⬇️ {format_bytes(rx_speed)}/s\n"
            f"⬆️ {format_bytes(tx_speed)}/s"
        )
    except Exception as e:
        res = f"Error: {e}"
    add_result(user_id, "traffic", res, is_final=True)

def run_speedtest(user_id):
    # Этапы обновления, чтобы пользователь не скучал
    server = "ping.online.net" 
    port = "5209"
    
    try:
        add_result(user_id, "speedtest", f"🚀 <b>Speedtest:</b> Connecting to {server}...")
        
        # 1. Download
        add_result(user_id, "speedtest", f"🚀 <b>Speedtest:</b> ⬇️ Downloading...")
        cmd_dl = f"iperf3 -c {server} -p {port} -t 5 -R -4 --json"
        res_dl = subprocess.run(cmd_dl, shell=True, capture_output=True, text=True)
        
        dl_speed_str = "Error"
        if res_dl.returncode == 0:
            try:
                json_dl = json.loads(res_dl.stdout)
                val = json_dl['end']['sum_received']['bits_per_second'] / 1_000_000
                dl_speed_str = f"{val:.2f} Mbps"
            except: pass
        
        # 2. Upload
        add_result(user_id, "speedtest", f"🚀 <b>Speedtest:</b> ⬇️ DL: {dl_speed_str} | ⬆️ Uploading...")
        cmd_ul = f"iperf3 -c {server} -p {port} -t 5 -4 --json"
        res_ul = subprocess.run(cmd_ul, shell=True, capture_output=True, text=True)
        
        ul_speed_str = "Error"
        if res_ul.returncode == 0:
            try:
                json_ul = json.loads(res_ul.stdout)
                val = json_ul['end']['sum_sent']['bits_per_second'] / 1_000_000
                ul_speed_str = f"{val:.2f} Mbps"
            except: pass
            
        final_res = (
            f"🚀 <b>Speedtest Results ({server}):</b>\n\n"
            f"⬇️ <b>Download:</b> {dl_speed_str}\n"
            f"⬆️ <b>Upload:</b> {ul_speed_str}"
        )
        add_result(user_id, "speedtest", final_res, is_final=True)

    except FileNotFoundError:
        add_result(user_id, "speedtest", "⚠️ <b>iperf3</b> not found. Install it: <code>apt install iperf3</code>", is_final=True)
    except Exception as e:
        add_result(user_id, "speedtest", f"⚠️ Speedtest failed: {e}", is_final=True)

def run_reboot(user_id):
    add_result(user_id, "reboot", "🔄 <b>Node is rebooting...</b> connection will be lost.", is_final=True)
    # Форсируем отправку в главном потоке (через хартбит), но здесь просто ждем немного
    time.sleep(2) 
    logging.warning("REBOOTING SYSTEM...")
    os.system("sbin/reboot")

def start_task_thread(task):
    cmd = task.get("command")
    user_id = task.get("user_id")
    
    if cmd == "selftest":
        threading.Thread(target=run_selftest, args=(user_id,), daemon=True).start()
    elif cmd == "top":
        threading.Thread(target=run_top, args=(user_id,), daemon=True).start()
    elif cmd == "traffic":
        threading.Thread(target=run_traffic, args=(user_id,), daemon=True).start()
    elif cmd == "speedtest":
        threading.Thread(target=run_speedtest, args=(user_id,), daemon=True).start()
    elif cmd == "reboot":
        # Reboot запускаем в отдельном потоке, но с задержкой
        threading.Thread(target=run_reboot, args=(user_id,), daemon=True).start()
    else:
        add_result(user_id, cmd, f"⚠️ Unknown command: {cmd}", is_final=True)

def get_stats_short():
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent,
        "uptime": get_uptime_str()
    }

def send_heartbeat():
    global RESULTS_QUEUE
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    stats = get_stats_short()
    
    # Забираем результаты из очереди атомарно
    results_to_send = []
    with RESULTS_LOCK:
        if RESULTS_QUEUE:
            results_to_send = list(RESULTS_QUEUE)
            RESULTS_QUEUE.clear()
    
    payload = {
        "token": AGENT_TOKEN,
        "stats": stats,
        "results": results_to_send
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            tasks = data.get("tasks", [])
            for task in tasks:
                logging.info(f"Received task: {task['command']}")
                start_task_thread(task)
        else:
            logging.error(f"Agent error: {response.status_code} - {response.text}")
            # Если ошибка, возвращаем результаты в очередь (в начало), чтобы не потерять
            if results_to_send:
                with RESULTS_LOCK:
                    RESULTS_QUEUE[0:0] = results_to_send

    except requests.exceptions.ConnectionError:
        logging.error(f"Cannot connect to Agent at {AGENT_BASE_URL}")
        if results_to_send:
            with RESULTS_LOCK:
                RESULTS_QUEUE[0:0] = results_to_send
    except Exception as e:
        logging.error(f"Heartbeat error: {e}")
        if results_to_send:
            with RESULTS_LOCK:
                RESULTS_QUEUE[0:0] = results_to_send

def main():
    if not AGENT_TOKEN:
        logging.critical("AGENT_TOKEN missing in .env")
        return

    logging.info(f"Node started. Agent: {AGENT_BASE_URL}")
    psutil.cpu_percent(interval=None)

    while True:
        send_heartbeat()
        time.sleep(NODE_UPDATE_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass