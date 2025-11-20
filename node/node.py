import os
import time
import json
import logging
import platform
import asyncio
import requests
import psutil
import subprocess
import threading
import random
from logging.handlers import RotatingFileHandler

AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8080")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
NODE_UPDATE_INTERVAL = int(os.environ.get("NODE_UPDATE_INTERVAL", 5))

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

RESULTS_QUEUE = []
RESULTS_LOCK = threading.Lock()

def escape_html(text):
    if text is None:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

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

def cmd_selftest():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    uptime = get_uptime_str()
    try:
        ip = requests.get("https://api.ipify.org", timeout=2).text
    except:
        ip = "Unknown"

    return (
        f"🛠 <b>Node Status:</b>\n\n"
        f"📊 CPU: <b>{cpu:.1f}%</b>\n"
        f"💾 RAM: <b>{mem:.1f}%</b>\n"
        f"💽 Disk: <b>{disk:.1f}%</b>\n"
        f"⏱ Uptime: <b>{uptime}</b>\n"
        f"🌐 IP: <code>{ip}</code>"
    )

def cmd_top():
    try:
        cmd = "ps aux --sort=-%cpu | head -n 11"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        if len(result) > 3000: result = result[:3000] + "\n..."
        safe_result = escape_html(result)
        return f"🔥 <b>Top Processes:</b>\n<pre>{safe_result}</pre>"
    except Exception as e:
        return f"Error running top: {escape_html(str(e))}"

def cmd_traffic():
    try:
        c1 = psutil.net_io_counters()
        time.sleep(1)
        c2 = psutil.net_io_counters()
        
        rx_speed = c2.bytes_recv - c1.bytes_recv
        tx_speed = c2.bytes_sent - c1.bytes_sent
        
        return (
            f"📡 <b>Network Traffic:</b>\n"
            f"⬇️ Total RX: {format_bytes(c2.bytes_recv)}\n"
            f"⬆️ Total TX: {format_bytes(c2.bytes_sent)}\n\n"
            f"⚡️ <b>Speed (1 sec):</b>\n"
            f"⬇️ {format_bytes(rx_speed)}/s\n"
            f"⬆️ {format_bytes(tx_speed)}/s"
        )
    except Exception as e:
        return f"Error measuring traffic: {escape_html(str(e))}"

def run_iperf_cmd(server, port, direction="dl"):
    try:
        base_cmd = f"iperf3 -c {server} -p {port} -t 5 -4 --json"
        
        if direction == "dl":
            cmd = f"{base_cmd} -R"
        else:
            cmd = base_cmd
            
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode == 0:
            try:
                json_data = json.loads(res.stdout)
                key = 'sum_received' if direction == 'dl' else 'sum_sent'
                if 'end' in json_data:
                    end_data = json_data['end']
                    if key in end_data:
                        bps = end_data[key]['bits_per_second']
                    elif 'sum_sent' in end_data:
                         bps = end_data['sum_sent']['bits_per_second']
                    else:
                        return None, "JSON Key Error"
                    
                    return bps / 1_000_000, None
            except json.JSONDecodeError:
                return None, "JSON Decode Error"
        else:
            err_msg = res.stderr.strip().split('\n')[-1] if res.stderr else "Unknown Error"
            return None, err_msg

    except Exception as e:
        return None, str(e)
    
    return None, "Unknown"

def cmd_speedtest():
    servers = [
        ("ping.online.net", "5209"),
        ("bouygues.testdebit.info", "5209"),
        ("speedtest.uztelecom.uz", "5209")
    ]
    
    logging.info("Starting speedtest sequence...")
    
    report = []
    success = False
    
    for server, port in servers:
        report.append(f"🔄 Trying <b>{server}</b>...")
        
        dl_val, dl_err = run_iperf_cmd(server, port, "dl")
        if dl_val is None:
            report.append(f"   ⬇️ DL Fail: {escape_html(dl_err)}")
            continue
            
        ul_val, ul_err = run_iperf_cmd(server, port, "ul")
        if ul_val is None:
            report.append(f"   ⬇️ DL: {dl_val:.2f} Mbps")
            report.append(f"   ⬆️ UL Fail: {escape_html(ul_err)}")
            continue
            
        return (
            f"🚀 <b>Speedtest Results:</b>\n"
            f"Server: {server}\n\n"
            f"⬇️ <b>Download:</b> {dl_val:.2f} Mbps\n"
            f"⬆️ <b>Upload:</b> {ul_val:.2f} Mbps"
        )

    final_report = "\n".join(report)
    return f"⚠️ <b>Speedtest Failed on all servers:</b>\n<pre>{final_report}</pre>"

def run_command_thread(cmd, user_id):
    res = ""
    try:
        if cmd == "selftest": res = cmd_selftest()
        elif cmd == "uptime": res = f"⏱ <b>Uptime:</b> {get_uptime_str()}"
        elif cmd == "top": res = cmd_top()
        elif cmd == "traffic": res = cmd_traffic()
        elif cmd == "speedtest": res = cmd_speedtest()
        elif cmd == "reboot":
            res = "🔄 <b>Node is rebooting...</b>"
            with RESULTS_LOCK:
                RESULTS_QUEUE.append({"user_id": user_id, "command": cmd, "result": res})
            send_heartbeat()
            os.system("(sleep 2 && /sbin/reboot) &")
            return
        else:
            res = f"⚠️ Unknown command: {escape_html(cmd)}"
    except Exception as e:
        res = f"⚠️ Critical Error executing {cmd}: {escape_html(str(e))}"

    if res:
        with RESULTS_LOCK:
            RESULTS_QUEUE.append({"user_id": user_id, "command": cmd, "result": res})

def get_stats_short():
    net = psutil.net_io_counters()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent,
        "uptime": get_uptime_str(),
        "net_rx": net.bytes_recv,
        "net_tx": net.bytes_sent
    }

def send_heartbeat():
    global RESULTS_QUEUE
    url = f"{AGENT_BASE_URL}/api/heartbeat"
    stats = get_stats_short()
    
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
                logging.info(f"Task: {task['command']}")
                threading.Thread(target=run_command_thread, args=(task['command'], task['user_id'])).start()
        else:
            logging.error(f"Server error: {response.status_code}")
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
        logging.critical("AGENT_TOKEN missing!")
        return

    logging.info(f"Node started. Agent: {AGENT_BASE_URL}")
    psutil.cpu_percent(interval=None)

    while True:
        send_heartbeat()
        time.sleep(NODE_UPDATE_INTERVAL)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass