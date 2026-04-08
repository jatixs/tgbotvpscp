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
    proc = None
    try:
        # FIXED: Use Popen + communicate() for explicit process lifecycle control
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True  # Create new process group for clean kill
        )
        stdout, stderr = proc.communicate(timeout=120)
        
        if proc.returncode == 0:
            output = stdout.decode('utf-8', errors='ignore')
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
            error = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
            return {"success": False, "error": error[:500]}
    except subprocess.TimeoutExpired:
        # FIXED: Kill zombie process and its entire process group on timeout
        if proc is not None:
            try:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            proc.wait()  # Reap zombie
        return {"success": False, "error": "Timeout (120s)"}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON parse error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

CONF = load_config()
DEBUG_MODE = CONF.get("DEBUG", "false").lower() == "true"


def mask_sensitive_output(text):
    """Mask tokens, passwords, and IPs from output before sending to agent server."""
    if not isinstance(text, str):
        return text
    # Mask hex tokens (32-64 chars)
    text = re.sub(r'\b[a-fA-F0-9]{32,64}\b', '[REDACTED_TOKEN]', text)
    # Mask IP addresses (keep localhost/0.0.0.0)
    text = re.sub(
        r'\b(?!127\.0\.0\.1|0\.0\.0\.0)(\d{1,3}\.){3}\d{1,3}\b',
        '[REDACTED_IP]', text
    )
    # Mask password-like patterns in key=value format
    text = re.sub(r'(?i)(password|passwd|pass|token|secret|key)\s*[=:]\s*\S+',
                  r'\1=[REDACTED]', text)
    return text

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

if not AGENT_BASE_URL or not AGENT_TOKEN:
    logging.error("CRITICAL: AGENT_BASE_URL or AGENT_TOKEN not found in .env")
    sys.exit(1)

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
LAST_AGENT_LANG = AGENT_ALERT_LANG if AGENT_ALERT_LANG in {"ru", "en"} else "ru"

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
    
    # Fallback: use stdlib urllib instead of fragile subprocess curl
    try:
        import urllib.request
        req = urllib.request.Request("https://ifconfig.me/ip", headers={"User-Agent": "curl/7.0"})
        response = urllib.request.urlopen(req, timeout=5)
        res = response.read().decode().strip()
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", res):
            EXTERNAL_IP_CACHE = res
            logging.info(f"External IP updated (urllib): {res}")
            return res
    except Exception as e:
        logging.debug(f"Failed to get IP via urllib fallback: {e}")

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
            try:
                ext_ip = stats.get("external_ip")
                if not ext_ip:
                    proc = subprocess.Popen(
                        ["curl", "-4", "-s", "--max-time", "2", "ifconfig.me"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    stdout, _ = proc.communicate()
                    ext_ip = stdout.decode().strip()
            except Exception:
                ext_ip = "N/A"
            
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
                    "ip": ext_ip,
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
                base_cmd = "DEBIAN_FRONTEND=noninteractive apt update && DEBIAN_FRONTEND=noninteractive apt-get --only-upgrade install -y && apt autoremove -y"
            else:
                base_cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt-get --only-upgrade install -y && sudo apt autoremove -y"

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
                            "output": mask_sensitive_output(html.escape((result.stdout or "")[-2000:]))
                        }
                    }
                else:
                    error_text = result.stderr or result.stdout or "Unknown error"
                    result_payload = {
                        "type": "i18n",
                        "key": "update_fail",
                        "params": {
                            "code": result.returncode,
                            "error": mask_sensitive_output(html.escape(error_text[-2000:]))
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
    global PENDING_RESULTS, SSH_EVENTS, AGENT_DOWN_SINCE, AGENT_DOWN_ALERT_SENT, LAST_AGENT_LANG  # noqa: F824
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
    
    if not agent_is_healthy:
        logging.warning("Agent detected as unreachable")
    
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
            data = response.json()

            # Agent provides preferred language while online; keep it cached for offline alerts.
            response_lang = data.get("alert_lang")
            if response_lang in {"ru", "en"} and response_lang != LAST_AGENT_LANG:
                LAST_AGENT_LANG = response_lang
                logging.info(f"Updated alert language from agent: {LAST_AGENT_LANG}")

            PENDING_RESULTS.clear()
            SSH_EVENTS.clear()

            tasks = data.get("tasks", [])
            for task in tasks:
                cmd = task.get("command", "")
                if cmd in LONG_RUNNING_COMMANDS:
                    threading.Thread(
                        target=execute_command, args=(task,), daemon=True
                    ).start()
                else:
                    execute_command(task)

            # Heartbeat delivery succeeded - reset down state and notify recovery if needed
            if AGENT_DOWN_SINCE is not None:
                downtime = time.time() - AGENT_DOWN_SINCE
                node_name = get_node_name_for_alert()

                if AGENT_DOWN_ALERT_SENT:
                    recovery_message = build_agent_recovery_alert(node_name, downtime)
                    send_critical_telegram_alert(recovery_message)
                    logging.info(f"Agent recovered after {format_downtime(downtime)} downtime")

                AGENT_DOWN_SINCE = None
                AGENT_DOWN_ALERT_SENT = False
        else:
            logging.warning(f"Server returned status: {response.status_code} {response.text}")

            # Treat only server-side failures as downtime; 4xx means reachable but misconfigured/request issue
            if response.status_code >= 500:
                current_time = time.time()
                if AGENT_DOWN_SINCE is None:
                    AGENT_DOWN_SINCE = current_time
                    logging.warning("Agent detected as unreachable")

                downtime = current_time - AGENT_DOWN_SINCE
                if downtime >= AGENT_ALERT_DELAY_SECONDS and not AGENT_DOWN_ALERT_SENT:
                    node_name = get_node_name_for_alert()
                    alert_message = build_agent_down_alert(node_name)

                    if send_critical_telegram_alert(alert_message):
                        AGENT_DOWN_ALERT_SENT = True
                        logging.warning(f"Critical alert sent: Agent down for {format_downtime(downtime)}")
    except Exception as e:
        logging.error(f"Connection error: {e}")

        current_time = time.time()
        if AGENT_DOWN_SINCE is None:
            AGENT_DOWN_SINCE = current_time
            logging.warning("Agent detected as unreachable")

        downtime = current_time - AGENT_DOWN_SINCE
        if downtime >= AGENT_ALERT_DELAY_SECONDS and not AGENT_DOWN_ALERT_SENT:
            node_name = get_node_name_for_alert()
            alert_message = build_agent_down_alert(node_name)

            if send_critical_telegram_alert(alert_message):
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
