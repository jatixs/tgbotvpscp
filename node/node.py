import time
import psutil
import requests
import logging
import os
import sys
import subprocess
import random
import re
import hmac
import hashlib
import json
import collections
from datetime import datetime

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
DEBUG_MODE = CONF.get("DEBUG", "false").lower() == "true"

class RedactingFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        if DEBUG_MODE:
            return msg
        
        msg = re.sub(r'\b[a-fA-F0-9]{32,64}\b', '[TOKEN_REDACTED]', msg)
        msg = re.sub(r'\b(?!(?:127\.0\.0\.1|0\.0\.0\.0|localhost))(?:\d{1,3}\.){3}\d{1,3}\b', '[IP_REDACTED]', msg)
        msg = re.sub(r'\b(id|user_id|chat_id|user)=(\d+)\b', r'\1=[ID_REDACTED]', msg)
        msg = re.sub(r'@[\w_]{5,}', '@[USERNAME_REDACTED]', msg)
        
        return msg

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)

# Путь к логам лучше брать относительно текущей директории или из конфига,
# но оставим жесткий путь как в оригинале, если структура папок сохраняется.
LOG_FILE_PATH = "/opt/tg-bot/logs/node/node.log"
# Создаем директорию логов, если её нет (на случай ручного запуска)
try:
    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
except Exception:
    pass

file_handler = logging.FileHandler(LOG_FILE_PATH)
stream_handler = logging.StreamHandler()

formatter = RedactingFormatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

if logger.hasHandlers():
    logger.handlers.clear()

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

AGENT_BASE_URL = CONF.get("AGENT_BASE_URL")
AGENT_TOKEN = CONF.get("AGENT_TOKEN")
UPDATE_INTERVAL = int(CONF.get("NODE_UPDATE_INTERVAL", 5))

if not AGENT_BASE_URL or not AGENT_TOKEN:
    logging.error("CRITICAL: AGENT_BASE_URL or AGENT_TOKEN not found in .env")
    sys.exit(1)

PENDING_RESULTS = []
LAST_TRAFFIC_STATS = {}
SSH_EVENTS = []

EXTERNAL_IP_CACHE = None 

class SSHMonitor:
    def __init__(self):
        self.log_files = ["/var/log/auth.log", "/var/log/secure"]
        self.current_file = None
        self.file_handle = None
        self.inode = None
        self.processed_lines = collections.deque(maxlen=100)
        self._open_log_file()
        if self.file_handle:
            self.file_handle.seek(0, 2)

    def _open_log_file(self):
        for log_path in self.log_files:
            if os.path.exists(log_path):
                try:
                    f = open(log_path, 'r', encoding='utf-8', errors='ignore')
                    self.current_file = log_path
                    self.file_handle = f
                    st = os.fstat(f.fileno())
                    self.inode = st.st_ino
                    logging.info(f"SSH Monitor watching: {log_path}")
                    return
                except Exception as e:
                    logging.error(f"Error opening SSH log {log_path}: {e}")
        logging.warning("No SSH log files found (auth.log/secure).")

    def check(self):
        if not self.file_handle:
            return []

        try:
            if not os.path.exists(self.current_file):
                self.file_handle.close()
                self._open_log_file()
                return []
            
            st = os.stat(self.current_file)
            if st.st_ino != self.inode or st.st_size < self.file_handle.tell():
                logging.info("Log rotation detected. Reopening.")
                self.file_handle.close()
                self._open_log_file()
                return []
        except Exception:
            pass

        events = []
        try:
            while True:
                line = self.file_handle.readline()
                if not line:
                    break
                
                if line in self.processed_lines:
                    continue
                self.processed_lines.append(line)
                if "Accepted" in line and "ssh" in line:
                    match = re.search(r"Accepted\s+(password|publickey)\s+for\s+(\S+)\s+from\s+(\S+)", line)
                    if match:
                        method = match.group(1)
                        user = match.group(2)
                        ip = match.group(3)
                        
                        try:
                            tz_offset = time.strftime('%z')
                            tz_label = f"GMT{tz_offset[:3]}:{tz_offset[3:]}" if tz_offset else "GMT"
                        except:
                            tz_label = "GMT"

                        events.append({
                            "user": user,
                            "ip": ip,
                            "method": method,
                            "timestamp": int(time.time()),
                            "node_time_str": time.strftime('%H:%M:%S'),
                            "tz_label": tz_label
                        })
        except Exception as e:
            logging.error(f"Error parsing SSH log: {e}")
        
        return events

