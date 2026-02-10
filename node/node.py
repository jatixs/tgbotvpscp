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
UPDATE_INTERVAL = int(CONF.get("NODE_UPDATE_INTERVAL", 5))

if not AGENT_BASE_URL or not AGENT_TOKEN:
    logging.error("CRITICAL: AGENT_BASE_URL or AGENT_TOKEN not found in .env")
    sys.exit(1)

PENDING_RESULTS = collections.deque(maxlen=50)
LAST_TRAFFIC_STATS = {}
SSH_EVENTS = collections.deque(maxlen=100)

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
    try:
        net = psutil.net_io_counters()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        freq = psutil.cpu_freq()
        
        ext_ip = get_external_ip()
        
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
        
        # Fallback to HTTPS ping if ICMP failed
        if ping_ms is None:
            try:
                import urllib.request
                t1 = time.time()
                req = urllib.request.Request("https://www.google.com", method="HEAD")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        ping_ms = round((time.time() - t1) * 1000, 1)
            except Exception:
                pass
        
        result = {
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
            "external_ip": ext_ip,
            "ping": ping_ms if ping_ms is not None else "n/a"
        }
        return result
    except Exception as e:
        logging.error(f"Error gathering stats: {e}")
        return {}

def get_public_iperf_server():
    """Get best iperf3 server by measuring ping to multiple servers"""
    try:
        url = "https://export.iperf3serverlist.net/listed_iperf3_servers.json"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            servers = response.json()
            valid_servers = [s for s in servers if s.get("IP/HOST") and s.get("PORT") and s.get("COUNTRY") != "RU"]
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
                # Security: Use exec instead of shell
                proc = subprocess.Popen(
                    ["ps", "aux"],
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
            server = get_public_iperf_server()
            if server:
                host = server.get("IP/HOST")
                port = server.get("PORT")
                city = server.get("SITE", "Unknown")
                country = server.get("COUNTRY", "")
                ping_ms = server.get("_ping", 0)  # Get ping from server selection
                
                # Download test with JSON output (-J flag, -R for reverse/download)
                cmd_dl = ["iperf3", "-c", host, "-p", str(port), "-J", "-t", "5", "-4", "-R"]
                try:
                    res_dl = subprocess.check_output(
                        cmd_dl, stderr=subprocess.STDOUT, timeout=30).decode()
                    dl_speed = parse_iperf_json(res_dl, 'download')
                except subprocess.TimeoutExpired:
                    dl_speed = 0.0
                except Exception as e:
                    logging.error(f"DL Test failed: {e}")
                    dl_speed = 0.0
                
                # Upload test with JSON output (-J flag)
                cmd_ul = ["iperf3", "-c", host, "-p", str(port), "-J", "-t", "5", "-4"]
                try:
                    res_ul = subprocess.check_output(
                        cmd_ul, stderr=subprocess.STDOUT, timeout=30).decode()
                    ul_speed = parse_iperf_json(res_ul, 'upload')
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
                        "ping": ping_ms,
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

def send_heartbeat():
    global PENDING_RESULTS, SSH_EVENTS  # noqa: F824
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    current_results = list(PENDING_RESULTS)
    current_ssh_events = list(SSH_EVENTS)
    
    # Get services status periodically
    services = []
    try:
        services = get_services_status()
    except Exception as e:
        logging.debug(f"Failed to get services status: {e}")
    
    payload_dict = {
        "token": AGENT_TOKEN,
        "stats": get_system_stats(),
        "results": current_results,
        "ssh_logins": current_ssh_events,
        "services": services,
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
            PENDING_RESULTS.clear()
            SSH_EVENTS.clear()

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