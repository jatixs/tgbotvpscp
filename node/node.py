import time
import json
import psutil
import requests
import logging
import os
import sys
import subprocess
import shlex
import random
import re 

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

# Хранилище результатов и состояний
PENDING_RESULTS = []
LAST_TRAFFIC_STATS = {}

# --- УТИЛИТЫ ДЛЯ ФОРМАТИРОВАНИЯ ---
def format_uptime_simple(seconds):
    seconds = int(seconds)
    d, s = divmod(seconds, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d > 0: parts.append(f"{d}d")
    if h > 0: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)

def format_bytes_simple(bytes_value):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    value = float(bytes_value)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"
# -----------------------------------

# Utility function to safely parse speed from iperf3 output (plain text)
def parse_iperf_speed(output: str, direction: str) -> float:
    """
    Парсит вывод iperf3 для нахождения скорости передачи.
    direction: 'sender' (для Upload) или 'receiver' (для Download).
    """
    for line in reversed(output.splitlines()):
        if "Mbits/sec" in line and (direction in line or direction == 'sender'):
            speed_match = re.search(r"(\d+\.?\d*)\s+Mbits/sec", line)
            if speed_match:
                return float(speed_match.group(1))
    
    fallback_match = re.findall(r"(\d+\.?\d*)\s+Mbits/sec", output)
    if fallback_match:
        return float(fallback_match[-1])
        
    return 0.0

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

def get_public_iperf_server():
    """Получает список публичных iperf3 серверов и выбирает случайный."""
    try:
        url = "https://export.iperf3serverlist.net/listed_iperf3_servers.json"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            servers = response.json()
            valid_servers = [s for s in servers if s.get("IP/HOST") and s.get("PORT") and s.get("COUNTRY") != "RU"]
            if valid_servers:
                return random.choice(valid_servers)
    except Exception as e:
        logging.error(f"Error fetching iperf servers: {e}")
    return None

