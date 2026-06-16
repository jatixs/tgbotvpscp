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
import html
import collections
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, '.env')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
SPEEDTEST_MODE_FILE = os.path.join(CONFIG_DIR, '.speedtest_mode')
os.makedirs(CONFIG_DIR, exist_ok=True)

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


def get_env_value(var_name):
    if not os.path.exists(ENV_FILE):
        return ""

    try:
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() == var_name:
                        return value.strip().strip('"').strip("'")
    except Exception:
        return ""

    return ""


def upsert_env_value(var_name, value):
    safe_value = str(value or "").replace('\r', ' ').replace('\n', ' ')
    new_line = f'{var_name}="{safe_value}"\n'
    lines = []
    found = False

    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key == var_name:
                lines[idx] = new_line
                found = True
                break

    if not found:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(new_line)

    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def sync_node_name_from_agent(agent_node_name):
    normalized_name = str(agent_node_name or '').strip()
    if not normalized_name:
        return

    current_node_name = get_env_value('NODE_NAME').strip()
    sync_mode = get_env_value('NODE_NAME_SYNC_MODE').strip().lower()
    should_sync = sync_mode == 'agent' or not current_node_name

    if not should_sync:
        if current_node_name:
            CONF['NODE_NAME'] = current_node_name
        return

    if current_node_name == normalized_name and sync_mode == 'agent':
        CONF['NODE_NAME'] = normalized_name
        return

    try:
        upsert_env_value('NODE_NAME', normalized_name)
        upsert_env_value('NODE_NAME_SYNC_MODE', 'agent')
        CONF['NODE_NAME'] = normalized_name
        CONF['NODE_NAME_SYNC_MODE'] = 'agent'
        logging.info(f"Synchronized NODE_NAME from agent: {normalized_name}")
    except Exception as e:
        logging.warning(f"Failed to synchronize NODE_NAME from agent: {e}")


def ensure_env_variables():
    """
    Check and add missing environment variables to .env file for nodes.
    """
    if not os.path.exists(ENV_FILE):
        return
    
    required_vars = {
        "MODE": "node",
        "NODE_UPDATE_INTERVAL": "5",
        "DEBUG": "false",
    }
    
    optional_vars = [
        "AGENT_BASE_URL",
        "AGENT_TOKEN",
        "BOT_TOKEN",
        "CRITICAL_ALERT_CHAT_IDS",
        "AGENT_ALERT_DELAY_SECONDS",
        "NODE_NAME",
        "NODE_NAME_SYNC_MODE",
    ]
    
    try:
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        existing_vars = set()
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                var_name = line.split('=')[0].strip()
                existing_vars.add(var_name)
        
        lines_to_add = []
        
        for var_name, default_val in required_vars.items():
            if var_name not in existing_vars:
                lines_to_add.append(f'{var_name}="{default_val}"')
        
        for var_name in optional_vars:
            if var_name not in existing_vars:
                lines_to_add.append(f'{var_name}=""')
        
        if lines_to_add:
            with open(ENV_FILE, 'a', encoding='utf-8') as f:
                f.write('\n' + '\n'.join(lines_to_add) + '\n')
            
    except Exception as e:
        pass  # Silent fail for env check


def get_server_country():
    """Detect server country code using external IP geolocation."""
    try:
        # Get external IP first
        ip = None
        for url in ["https://api.ipify.org", "https://ipinfo.io/ip", "https://ifconfig.me/ip"]:
            try:
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    ip = resp.text.strip()
                    break
            except Exception:
                continue
        
        if ip:
            # Get country from IP
            try:
                # nosemgrep: python.requests.security.insecure-requests.insecure-requests
                resp = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("countryCode", "")
            except Exception:
                pass
    except Exception:
        pass
    return ""


def get_speedtest_mode():
    """
    Detect speedtest mode: 'OOKLA', 'IPERF3', or 'AUTO'.
    """
    # Check config file first
    if os.path.exists(SPEEDTEST_MODE_FILE):
        try:
            with open(SPEEDTEST_MODE_FILE, 'r') as f:
                mode = f.read().strip().upper()
                if mode in ('OOKLA', 'RU'):
                    return 'OOKLA' if mode == 'OOKLA' else 'IPERF3'
        except Exception:
            pass
    
    # Check if Ookla speedtest is available
    try:
        result = subprocess.run(['speedtest', '--version'], capture_output=True, timeout=5)
        if result.returncode == 0 and b'Speedtest by Ookla' in result.stdout:
            return 'OOKLA'
    except Exception:
        pass
    
    # Check if iperf3 is available
    try:
        result = subprocess.run(['which', 'iperf3'], capture_output=True, timeout=5)
        if result.returncode == 0:
            return 'IPERF3'
    except Exception:
        pass
    
    return 'AUTO'