def get_external_ip():
    global EXTERNAL_IP_CACHE
    if EXTERNAL_IP_CACHE:
        return EXTERNAL_IP_CACHE

    services = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
        "https://ipecho.net/plain",
        "http://checkip.amazonaws.com"
    ]

    for service in services:
        try:
            response = requests.get(service, timeout=5)
            if response.status_code == 200:
                ip = response.text.strip()
                if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                    EXTERNAL_IP_CACHE = ip
                    logging.info(f"External IP updated: {ip}")
                    return ip
        except Exception:
            continue
    
    try:
        res = subprocess.check_output("curl -4 -s --max-time 5 ifconfig.me", shell=True).decode().strip()
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", res):
            EXTERNAL_IP_CACHE = res
            logging.info(f"External IP updated (curl): {res}")
            return res
    except Exception:
        pass

    logging.warning("Could not determine external IP locally. Delegating to Agent Server.")
    return None

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

def parse_iperf_speed(output: str, direction: str) -> float:
    for line in reversed(output.splitlines()):
        if "Mbits/sec" in line and (direction in line or direction == 'sender'):
            speed_match = re.search(r"(\d+\.?\d*)\s+Mbits/sec", line)
            if speed_match:
                return float(speed_match.group(1))
    
    fallback_match = re.findall(r"(\d+\.?\d*)\s+Mbits/sec", output)
    if fallback_match:
        return float(fallback_match[-1])
        
    return 0.0

def get_top_processes(metric):
    try:
        attrs = ['pid', 'name', 'cpu_percent', 'memory_percent']
        procs = []
        for p in psutil.process_iter(attrs):
            try:
                p.info['name'] = p.info['name'][:15]
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        if metric == 'cpu':
            sorted_procs = sorted(procs, key=lambda p: p['cpu_percent'], reverse=True)[:3]
            info_list = [f"{p['name']} ({p['cpu_percent']}%)" for p in sorted_procs]
        elif metric == 'ram':
            sorted_procs = sorted(procs, key=lambda p: p['memory_percent'], reverse=True)[:3]
            info_list = [f"{p['name']} ({p['memory_percent']:.1f}%)" for p in sorted_procs]
        else:
            return ""

        return ", ".join(info_list)
    except Exception as e:
        logging.error(f"Error getting top processes: {e}")
        return "n/a"

def get_system_stats():
    try:
        net = psutil.net_io_counters()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        freq = psutil.cpu_freq()
        
        ext_ip = get_external_ip()
        
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": mem.percent,
            "disk": disk.percent,
            "ram_total": mem.total,
            "ram_free": mem.available,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "cpu_freq": freq.current if freq else 0,
            "net_rx": net.bytes_recv,
            "net_tx": net.bytes_sent,
            "uptime": int(time.time() - psutil.boot_time()),
            "process_cpu": get_top_processes('cpu'),
            "process_ram": get_top_processes('ram'),
            "external_ip": ext_ip
        }
    except Exception as e:
        logging.error(f"Error gathering stats: {e}")
        return {}