def execute_command(task):
    global LAST_TRAFFIC_STATS
    cmd = task.get("command")
    user_id = task.get("user_id")
    logging.info(f"Executing command: {cmd}")

    result_text = ""
    try:
        if cmd == "uptime":
            uptime_sec = int(time.time() - psutil.boot_time())
            result_text = f"⏱ Uptime: {format_uptime_simple(uptime_sec)}"

        elif cmd == "traffic":
            net = psutil.net_io_counters()
            now = time.time()
            
            rx_total = format_bytes_simple(net.bytes_recv)
            tx_total = format_bytes_simple(net.bytes_sent)
            
            speed_info = ""
            
            if LAST_TRAFFIC_STATS:
                prev_rx = LAST_TRAFFIC_STATS.get('rx', 0)
                prev_tx = LAST_TRAFFIC_STATS.get('tx', 0)
                prev_time = LAST_TRAFFIC_STATS.get('time', 0)
                
                dt = now - prev_time
                if dt > 0:
                    rx_speed = (net.bytes_recv - prev_rx) * 8 / (1024 * 1024) / dt
                    tx_speed = (net.bytes_sent - prev_tx) * 8 / (1024 * 1024) / dt
                    speed_info = f"\n\n⚡️ <b>Скорость:</b>\n⬇️ {rx_speed:.2f} Mbit/s\n⬆️ {tx_speed:.2f} Mbit/s"

            LAST_TRAFFIC_STATS = {
                'rx': net.bytes_recv,
                'tx': net.bytes_sent,
                'time': now
            }
            
            result_text = f"📡 <b>Traffic:</b>\n⬇️ Total RX: {rx_total}\n⬆️ Total TX: {tx_total}{speed_info}"

        elif cmd == "top":
            try:
                res = subprocess.check_output(
                    "ps aux --sort=-%cpu | head -n 11", shell=True).decode()
                
                # --- ИСПРАВЛЕНИЕ: Экранирование HTML ---
                # Заменяем символы <, >, & на безопасные сущности, 
                # чтобы Telegram не пытался их парсить как теги.
                safe_res = res.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                result_text = f"<pre>{safe_res}</pre>"
                # ---------------------------------------
                
            except Exception as e:
                result_text = f"Error running top: {e}"

        elif cmd == "selftest":
            stats = get_system_stats()
            
            # --- Сбор дополнительной информации ---
            try:
                ip_res = subprocess.check_output("curl -4 -s --max-time 2 ifconfig.me", shell=True).decode().strip()
                ext_ip = ip_res or "N/A"
            except:
                ext_ip = "N/A"
                
            try:
                ping_res = subprocess.check_output("ping -c 1 -W 1 8.8.8.8", shell=True).decode()
                ping_match = re.search(r"time=([\d\.]+) ms", ping_res)
                ping_status = f"🔗 {ping_match.group(1)} ms" if ping_match else "🔗 ❌ Fail"
            except:
                ping_status = "🔗 ❌ Fail"

            try:
                kernel = subprocess.check_output("uname -r", shell=True).decode().strip()
            except:
                kernel = "N/A"
            # --------------------------------------
            
            uptime_str = format_uptime_simple(stats.get('uptime', 0))
            rx_total = format_bytes_simple(stats.get('net_rx', 0))
            tx_total = format_bytes_simple(stats.get('net_tx', 0))
            
            result_text = (
                f"🛠 <b>Server Info:</b>\n\n"
                f"✅ Node Status: <b>Active</b>\n"
                f"⏱ Uptime: <b>{uptime_str}</b>\n"
                f"📦 OS/Kernel: {kernel}\n"
                f"🌐 External IP: <code>{ext_ip}</code>\n"
                f"📡 {ping_status}\n\n"
                f"📊 <b>Resources:</b>\n"
                f"  CPU: <b>{stats.get('cpu', 0):.1f}%</b>\n"
                f"  RAM: <b>{stats.get('ram', 0):.1f}%</b>\n"
                f"  Disk: <b>{stats.get('disk', 0):.1f}%</b>\n\n"
                f"📈 <b>Traffic (Total):</b>\n"
                f"  ⬇️ RX: {rx_total}\n"
                f"  ⬆️ TX: {tx_total}"
            )

        elif cmd == "speedtest":
            server = get_public_iperf_server()
            if server:
                host = server.get("IP/HOST")
                port = server.get("PORT")
                city = server.get("SITE", "Unknown")
                country = server.get("COUNTRY", "")
                
                # --- FIX FOR BANDIT B602 (shell=True) ---
                # Use list of arguments instead of string, remove shlex.quote, remove shell=True
                
                # --- RUNNING DOWNLOAD TEST (-R, client receives) ---
                cmd_dl = ["iperf3", "-c", host, "-p", str(port), "-t", "5", "-4", "-R"]
                try:
                    res_dl = subprocess.check_output(
                        cmd_dl, stderr=subprocess.STDOUT, timeout=20).decode()
                    dl_speed = parse_iperf_speed(res_dl, 'receiver')
                except subprocess.TimeoutExpired:
                    dl_speed = 0.0
                except Exception as e:
                    logging.error(f"DL Test failed: {e}")
                    dl_speed = 0.0
                
                # --- RUNNING UPLOAD TEST (default, client sends) ---
                cmd_ul = ["iperf3", "-c", host, "-p", str(port), "-t", "5", "-4"]
                try:
                    res_ul = subprocess.check_output(
                        cmd_ul, stderr=subprocess.STDOUT, timeout=20).decode()
                    ul_speed = parse_iperf_speed(res_ul, 'sender')
                except subprocess.TimeoutExpired:
                    ul_speed = 0.0
                except Exception as e:
                    logging.error(f"UL Test failed: {e}")
                    ul_speed = 0.0
                
                if dl_speed == 0.0 and ul_speed == 0.0:
                    raise Exception("iperf3 returned zero speed or failed to parse.")
                    
                result_text = (f"🚀 <b>Speedtest (iperf3)</b>\n"
                               f"🌍 Server: {city}, {country} ({host})\n"
                               f"⬇️ <b>Download:</b> {dl_speed:.2f} Mbit/s\n"
                               f"⬆️ <b>Upload:</b> {ul_speed:.2f} Mbit/s\n\n"
                               f"iPerf Done.")
            else:
                try:
                    res = subprocess.check_output("ping -c 3 8.8.8.8", shell=True).decode()
                    result_text = f"⚠️ iperf3 servers unavailable. Ping check:\n<pre>{res}</pre>"
                except Exception as e:
                    result_text = f"Network check failed: {e}"

        elif cmd == "reboot":
            result_text = "🔄 Reboot command received. Rebooting..."
            PENDING_RESULTS.append(
                {"command": cmd, "user_id": user_id, "result": result_text})
            send_heartbeat()
            os.system("reboot")
            return

        else:
            result_text = f"Unknown command: {cmd}"

    except subprocess.TimeoutExpired:
        result_text = "❌ Speedtest timed out (server busy or test too long)."
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
            PENDING_RESULTS = []

            tasks = data.get("tasks", [])
            for task in tasks:
                execute_command(task)
        else:
            logging.warning(f"Server returned status: {response.status_code}")
    except Exception as e:
        logging.error(f"Connection error: {e}")

def main():
    logging.info(f"Node Agent started. Target: {AGENT_BASE_URL}")
    psutil.cpu_percent(interval=None)

    while True:
        send_heartbeat()
        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    main()