def run_ookla_speedtest():
    """Run Ookla Speedtest CLI and return result dict."""
    cmd = ["speedtest", "--accept-license", "--accept-gdpr", "--format=json"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        
        if result.returncode == 0:
            output = result.stdout.decode('utf-8', errors='ignore')
            data = json.loads(output)
            
            download_speed = data.get("download", {}).get("bandwidth", 0) / 125000
            upload_speed = data.get("upload", {}).get("bandwidth", 0) / 125000
            ping_latency = data.get("ping", {}).get("latency", 0)
            server_name = data.get("server", {}).get("name", "N/A")
            server_location = data.get("server", {}).get("location", "N/A")
            server_country = data.get("server", {}).get("country", "")
            result_url = data.get("result", {}).get("url", "")
            
            return {
                "success": True,
                "dl": download_speed,
                "ul": upload_speed,
                "ping": ping_latency,
                "server": f"{server_name} ({server_location})",
                "country": server_country,
                "url": result_url
            }
        else:
            error = result.stderr.decode('utf-8', errors='ignore') or result.stdout.decode('utf-8', errors='ignore')
            return {"success": False, "error": error[:500]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout (120s)"}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON parse error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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

# Path to logs is better taken relative to current dir or config,
# but we kept hardcoded path as in original if folder structure is preserved.
LOG_FILE_PATH = "/opt/tg-bot/logs/node/node.log"
# Create log directory if missing (for manual run)
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
BOT_TOKEN = CONF.get("BOT_TOKEN", "")
CRITICAL_ALERT_CHAT_IDS = CONF.get("CRITICAL_ALERT_CHAT_IDS", "")

try:
    UPDATE_INTERVAL = max(1, int(CONF.get("NODE_UPDATE_INTERVAL", 5)))
except ValueError:
    UPDATE_INTERVAL = 5

try:
    AGENT_ALERT_DELAY_SECONDS = int(CONF.get("AGENT_ALERT_DELAY_SECONDS", 30))
except ValueError:
    AGENT_ALERT_DELAY_SECONDS = 30

try:
    AGENT_ALERT_LANG = CONF.get("AGENT_ALERT_LANG", "ru").lower()
except ValueError:
    AGENT_ALERT_LANG = "ru"

AGENT_ALERT_STATE_FILE = os.path.join(CONFIG_DIR, '.agent_alert_state.json')
AGENT_ALERT_STATE_LOCK_DIR = os.path.join(CONFIG_DIR, '.agent_alert_state.lock')
AGENT_ALERT_DEDUP_SECONDS = max(AGENT_ALERT_DELAY_SECONDS, UPDATE_INTERVAL * 3, 60)
AGENT_ALERT_META_FILE = os.path.join(CONFIG_DIR, '.agent_alert_meta.json')

if not AGENT_BASE_URL or not AGENT_TOKEN:
    logging.error("CRITICAL: AGENT_BASE_URL or AGENT_TOKEN not found in .env")
    sys.exit(1)

OWN_NODE_TOKEN_HASH = hashlib.sha256(AGENT_TOKEN.encode()).hexdigest()

# Parse critical alert targets if provided.
# Supports numeric chat IDs (e.g. -100123...) and string targets (e.g. @channel_username).
CRITICAL_CHAT_IDS = []
if CRITICAL_ALERT_CHAT_IDS:
    for raw_target in CRITICAL_ALERT_CHAT_IDS.split(','):
        target = raw_target.strip()
        if not target:
            continue
        if re.fullmatch(r"-?\d+", target):
            CRITICAL_CHAT_IDS.append(int(target))
        else:
            CRITICAL_CHAT_IDS.append(target)

if BOT_TOKEN and CRITICAL_CHAT_IDS:
    logging.info(f"Critical alerts configured for {len(CRITICAL_CHAT_IDS)} chat target(s)")
elif BOT_TOKEN and not CRITICAL_CHAT_IDS:
    logging.warning("BOT_TOKEN configured, but CRITICAL_ALERT_CHAT_IDS is empty or invalid")
elif not BOT_TOKEN and CRITICAL_ALERT_CHAT_IDS:
    logging.warning("CRITICAL_ALERT_CHAT_IDS configured, but BOT_TOKEN is empty")

PENDING_RESULTS = collections.deque(maxlen=50)
LAST_TRAFFIC_STATS = {}
_HEARTBEAT_NET_STATS = {}
SSH_EVENTS = collections.deque(maxlen=100)

# Commands that take a long time and must run in a background thread
# so heartbeats are not blocked.
LONG_RUNNING_COMMANDS = {"speedtest", "update"}

# Agent health tracking
AGENT_DOWN_SINCE = None
AGENT_DOWN_ALERT_SENT = False
AGENT_STABLE_SINCE = None  # Timestamp when agent first came back up; used to confirm stable recovery
LAST_AGENT_LANG = AGENT_ALERT_LANG if AGENT_ALERT_LANG in {"ru", "en"} else "ru"
CACHED_ALERT_REPORTER_HASH = None
SKIPPED_AGENT_ALERT_LOGS = set()
LAST_HTTP_ERROR_SIGNATURE = None
LAST_HTTP_ERROR_LOGGED_AT = 0.0
SUPPRESSED_HTTP_ERROR_COUNT = 0
HTTP_ERROR_LOG_COOLDOWN_SECONDS = max(UPDATE_INTERVAL * 4, 30)

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
        "https://checkip.amazonaws.com"
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
        # Security: Use exec instead of shell to prevent injection
        proc = subprocess.Popen(
            ["curl", "-4", "-s", "--max-time", "5", "ifconfig.me"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = proc.communicate()
        res = stdout.decode().strip()
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", res):
            EXTERNAL_IP_CACHE = res
            logging.info(f"External IP updated (curl): {res}")
            return res
    except Exception as e:
        logging.debug(f"Failed to get IP via curl: {e}")

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


def get_services_status():
    """Get status of common services on the node - only installed ones"""
    services = []
    common_services = [
        "xray", "nginx", "docker", "ssh", "sshd", "fail2ban",
        "mysql", "mariadb", "postgresql", "redis", "mongodb",
        "apache2", "httpd", "php-fpm", "caddy", "traefik"
    ]
    
    for service in common_services:
        try:
            # First check if service exists (is-enabled or show LoadState)
            proc_check = subprocess.run(
                ["systemctl", "show", service, "-p", "LoadState"],
                capture_output=True,
                timeout=2
            )
            load_state = proc_check.stdout.decode().strip()
            
            # Skip if service is not found/not installed
            if "not-found" in load_state or "masked" in load_state:
                continue
                
            # Get actual status
            proc = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                timeout=2
            )
            status = proc.stdout.decode().strip()
            
            # Only add if service exists and has valid status
            if status in ["active", "inactive", "failed"]:
                services.append({
                    "name": service,
                    "status": "running" if status == "active" else "stopped"
                })
        except Exception:
            pass
    
    # Also check for docker containers
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}:{{.Status}}"],
            capture_output=True,
            timeout=5
        )
        if proc.returncode == 0:
            for line in proc.stdout.decode().strip().split("\n"):
                if ":" in line:
                    name, status = line.split(":", 1)
                    if name.strip():
                        services.append({
                            "name": name.strip(),
                            "type": "docker",
                            "status": "running" if "Up" in status else "stopped"
                        })
    except Exception:
        pass
    
    return services


def service_action(service_name, action, service_type="systemd"):
    """Execute service action (start, stop, restart) for systemd or docker"""
    allowed_actions = ["start", "stop", "restart"]
    if action not in allowed_actions:
        return {"success": False, "error": f"Invalid action: {action}"}
    if not re.match(r"^[\w\-\.]+$", service_name):
        return {"success": False, "error": "Invalid service name format"}
    try:
        if service_type == "docker":
            # Docker container commands
            proc = subprocess.run(
                ["docker", action, service_name],
                capture_output=True,
                timeout=60
            )
        else:
            # Systemd service commands
            proc = subprocess.run(
                ["systemctl", action, service_name],
                capture_output=True,
                timeout=30
            )
        
        if proc.returncode == 0:
            return {"success": True, "message": f"Service {service_name} {action}ed successfully"}
        else:
            return {"success": False, "error": proc.stderr.decode().strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout while executing service action"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def parse_iperf_json(output: str, direction: str) -> float:
    """
    Parse iperf3 JSON output.
    direction: 'download' or 'upload'
    """
    try:
        data = json.loads(output)
        
        # Check for error in iperf3 output
        if "error" in data:
            logging.error(f"iperf3 error: {data['error']}")
            return 0.0
            
        if "end" not in data:
            logging.error(f"No 'end' section in iperf3 output")
            return 0.0
            
        end = data["end"]
        
        if direction == 'download':
            # For download test (-R), we need sum_received
            if "sum_received" in end:
                speed = end["sum_received"]["bits_per_second"] / 1000000
                logging.info(f"Download speed parsed: {speed:.2f} Mbps")
                return speed
            # Fallback: try streams
            elif "streams" in end and len(end["streams"]) > 0:
                speed = end["streams"][0].get("receiver", {}).get("bits_per_second", 0) / 1000000
                logging.info(f"Download speed from streams: {speed:.2f} Mbps")
                return speed
        else:
            # For upload test, we need sum_sent
            if "sum_sent" in end:
                speed = end["sum_sent"]["bits_per_second"] / 1000000
                logging.info(f"Upload speed parsed: {speed:.2f} Mbps")
                return speed
            # Fallback: try streams
            elif "streams" in end and len(end["streams"]) > 0:
                speed = end["streams"][0].get("sender", {}).get("bits_per_second", 0) / 1000000
                logging.info(f"Upload speed from streams: {speed:.2f} Mbps")
                return speed
                
        logging.error(f"Could not find speed data in iperf3 output for {direction}")
        logging.debug(f"Available keys in 'end': {list(end.keys())}")
        
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse iperf3 JSON: {e}")
    except KeyError as e:
        logging.error(f"Missing key in iperf3 output: {e}")
    except Exception as e:
        logging.error(f"Error parsing iperf3 output: {e}")
    
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
    global _HEARTBEAT_NET_STATS
    try:
        net = psutil.net_io_counters()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        freq = psutil.cpu_freq()
        
        ext_ip = get_external_ip()
        
        # Calculate network speed from previous heartbeat measurement
        now = time.time()
        net_rx_speed = 0.0
        net_tx_speed = 0.0
        if _HEARTBEAT_NET_STATS:
            prev_rx = _HEARTBEAT_NET_STATS.get('rx', 0)
            prev_tx = _HEARTBEAT_NET_STATS.get('tx', 0)
            prev_time = _HEARTBEAT_NET_STATS.get('time', 0)
            dt = now - prev_time
            if 1 <= dt <= 120:
                net_rx_speed = max(0.0, (net.bytes_recv - prev_rx) * 8 / 1024 / dt)
                net_tx_speed = max(0.0, (net.bytes_sent - prev_tx) * 8 / 1024 / dt)
            else:
                # Keep previous speed if interval is abnormal
                net_rx_speed = _HEARTBEAT_NET_STATS.get('last_rx_speed', 0.0)
                net_tx_speed = _HEARTBEAT_NET_STATS.get('last_tx_speed', 0.0)
        
        _HEARTBEAT_NET_STATS = {
            'rx': net.bytes_recv,
            'tx': net.bytes_sent,
            'time': now,
            'last_rx_speed': net_rx_speed,
            'last_tx_speed': net_tx_speed
        }
        
        # Measure ping: try ICMP first (faster/accurate), fallback to HTTPS if blocked
        ping_ms = None
        
        # Try ICMP ping first
        try:
            proc = subprocess.Popen(
                ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, _ = proc.communicate(timeout=5)
            ping_match = re.search(r"time=([\d\.]+)\s*ms", stdout.decode())
            if ping_match:
                ping_ms = round(float(ping_match.group(1)), 1)
        except Exception:
            pass
        
        if ping_ms is None:
            try:
                t1 = time.time()
                resp = requests.head("https://www.google.com", timeout=3)
                if resp.status_code == 200:
                    ping_ms = round((time.time() - t1) * 1000, 1)
            except Exception:
                pass
        
        ram_used = mem.total - mem.available
        ram_pct = round(ram_used / mem.total * 100, 1) if mem.total > 0 else 0
        
        result = {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": ram_pct,
            "disk": disk.percent,
            "ram_total": mem.total,
            "ram_used": ram_used,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "cpu_freq": freq.current if freq else 0,
            "net_rx": net.bytes_recv,
            "net_tx": net.bytes_sent,
            "net_rx_speed": round(net_rx_speed, 2),
            "net_tx_speed": round(net_tx_speed, 2),
            "uptime": int(time.time() - psutil.boot_time()),
            "boot_time": int(psutil.boot_time()),
            "process_cpu": get_top_processes('cpu'),
            "process_ram": get_top_processes('ram'),
            "external_ip": ext_ip,
            "ping": ping_ms if ping_ms is not None else "n/a"
        }
        return result
    except Exception as e:
        logging.error(f"Error gathering stats: {e}")
        return {}

def get_public_iperf_server(exclude_ru=True):
    """Get best iperf3 server by measuring ping to multiple servers"""
    try:
        # For Russia, use Russian server list
        if not exclude_ru:
            try:
                import yaml
                ru_url = "https://raw.githubusercontent.com/itdoginfo/russian-iperf3-servers/refs/heads/main/list.yml"
                response = requests.get(ru_url, timeout=5)
                if response.status_code == 200:
                    data = yaml.safe_load(response.text)
                    servers = []
                    for s in data:
                        if "address" in s and "port" in s:
                            port = int(str(s["port"]).split("-")[0].strip())
                            servers.append({
                                "IP/HOST": s["address"],
                                "PORT": port,
                                "SITE": s.get("City", "Unknown"),
                                "COUNTRY": "RU",
                                "provider": s.get("Name", "")
                            })
                    if servers:
                        sample_size = min(15, len(servers))
                        test_servers = random.sample(servers, sample_size)
                        
                        best_server = None
                        best_ping = float('inf')
                        
                        for server in test_servers:
                            host = server.get("IP/HOST")
                            ping_ms = measure_ping(host)
                            if ping_ms is not None and ping_ms < best_ping:
                                best_ping = ping_ms
                                best_server = server
                                best_server["_ping"] = ping_ms
                        
                        if best_server:
                            logging.info(f"Selected RU server: {best_server.get('IP/HOST')} ({best_ping:.2f} ms)")
                            return best_server
                        return random.choice(servers)
            except Exception as e:
                logging.error(f"Error fetching RU iperf servers: {e}")
        
        # Global server list
        url = "https://export.iperf3serverlist.net/listed_iperf3_servers.json"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            servers = response.json()
            if exclude_ru:
                valid_servers = [s for s in servers if s.get("IP/HOST") and s.get("PORT") and s.get("COUNTRY") != "RU"]
            else:
                valid_servers = [s for s in servers if s.get("IP/HOST") and s.get("PORT")]
            if valid_servers:
                # Test ping to up to 15 random servers and pick the best one
                sample_size = min(15, len(valid_servers))
                test_servers = random.sample(valid_servers, sample_size)
                
                best_server = None
                best_ping = float('inf')
                
                for server in test_servers:
                    host = server.get("IP/HOST")
                    ping_ms = measure_ping(host)
                    if ping_ms is not None and ping_ms < best_ping:
                        best_ping = ping_ms
                        best_server = server
                        best_server["_ping"] = ping_ms
                
                if best_server:
                    logging.info(f"Selected server: {best_server.get('IP/HOST')} ({best_ping:.2f} ms)")
                    return best_server
                    
                # Fallback to random if ping failed
                return random.choice(valid_servers)
    except Exception as e:
        logging.error(f"Error fetching iperf servers: {e}")
    return None


def measure_ping(host: str) -> float:
    """Measure ping to a host, returns average ping in ms or None on failure"""
    try:
        # Linux ping command
        cmd = ["ping", "-c", "2", "-W", "2", host]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse: rtt min/avg/max/mdev = 1.234/5.678/9.012/1.234 ms
            match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", result.stdout)
            if match:
                return float(match.group(1))
    except Exception as e:
        logging.debug(f"Ping to {host} failed: {e}")
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
                proc = subprocess.Popen(
                    ["ps", "-eo", "user,pid,%cpu,%mem,comm", "--sort=-%cpu"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = proc.communicate()
                all_lines = stdout.decode().split('\n')
                res = '\n'.join(all_lines[:11])  # Head -n 11
                
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

            # Fetch IPv4
            ext_ipv4 = stats.get("external_ip") or ""
            if not ext_ipv4:
                try:
                    proc = subprocess.Popen(
                        ["curl", "-4", "-s", "--max-time", "3", "ifconfig.me"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    stdout, _ = proc.communicate()
                    ext_ipv4 = stdout.decode().strip()
                except Exception:
                    ext_ipv4 = ""

            # Fetch IPv6
            ext_ipv6 = ""
            try:
                proc = subprocess.Popen(
                    ["curl", "-6", "-s", "--max-time", "3", "ifconfig.me"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = proc.communicate()
                candidate = stdout.decode().strip()
                if ":" in candidate:
                    ext_ipv6 = candidate
            except Exception:
                ext_ipv6 = ""

            ping_val = "0"
            inet_ok = False
            try:
                proc = subprocess.Popen(
                    ["ping", "-c", "1", "-W", "1", "8.8.8.8"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = proc.communicate()
                ping_res = stdout.decode()
                ping_match = re.search(r"time=([\d\.]+) ms", ping_res)
                if ping_match:
                    ping_val = ping_match.group(1)
                    inet_ok = True
            except Exception:
                pass

            try:
                # Security: Use exec instead of shell
                proc = subprocess.Popen(
                    ["uname", "-r"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = proc.communicate()
                kernel = stdout.decode().strip()
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
                    "ipv4": ext_ipv4 or "N/A",
                    "ipv6": ext_ipv6 or "N/A",
                    "rx": rx_total,
                    "tx": tx_total
                }
            }

        elif cmd == "speedtest":
            # Determine speedtest mode
            mode = get_speedtest_mode()
            country_code = None
            
            if mode == 'AUTO':
                # Need to detect based on geo
                country_code = get_server_country()
                if country_code == 'RU':
                    mode = 'IPERF3'
                else:
                    # Check if Ookla is available
                    try:
                        result = subprocess.run(['speedtest', '--version'], capture_output=True, timeout=5)
                        if result.returncode == 0 and b'Speedtest by Ookla' in result.stdout:
                            mode = 'OOKLA'
                        else:
                            mode = 'IPERF3'
                    except Exception:
                        mode = 'IPERF3'
            
            if mode == 'OOKLA':
                # Use Ookla Speedtest CLI
                ookla_result = run_ookla_speedtest()
                if ookla_result.get("success"):
                    result_payload = {
                        "type": "i18n",
                        "key": "speedtest_ookla_results",
                        "params": {
                            "dl": ookla_result["dl"],
                            "ul": ookla_result["ul"],
                            "ping": ookla_result["ping"],
                            "server": ookla_result["server"].split(" (")[0] if " (" in ookla_result["server"] else ookla_result["server"],
                            "location": ookla_result["server"].split(" (")[1].rstrip(")") if " (" in ookla_result["server"] else "",
                            "url": ookla_result.get("url", "")
                        }
                    }
                else:
                    result_payload = {
                        "type": "i18n",
                        "key": "error_with_details",
                        "params": {"error": ookla_result.get("error", "Ookla speedtest failed")}
                    }
            else:
                # Use iperf3
                is_russia = country_code == 'RU' if country_code else get_server_country() == 'RU'
                
                # Try RU servers first, fallback to global
                server_lists_to_try = []
                if is_russia:
                    server_lists_to_try.append(('ru', False))    # RU servers
                    server_lists_to_try.append(('global', True)) # Global fallback
                else:
                    server_lists_to_try.append(('global', True))
                
                speedtest_done = False
                last_error = None
                
                for list_name, exclude_ru_flag in server_lists_to_try:
                    if speedtest_done:
                        break
                    
                    server = get_public_iperf_server(exclude_ru=exclude_ru_flag)
                    if not server:
                        logging.warning(f"No iperf3 servers found in {list_name} list")
                        continue
                    
                    # Try the selected server
                    host = server.get("IP/HOST")
                    port = server.get("PORT")
                    city = server.get("SITE", "Unknown")
                    country = server.get("COUNTRY", "")
                    ping_ms = server.get("_ping", 0)
                    
                    dl_speed = 0.0
                    ul_speed = 0.0
                    
                    # Download test
                    cmd_dl = ["iperf3", "-c", host, "-p", str(port), "-J", "-t", "5", "-4", "-R"]
                    try:
                        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
                        res_dl = subprocess.check_output(
                            cmd_dl, stderr=subprocess.STDOUT, timeout=30).decode()
                        dl_speed = parse_iperf_json(res_dl, 'download')
                    except subprocess.TimeoutExpired:
                        logging.warning(f"DL test timeout for {host}:{port}")
                    except Exception as e:
                        logging.error(f"DL Test failed for {host}:{port}: {e}")
                    
                    # Upload test
                    cmd_ul = ["iperf3", "-c", host, "-p", str(port), "-J", "-t", "5", "-4"]
                    try:
                        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
                        res_ul = subprocess.check_output(
                            cmd_ul, stderr=subprocess.STDOUT, timeout=30).decode()
                        ul_speed = parse_iperf_json(res_ul, 'upload')
                    except subprocess.TimeoutExpired:
                        logging.warning(f"UL test timeout for {host}:{port}")
                    except Exception as e:
                        logging.error(f"UL Test failed for {host}:{port}: {e}")
                    
                    if dl_speed > 0.0 or ul_speed > 0.0:
                        result_payload = {
                            "type": "i18n",
                            "key": "speedtest_results",
                            "params": {
                                "dl": dl_speed,
                                "ul": ul_speed,
                                "ping": ping_ms,
                                "server": f"{city}, {country}",
                                "provider": host
                            }
                        }
                        speedtest_done = True
                    else:
                        last_error = f"{host}:{port} ({list_name})"
                        logging.warning(f"iperf3 failed on {last_error}, trying next...")
                
                if not speedtest_done:
                    result_payload = {
                        "type": "i18n",
                        "key": "error_with_details",
                        "params": {"error": f"All iperf3 servers unavailable. Last tried: {last_error or 'none found'}"}
                    }

        elif cmd == "update":
            if os.geteuid() == 0:
                base_cmd = "DEBIAN_FRONTEND=noninteractive apt update && DEBIAN_FRONTEND=noninteractive apt upgrade -y && apt autoremove -y"
            else:
                base_cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"

            try:
                result = subprocess.run(
                    ["bash", "-lc", base_cmd],
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                if result.returncode == 0:
                    result_payload = {
                        "type": "i18n",
                        "key": "update_success",
                        "params": {
                            "output": html.escape((result.stdout or "")[-2000:])
                        }
                    }
                else:
                    error_text = result.stderr or result.stdout or "Unknown error"
                    result_payload = {
                        "type": "i18n",
                        "key": "update_fail",
                        "params": {
                            "code": result.returncode,
                            "error": html.escape(error_text[-2000:])
                        }
                    }
            except subprocess.TimeoutExpired:
                result_payload = {
                    "type": "i18n",
                    "key": "update_fail",
                    "params": {
                        "code": "timeout",
                        "error": html.escape("Command timed out after 1800 seconds")
                    }
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
            try:
                subprocess.Popen(["reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                logger.error(f"Failed to reboot: {e}")
            return

        elif cmd == "services_list":
            services = get_services_status()
            result_payload = {
                "type": "services_list",
                "services": services
            }

        elif cmd == "service_action":
            svc_name = task.get("service")
            svc_action = task.get("action")
            svc_type = task.get("type", "systemd")
            if not svc_name or not svc_action:
                result_payload = {
                    "type": "i18n",
                    "key": "error_with_details",
                    "params": {"error": "Missing service or action"}
                }
            else:
                result = service_action(svc_name, svc_action, svc_type)
                if result["success"]:
                    result_payload = {
                        "type": "i18n",
                        "key": "services_action_success",
                        "params": {"service": svc_name, "action": svc_action}
                    }
                else:
                    result_payload = {
                        "type": "i18n",
                        "key": "error_with_details",
                        "params": {"error": result.get("error", "Unknown error")}
                    }

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

def check_agent_health():
    """
    Check if the agent is accessible by making a simple HTTP request.
    Returns True if accessible, False otherwise.
    """
    try:
        # Try to reach agent's health endpoint with a short timeout
        health_url = f"{AGENT_BASE_URL.rstrip('/')}/health"
        response = requests.get(health_url, timeout=3)
        # Any non-5xx response means endpoint is reachable (even if /health is not implemented)
        if response.status_code < 500:
            return True
    except Exception:
        pass

    # If health endpoint doesn't exist or is unstable, check heartbeat endpoint reachability
    try:
        response = requests.head(f"{AGENT_BASE_URL.rstrip('/')}/api/heartbeat", timeout=3)
        return response.status_code < 500
    except Exception:
        return False


def send_critical_telegram_alert(message):
    """
    Send critical alert directly to Telegram, bypassing the agent.
    Used when agent is down and cannot relay messages.
    """
    if not BOT_TOKEN or not CRITICAL_CHAT_IDS:
        logging.warning("Direct Telegram alert skipped: BOT_TOKEN or CRITICAL_ALERT_CHAT_IDS not configured")
        return False
    
    telegram_api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    success_count = 0
    
    for chat_id in CRITICAL_CHAT_IDS:
        try:
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(telegram_api_url, json=payload, timeout=10)
            if response.status_code == 200:
                success_count += 1
                logging.info(f"Critical alert sent to Telegram chat {chat_id}")
            else:
                response_text = response.text[:200]
                logging.warning(
                    f"Failed to send critical alert to chat {chat_id}: "
                    f"{response.status_code} {response_text}"
                )
                if response.status_code == 403 and "bots can't send messages to bots" in response_text:
                    logging.warning(
                        "Invalid CRITICAL_ALERT_CHAT_IDS target: this is a bot chat. "
                        "Use your personal chat_id, group_id, or channel_id where your bot is added and has access."
                    )
        except Exception as e:
            logging.error(f"Error sending critical Telegram alert to chat {chat_id}: {e}")
    
    return success_count > 0


def _acquire_agent_alert_lock():
    for _ in range(10):
        try:
            os.mkdir(AGENT_ALERT_STATE_LOCK_DIR)
            return True
        except FileExistsError:
            time.sleep(0.1)
        except Exception as e:
            logging.debug(f"Failed to acquire alert lock: {e}")
            return False
    return False


def _release_agent_alert_lock():
    try:
        os.rmdir(AGENT_ALERT_STATE_LOCK_DIR)
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.debug(f"Failed to release alert lock: {e}")


def _load_agent_alert_state():
    try:
        with open(AGENT_ALERT_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.debug(f"Failed to load alert state: {e}")
        return {}


def _save_agent_alert_state(state):
    temp_path = f"{AGENT_ALERT_STATE_FILE}.{os.getpid()}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    os.replace(temp_path, AGENT_ALERT_STATE_FILE)


def load_agent_alert_meta():
    try:
        with open(AGENT_ALERT_META_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.debug(f"Failed to load alert meta: {e}")
    return {}


def save_agent_alert_meta(meta):
    temp_path = f"{AGENT_ALERT_META_FILE}.{os.getpid()}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f)
    os.replace(temp_path, AGENT_ALERT_META_FILE)


def get_cached_alert_reporter_hash():
    global CACHED_ALERT_REPORTER_HASH
    if CACHED_ALERT_REPORTER_HASH:
        return CACHED_ALERT_REPORTER_HASH
    meta = load_agent_alert_meta()
    reporter_hash = meta.get('alert_reporter_hash')
    if isinstance(reporter_hash, str) and reporter_hash:
        CACHED_ALERT_REPORTER_HASH = reporter_hash
    return CACHED_ALERT_REPORTER_HASH


def update_cached_alert_reporter_hash(reporter_hash):
    global CACHED_ALERT_REPORTER_HASH
    if not isinstance(reporter_hash, str) or not reporter_hash:
        return
    if reporter_hash == CACHED_ALERT_REPORTER_HASH:
        return
    CACHED_ALERT_REPORTER_HASH = reporter_hash
    meta = load_agent_alert_meta()
    meta['alert_reporter_hash'] = reporter_hash
    save_agent_alert_meta(meta)


def is_alert_reporter_node():
    reporter_hash = get_cached_alert_reporter_hash()
    if not reporter_hash:
        return True
    return reporter_hash == OWN_NODE_TOKEN_HASH


def _clear_skipped_agent_alert_logs(node_name, alert_kind=None):
    global SKIPPED_AGENT_ALERT_LOGS
    SKIPPED_AGENT_ALERT_LOGS = {
        key for key in SKIPPED_AGENT_ALERT_LOGS
        if key[0] != node_name or (alert_kind is not None and key[1] != alert_kind)
    }


def _log_skipped_agent_alert_once(alert_kind, node_name):
    reporter_hash = get_cached_alert_reporter_hash() or "unknown"
    log_key = (node_name, alert_kind, reporter_hash)
    if log_key in SKIPPED_AGENT_ALERT_LOGS:
        return

    _clear_skipped_agent_alert_logs(node_name, alert_kind)
    SKIPPED_AGENT_ALERT_LOGS.add(log_key)
    logging.info(
        f"Skipping agent {alert_kind} alert on node {node_name}: another node is selected as reporter"
    )


def _get_node_alert_state(state, node_name):
    node_state = state.get(node_name)
    if isinstance(node_state, dict):
        return node_state
    return {
        'incident_active': False,
        'down_sent': False,
        'last_down_alert_at': 0,
        'last_recovery_alert_at': 0,
    }


def _prune_finished_incident(node_state):
    last_recovery_alert_at = float(node_state.get('last_recovery_alert_at', 0) or 0)
    pending_kind = node_state.get('pending_kind')
    if pending_kind == 'recovery':
        return
    if node_state.get('incident_active'):
        return
    if last_recovery_alert_at and time.time() - last_recovery_alert_at > AGENT_ALERT_DEDUP_SECONDS:
        node_state.clear()


def _reserve_agent_alert(alert_kind, node_name):
    now = time.time()
    reservation_id = f"{os.getpid()}:{threading.get_ident()}:{int(now * 1000)}"

    if not _acquire_agent_alert_lock():
        logging.warning(f"Alert dedup lock unavailable, sending {alert_kind} alert without deduplication")
        return reservation_id

    try:
        state = _load_agent_alert_state()
        node_state = _get_node_alert_state(state, node_name)
        _prune_finished_incident(node_state)

        if alert_kind == 'down':
            if node_state.get('incident_active') and node_state.get('down_sent'):
                return None
            node_state['incident_active'] = True
        elif alert_kind == 'recovery':
            if not node_state.get('incident_active') or not node_state.get('down_sent'):
                return None
            if node_state.get('pending_kind') == 'recovery':
                return None
        else:
            last_sent_at = float(node_state.get(f'last_{alert_kind}_alert_at', 0) or 0)
            if last_sent_at and now - last_sent_at < AGENT_ALERT_DEDUP_SECONDS:
                return None

        node_state['pending_kind'] = alert_kind
        node_state['pending_since'] = now
        node_state['reservation_id'] = reservation_id
        state[node_name] = node_state
        _save_agent_alert_state(state)
        return reservation_id
    finally:
        _release_agent_alert_lock()


def _finalize_agent_alert(alert_kind, node_name, reservation_id, sent):
    if not _acquire_agent_alert_lock():
        return

    try:
        state = _load_agent_alert_state()
        node_state = state.get(node_name)
        if not isinstance(node_state, dict) or node_state.get('reservation_id') != reservation_id:
            return

        node_state.pop('pending_kind', None)
        node_state.pop('pending_since', None)
        node_state.pop('reservation_id', None)

        if sent:
            now = time.time()
            if alert_kind == 'down':
                node_state['incident_active'] = True
                node_state['down_sent'] = True
                node_state['last_down_alert_at'] = now
            elif alert_kind == 'recovery':
                node_state['incident_active'] = False
                node_state['down_sent'] = False
                node_state['last_recovery_alert_at'] = now
            else:
                node_state[f'last_{alert_kind}_alert_at'] = now
        elif alert_kind == 'down' and not node_state.get('down_sent'):
            node_state['incident_active'] = True

        _prune_finished_incident(node_state)
        if node_state:
            state[node_name] = node_state
        else:
            state.pop(node_name, None)
        _save_agent_alert_state(state)
    finally:
        _release_agent_alert_lock()


def clear_agent_alert_incident(node_name):
    if not _acquire_agent_alert_lock():
        return

    try:
        state = _load_agent_alert_state()
        node_state = _get_node_alert_state(state, node_name)
        node_state['incident_active'] = False
        node_state['down_sent'] = False
        node_state.pop('pending_kind', None)
        node_state.pop('pending_since', None)
        node_state.pop('reservation_id', None)
        _prune_finished_incident(node_state)
        if node_state:
            state[node_name] = node_state
        else:
            state.pop(node_name, None)
        _save_agent_alert_state(state)
    finally:
        _release_agent_alert_lock()

    _clear_skipped_agent_alert_logs(node_name)


def send_deduplicated_agent_alert(alert_kind, node_name, message):
    if not is_alert_reporter_node():
        _log_skipped_agent_alert_once(alert_kind, node_name)
        return False

    _clear_skipped_agent_alert_logs(node_name, alert_kind)

    reservation_id = _reserve_agent_alert(alert_kind, node_name)
    if reservation_id is None:
        logging.info(f"Duplicate agent {alert_kind} alert suppressed for node {node_name}")
        return False

    sent = False
    try:
        sent = send_critical_telegram_alert(message)
        return sent
    finally:
        _finalize_agent_alert(alert_kind, node_name, reservation_id, sent)


def format_downtime(seconds):
    return format_downtime_localized(seconds, LAST_AGENT_LANG)


def format_downtime_localized(seconds, lang):
    """Format downtime duration in human-readable format in the selected language."""
    if lang == "en":
        if seconds < 60:
            return f"{int(seconds)} seconds"
        if seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minutes"
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        if minutes > 0:
            return f"{hours} hours {minutes} minutes"
        return f"{hours} hours"

    if seconds < 60:
        return f"{int(seconds)} секунд"
    if seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} минут"
    hours = int(seconds / 3600)
    minutes = int((seconds % 3600) / 60)
    if minutes > 0:
        return f"{hours} часов {minutes} минут"
    return f"{hours} часов"


def summarize_http_error_body(body, limit=160):
    if not body:
        return ""
    body_text = str(body)
    title_match = re.search(r"<title>(.*?)</title>", body_text, flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        if title:
            return title
    compact = re.sub(r"\s+", " ", body_text).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def flush_suppressed_http_error_logs():
    global LAST_HTTP_ERROR_SIGNATURE, LAST_HTTP_ERROR_LOGGED_AT, SUPPRESSED_HTTP_ERROR_COUNT
    if LAST_HTTP_ERROR_SIGNATURE and SUPPRESSED_HTTP_ERROR_COUNT > 0:
        logging.warning(
            f"Previous server error repeated {SUPPRESSED_HTTP_ERROR_COUNT} more time(s): {LAST_HTTP_ERROR_SIGNATURE}"
        )
    LAST_HTTP_ERROR_SIGNATURE = None
    LAST_HTTP_ERROR_LOGGED_AT = 0.0
    SUPPRESSED_HTTP_ERROR_COUNT = 0


def log_http_error(status_code, body):
    global LAST_HTTP_ERROR_SIGNATURE, LAST_HTTP_ERROR_LOGGED_AT, SUPPRESSED_HTTP_ERROR_COUNT

    response_summary = summarize_http_error_body(body)
    signature = f"{status_code} {response_summary}".strip()
    now = time.time()

    if signature == LAST_HTTP_ERROR_SIGNATURE and now - LAST_HTTP_ERROR_LOGGED_AT < HTTP_ERROR_LOG_COOLDOWN_SECONDS:
        SUPPRESSED_HTTP_ERROR_COUNT += 1
        LAST_HTTP_ERROR_LOGGED_AT = now
        return

    if LAST_HTTP_ERROR_SIGNATURE and SUPPRESSED_HTTP_ERROR_COUNT > 0:
        logging.warning(
            f"Previous server error repeated {SUPPRESSED_HTTP_ERROR_COUNT} more time(s): {LAST_HTTP_ERROR_SIGNATURE}"
        )

    LAST_HTTP_ERROR_SIGNATURE = signature
    LAST_HTTP_ERROR_LOGGED_AT = now
    SUPPRESSED_HTTP_ERROR_COUNT = 0
    logging.warning(f"Server returned status: {signature}")


def get_node_name_for_alert():
    node_name = CONF.get("NODE_NAME", "")
    if node_name:
        return node_name
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "Unknown Node"


def build_agent_down_alert(node_name):
    if LAST_AGENT_LANG == "en":
        return (
            f"🚨 <b>CRITICAL: Main agent (primary server) is UNREACHABLE!</b>\n\n"
            f"🌐 <b>Reported by node:</b> {node_name}\n"
            f"💭 <b>Status:</b> Agent is unreachable since {datetime.fromtimestamp(AGENT_DOWN_SINCE).strftime('%H:%M:%S')}\n"
            f"⚠️ <b>Action:</b> Check main server availability and bot service status"
        )
    return (
        f"🚨 <b>КРИТИЧНОЕ: Главный агент (основной сервер) НЕДОСТУПЕН!</b>\n\n"
        f"🌐 <b>Сообщено нодой:</b> {node_name}\n"
        f"💭 <b>Статус:</b> Агент недоступен с {datetime.fromtimestamp(AGENT_DOWN_SINCE).strftime('%H:%M:%S')}\n"
        f"⚠️ <b>Действие:</b> Проверьте доступность основного сервера и службы бота"
    )


def build_agent_recovery_alert(node_name, downtime):
    downtime_text = format_downtime_localized(downtime, LAST_AGENT_LANG)
    if LAST_AGENT_LANG == "en":
        return (
            f"✅ <b>Main agent recovered!</b>\n\n"
            f"🌐 <b>Reported by node:</b> {node_name}\n"
            f"🟢 <b>Status:</b> Agent is reachable again\n"
            f"⏱ <b>Downtime:</b> {downtime_text}\n"
            f"📡 <b>System stabilized</b>"
        )
    return (
        f"✅ <b>Главный агент восстановлен!</b>\n\n"
        f"🌐 <b>Сообщено нодой:</b> {node_name}\n"
        f"🟢 <b>Статус:</b> Агент снова доступен\n"
        f"⏱ <b>Время простоя:</b> {downtime_text}\n"
        f"📡 <b>Система стабилизована</b>"
    )


def send_heartbeat():
    global AGENT_DOWN_SINCE, AGENT_DOWN_ALERT_SENT, AGENT_STABLE_SINCE, LAST_AGENT_LANG
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    current_results = list(PENDING_RESULTS)
    current_ssh_events = list(SSH_EVENTS)
    
    # Get services status periodically
    services = []
    try:
        services = get_services_status()
    except Exception as e:
        logging.debug(f"Failed to get services status: {e}")
    
    # Check agent health status before sending heartbeat
    agent_is_healthy = check_agent_health()
    agent_status = "online" if agent_is_healthy else "unreachable"
    
    payload_dict = {
        "stats": get_system_stats(),
        "results": current_results,
        "ssh_logins": current_ssh_events,
        "services": services,
        "agent_status": agent_status,
        "timestamp": int(time.time())
    }
    
    payload_bytes = json.dumps(payload_dict, sort_keys=True).encode('utf-8')
    
    signature = hmac.new(AGENT_TOKEN.encode(), payload_bytes, hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-Node-Token": AGENT_TOKEN,
        "X-Signature": signature
    }

    try:
        response = requests.post(url, data=payload_bytes, headers=headers, timeout=5)
        if response.status_code == 200:
            flush_suppressed_http_error_logs()
            data = response.json()

            sync_node_name_from_agent(data.get("node_name", ""))

            # Agent provides preferred language while online; keep it cached for offline alerts.
            response_lang = data.get("alert_lang")
            if response_lang in {"ru", "en"} and response_lang != LAST_AGENT_LANG:
                LAST_AGENT_LANG = response_lang
                logging.info(f"Updated alert language from agent: {LAST_AGENT_LANG}")

            response_reporter_hash = data.get("agent_alert_reporter_hash")
            if isinstance(response_reporter_hash, str) and response_reporter_hash:
                update_cached_alert_reporter_hash(response_reporter_hash)

            for r in current_results:
                try:
                    PENDING_RESULTS.remove(r)
                except ValueError:
                    pass
            for e in current_ssh_events:
                try:
                    SSH_EVENTS.remove(e)
                except ValueError:
                    pass

            tasks = data.get("tasks", [])
            for task in tasks:
                cmd = task.get("command", "")
                if cmd in LONG_RUNNING_COMMANDS:
                    threading.Thread(
                        target=execute_command, args=(task,), daemon=True
                    ).start()
                else:
                    execute_command(task)

            # Heartbeat delivery succeeded - wait for stable recovery before notifying
            if AGENT_DOWN_SINCE is not None:
                now = time.time()
                if AGENT_STABLE_SINCE is None:
                    AGENT_STABLE_SINCE = now
                    logging.info("Agent became reachable again, waiting for stability confirmation")
                elif now - AGENT_STABLE_SINCE >= AGENT_ALERT_DELAY_SECONDS:
                    # Agent has been consistently reachable long enough - declare recovery
                    downtime = now - AGENT_DOWN_SINCE
                    node_name = get_node_name_for_alert()

                    if AGENT_DOWN_ALERT_SENT:
                        recovery_message = build_agent_recovery_alert(node_name, downtime)
                        if send_deduplicated_agent_alert("recovery", node_name, recovery_message):
                            logging.info(f"Agent recovered after {format_downtime(downtime)} downtime")
                    else:
                        clear_agent_alert_incident(node_name)

                    AGENT_DOWN_SINCE = None
                    AGENT_DOWN_ALERT_SENT = False
                    AGENT_STABLE_SINCE = None
            else:
                # No ongoing downtime - reset stability tracking
                AGENT_STABLE_SINCE = None
        else:
            log_http_error(response.status_code, response.text)

            # Treat only server-side failures as downtime; 4xx means reachable but misconfigured/request issue
            if response.status_code >= 500:
                current_time = time.time()
                if AGENT_DOWN_SINCE is None:
                    AGENT_DOWN_SINCE = current_time
                    logging.warning("Agent detected as unreachable")
                AGENT_STABLE_SINCE = None  # Any failure cancels the stability window

                downtime = current_time - AGENT_DOWN_SINCE
                if downtime >= AGENT_ALERT_DELAY_SECONDS and not AGENT_DOWN_ALERT_SENT:
                    node_name = get_node_name_for_alert()
                    alert_message = build_agent_down_alert(node_name)

                    if send_deduplicated_agent_alert("down", node_name, alert_message):
                        AGENT_DOWN_ALERT_SENT = True
                        logging.warning(f"Critical alert sent: Agent down for {format_downtime(downtime)}")
    except Exception as e:
        flush_suppressed_http_error_logs()
        logging.error(f"Connection error: {e}")

        current_time = time.time()
        if AGENT_DOWN_SINCE is None:
            AGENT_DOWN_SINCE = current_time
            logging.warning("Agent detected as unreachable")
        AGENT_STABLE_SINCE = None  # Any failure cancels the stability window

        downtime = current_time - AGENT_DOWN_SINCE
        if downtime >= AGENT_ALERT_DELAY_SECONDS and not AGENT_DOWN_ALERT_SENT:
            node_name = get_node_name_for_alert()
            alert_message = build_agent_down_alert(node_name)

            if send_deduplicated_agent_alert("down", node_name, alert_message):
                AGENT_DOWN_ALERT_SENT = True
                logging.warning(f"Critical alert sent: Agent down for {format_downtime(downtime)}")

def main():
    # Check and update environment variables
    ensure_env_variables()
    
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