def get_public_iperf_server():
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

    result_payload = None
    try:
        if cmd == "uptime":
            uptime_sec = int(time.time() - psutil.boot_time())
            result_payload = {
                "type": "i18n",
                "key": "uptime_text",
                "params": {
                    "uptime": format_uptime_simple(uptime_sec)
                }
            }

        elif cmd == "traffic":
            net = psutil.net_io_counters()
            now = time.time()
            
            rx_total = format_bytes_simple(net.bytes_recv)
            tx_total = format_bytes_simple(net.bytes_sent)
            
            speed_rx_val = "0.00"
            speed_tx_val = "0.00"
            
            if LAST_TRAFFIC_STATS:
                prev_rx = LAST_TRAFFIC_STATS.get('rx', 0)
                prev_tx = LAST_TRAFFIC_STATS.get('tx', 0)
                prev_time = LAST_TRAFFIC_STATS.get('time', 0)
                
                dt = now - prev_time
                if dt > 0:
                    rx_speed = (net.bytes_recv - prev_rx) * 8 / (1024 * 1024) / dt
                    tx_speed = (net.bytes_sent - prev_tx) * 8 / (1024 * 1024) / dt
                    speed_rx_val = f"{rx_speed:.2f}"
                    speed_tx_val = f"{tx_speed:.2f}"

            LAST_TRAFFIC_STATS = {
                'rx': net.bytes_recv,
                'tx': net.bytes_sent,
                'time': now
            }
            
            result_payload = {
                "type": "i18n",
                "key": "traffic_report_node", 
                "params": {
                    "rx": rx_total,
                    "tx": tx_total,
                    "speed_rx": speed_rx_val,
                    "speed_tx": speed_tx_val
                }
            }

        elif cmd == "top":
            try:
                res = subprocess.check_output(
                    "ps aux --sort=-%cpu | head -n 11", shell=True).decode()
                
                safe_res = res.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                result_payload = {
                    "type": "i18n",
                    "key": "top_header",
                    "params": {
                        "output": safe_res
                    }
                }
                
            except Exception as e:
                result_payload = {
                    "type": "i18n", 
                    "key": "error_with_details", 
                    "params": {"error": str(e)}
                }

        elif cmd == "selftest":
            stats = get_system_stats()
            try:
                ext_ip = stats.get("external_ip")
                if not ext_ip:
                     ext_ip = subprocess.check_output("curl -4 -s --max-time 2 ifconfig.me", shell=True).decode().strip()
            except Exception:
                ext_ip = "N/A"
            
            ping_val = "0"
            inet_ok = False
            try:
                ping_res = subprocess.check_output("ping -c 1 -W 1 8.8.8.8", shell=True).decode()
                ping_match = re.search(r"time=([\d\.]+) ms", ping_res)
                if ping_match:
                    ping_val = ping_match.group(1)
                    inet_ok = True
            except Exception:
                pass

            try:
                kernel = subprocess.check_output("uname -r", shell=True).decode().strip()
            except Exception:
                kernel = "N/A"
            
            uptime_str = format_uptime_simple(stats.get('uptime', 0))
            rx_total = format_bytes_simple(stats.get('net_rx', 0))
            tx_total = format_bytes_simple(stats.get('net_tx', 0))
            
            result_payload = {
                "type": "i18n",
                "key": "selftest_results_body",
                "params": {
                    "cpu": stats.get('cpu', 0),
                    "mem": stats.get('ram', 0),
                    "disk": stats.get('disk', 0),
                    "uptime": uptime_str,
                    "inet_status": {"key": "selftest_inet_ok"} if inet_ok else {"key": "selftest_inet_fail"},
                    "ping": ping_val,
                    "ip": ext_ip,
                    "rx": rx_total,
                    "tx": tx_total
                }
            }

        elif cmd == "speedtest":
            server = get_public_iperf_server()
            if server:
                host = server.get("IP/HOST")
                port = server.get("PORT")
                city = server.get("SITE", "Unknown")
                country = server.get("COUNTRY", "")
                
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
                    
                result_payload = {
                    "type": "i18n",
                    "key": "speedtest_results",
                    "params": {
                        "dl": dl_speed,
                        "ul": ul_speed,
                        "ping": 0,
                        "flag": "",
                        "server": f"{city}, {country}",
                        "provider": host
                    }
                }
            else:
                try:
                    res = subprocess.check_output("ping -c 3 8.8.8.8", shell=True).decode()
                    result_payload = {
                        "type": "i18n",
                        "key": "error_with_details",
                        "params": {"error": f"iperf3 unavailable. Ping check:\n{res}"}
                    }
                except Exception as e:
                    result_payload = {
                        "type": "i18n",
                        "key": "error_with_details",
                        "params": {"error": f"Network check failed: {e}"}
                    }

        elif cmd == "reboot":
            result_payload = {
                "type": "i18n",
                "key": "reboot_confirmed",
                "params": {}
            }
            PENDING_RESULTS.append(
                {"command": cmd, "user_id": user_id, "result": result_payload})
            send_heartbeat()
            os.system("reboot")
            return

        else:
            result_payload = {
                "type": "i18n", 
                "key": "error_with_details", 
                "params": {"error": f"Unknown command: {cmd}"}
            }

    except subprocess.TimeoutExpired:
        result_payload = {
            "type": "i18n",
            "key": "error_with_details",
            "params": {"error": "Speedtest timed out."}
        }
    except Exception as e:
        logging.error(f"Command execution failed: {e}")
        result_payload = {
            "type": "i18n",
            "key": "error_with_details",
            "params": {"error": str(e)}
        }

    if result_payload:
        PENDING_RESULTS.append({
            "command": cmd,
            "user_id": user_id,
            "result": result_payload
        })

def send_heartbeat():
    global PENDING_RESULTS, SSH_EVENTS
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    
    current_ssh_events = SSH_EVENTS[:]
    
    payload_dict = {
        "token": AGENT_TOKEN,
        "stats": get_system_stats(),
        "results": PENDING_RESULTS,
        "ssh_logins": current_ssh_events,
        "timestamp": int(time.time())
    }
    
    payload_bytes = json.dumps(payload_dict, sort_keys=True).encode('utf-8')
    
    signature = hmac.new(AGENT_TOKEN.encode(), payload_bytes, hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature
    }

    try:
        response = requests.post(url, data=payload_bytes, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            PENDING_RESULTS = []
            
            if current_ssh_events:
                 SSH_EVENTS = SSH_EVENTS[len(current_ssh_events):]

            tasks = data.get("tasks", [])
            for task in tasks:
                execute_command(task)
        else:
            logging.warning(f"Server returned status: {response.status_code} {response.text}")
    except Exception as e:
        logging.error(f"Connection error: {e}")

def main():
    logging.info(f"Node Agent started. Target: {AGENT_BASE_URL}. Mode: {'DEBUG' if DEBUG_MODE else 'RELEASE'}")
    psutil.cpu_percent(interval=None)
    get_external_ip()
    
    ssh_monitor = SSHMonitor()

    while True:
        new_events = ssh_monitor.check()
        if new_events:
            logging.info(f"Found {len(new_events)} SSH login events.")
            SSH_EVENTS.extend(new_events)

        send_heartbeat()
        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    main()