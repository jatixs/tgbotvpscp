import os
import time
import subprocess
import requests
import logging
import re
import json
import sys
import glob
from datetime import datetime, timedelta
from typing import Optional, Callable

try:
    import docker
    import docker.errors
    from docker.client import DockerClient

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
BASE_DIR_WATCHDOG = os.path.dirname(__file__)
CORE_DIR_WATCHDOG = os.path.join(BASE_DIR_WATCHDOG, "core")
if CORE_DIR_WATCHDOG not in sys.path:
    sys.path.insert(0, BASE_DIR_WATCHDOG)
try:
    from core import config
    from core.i18n import get_text, load_user_settings
    from core.utils import escape_html
except ImportError as e:
    print(f"FATAL: Could not import core modules: {e}")
    print(
        "Ensure watchdog.py is run from the correct directory (/opt-tg-bot) and venv."
    )
    sys.exit(1)
ALERT_BOT_TOKEN = config.TOKEN
ALERT_ADMIN_ID = config.ADMIN_USER_ID
DEPLOY_MODE = config.DEPLOY_MODE
dotenv_path = os.path.join(BASE_DIR_WATCHDOG, ".env")
env_vars = {}
try:
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and (not line.startswith("#")) and ("=" in line):
                key, value = line.split("=", 1)
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                env_vars[key.strip()] = value.strip()
except Exception as e:
    print(f"WARNING: Could not read .env file for TG_BOT_NAME: {e}")
BOT_NAME = env_vars.get("TG_BOT_NAME", "VPS Bot")
if DEPLOY_MODE == "docker":
    BOT_SERVICE_NAME = env_vars.get("TG_BOT_CONTAINER_NAME", "tg-bot-root")
else:
    BOT_SERVICE_NAME = "tg-bot.service"
WATCHDOG_SERVICE_NAME = "tg-watchdog.service"
CONFIG_DIR = config.CONFIG_DIR
RESTART_FLAG_FILE = config.RESTART_FLAG_FILE
REBOOT_FLAG_FILE = config.REBOOT_FLAG_FILE
BOT_LOG_DIR = config.BOT_LOG_DIR
WATCHDOG_LOG_DIR = config.WATCHDOG_LOG_DIR
CHECK_INTERVAL_SECONDS = 5
ALERT_COOLDOWN_SECONDS = 300
config.setup_logging(WATCHDOG_LOG_DIR, "watchdog")
last_alert_times = {}
bot_service_was_down_or_activating = False
status_alert_message_id = None
current_reported_state = None
down_time_start = None
last_service_start_dt = None

docker_client: Optional[DockerClient] = None
if DEPLOY_MODE == "docker":
    if DOCKER_AVAILABLE:
        try:
            docker_client = docker.from_env()
            docker_client.ping()
            logging.info("Успешное подключение к Docker API.")
        except docker.errors.DockerException:
            logging.critical(
                "Не удалось подключиться к Docker socket. Убедитесь, что /var/run/docker.sock смонтирован."
            )
            docker_client = None
        except Exception as e:
            logging.critical(
                f"Неожиданная ошибка при инициализации Docker клиента: {e}"
            )
            docker_client = None
    else:
        logging.critical(
            "Режим Docker, но библиотека 'docker' не установлена! Watchdog не сможет работать."
        )


def get_system_uptime() -> str:
    """Получает аптайм системы из /proc/uptime"""
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        return str(timedelta(seconds=int(uptime_seconds)))
    except Exception:
        return "N/A"


def get_last_backup_info() -> str:
    """Находит последний бэкап и возвращает локализованную строку статуса"""
    load_user_settings()
    try:
        traffic_dir = getattr(config, 'TRAFFIC_BACKUP_DIR', None)
        if not traffic_dir or not os.path.exists(traffic_dir):
            return get_text("wd_backup_dir_not_found", ALERT_ADMIN_ID)
        
        files = glob.glob(os.path.join(traffic_dir, "traffic_backup_*.json"))
        if not files:
            return get_text("wd_backup_traffic_none", ALERT_ADMIN_ID)
            
        latest_file = max(files, key=os.path.getmtime)
        mod_time = os.path.getmtime(latest_file)
        dt = datetime.fromtimestamp(mod_time)
        
        return get_text("wd_backup_traffic_found", ALERT_ADMIN_ID, date=dt.strftime('%Y-%m-%d %H:%M'))
    except Exception as e:
        return get_text("wd_backup_error", ALERT_ADMIN_ID, error=str(e))


def process_startup_flags():
    """Проверяет флаги перезагрузки/рестарта и уведомляет пользователей"""
    
    load_user_settings() 
    
    if os.path.exists(RESTART_FLAG_FILE):
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
            
            if ":" in content:
                chat_id_str, message_id_str = content.split(":", 1)
                chat_id = int(chat_id_str)
                message_id = int(message_id_str)
                text = f"✅ {get_text('utils_bot_restarted', chat_id)}"
                
                url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/editMessageText"
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "reply_markup": json.dumps({"inline_keyboard": []})
                }
                requests.post(url, data=payload, timeout=5)
                logging.info(f"Processed restart flag for chat {chat_id}")
        except Exception as e:
            logging.error(f"Error processing restart flag: {e}")
        finally:
            try:
                os.remove(RESTART_FLAG_FILE)
            except Exception:
                pass

    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                uid_str = f.read().strip()
            
            if uid_str.isdigit():
                chat_id = int(uid_str)
                text = f"✅ {get_text('utils_server_rebooted', chat_id)}"
                
                url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
                requests.post(url, data=payload, timeout=5)
                logging.info(f"Processed reboot flag for chat {chat_id}")
        except Exception as e:
            logging.error(f"Error processing reboot flag: {e}")
        finally:
            try:
                os.remove(REBOOT_FLAG_FILE)
            except Exception:
                pass


def send_or_edit_telegram_alert(
    message_key: str, alert_type: str, message_id_to_edit=None, **kwargs
):
    global last_alert_times, status_alert_message_id
    load_user_settings()
    
    current_time = time.time()
    apply_cooldown = alert_type in [
        "bot_restart_fail",
        "watchdog_config_error",
        "watchdog_error",
        "bot_service_error_on_start",
    ]
    if (
        apply_cooldown
        and current_time - last_alert_times.get(alert_type, 0) < ALERT_COOLDOWN_SECONDS
    ):
        logging.warning(f"Активен кулдаун для '{alert_type}', пропуск уведомления.")
        return message_id_to_edit
    
    if alert_type in ["bot_service_up_ok", "watchdog_start"]:
        alert_prefix = ""
    else:
        alert_prefix = get_text("watchdog_alert_prefix", ALERT_ADMIN_ID) + "\n\n"

    if not message_key:
        logging.error(
            f"send_or_edit_telegram_alert вызван с пустым message_key для alert_type '{alert_type}'"
        )
        message_body = get_text("error_internal", ALERT_ADMIN_ID)
    else:
        message_body = get_text(message_key, ALERT_ADMIN_ID, **kwargs)
    
    text_to_send = f"{alert_prefix}{message_body}"

    extra_info = []
    if kwargs.get("downtime") and kwargs.get("downtime") != "N/A":
        extra_info.append(get_text("wd_downtime", ALERT_ADMIN_ID, value=kwargs['downtime']))
    if kwargs.get("uptime"):
        extra_info.append(get_text("wd_uptime", ALERT_ADMIN_ID, value=kwargs['uptime']))
    if kwargs.get("last_backup"):
        extra_info.append(get_text("wd_last_backup", ALERT_ADMIN_ID, value=kwargs['last_backup']))
    
    if extra_info:
        text_to_send += "\n\n" + "\n".join(extra_info)

    message_sent_or_edited = False
    new_message_id = message_id_to_edit
    empty_kb = json.dumps({"inline_keyboard": []})

    if message_id_to_edit:
        url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": ALERT_ADMIN_ID,
            "message_id": message_id_to_edit,
            "text": text_to_send,
            "parse_mode": "HTML",
            "reply_markup": empty_kb 
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                logging.info(f"Telegram-сообщение ID {message_id_to_edit} отредактировано ('{alert_type}').")
                message_sent_or_edited = True
                if apply_cooldown:
                    last_alert_times[alert_type] = current_time
            elif response.status_code == 400:
                logging.debug(f"Сообщение ID {message_id_to_edit} не изменено.")
                message_sent_or_edited = True
            else:
                logging.warning(f"Ошибка редактирования {message_id_to_edit}: {response.text}")
                status_alert_message_id = None
                new_message_id = None
        except Exception as e:
            logging.error(f"Ошибка при редактировании: {e}")
            status_alert_message_id = None
            new_message_id = None
            
    if not message_sent_or_edited:
        url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": ALERT_ADMIN_ID,
            "text": text_to_send,
            "parse_mode": "HTML",
            "reply_markup": empty_kb
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                sent_data = response.json()
                new_message_id = sent_data.get("result", {}).get("message_id")
                logging.info(f"Telegram-оповещение '{alert_type}' отправлено (ID {new_message_id}).")
                if apply_cooldown:
                    last_alert_times[alert_type] = current_time
            else:
                logging.error(f"Ошибка отправки '{alert_type}': {response.text}")
                new_message_id = None
        except Exception as e:
            logging.error(f"Ошибка при отправке '{alert_type}': {e}")
            new_message_id = None
            
    return new_message_id


def check_bot_log_for_errors():
    current_bot_log_file = os.path.join(BOT_LOG_DIR, "bot.log")
    try:
        if not os.path.exists(current_bot_log_file):
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_log = os.path.join(BOT_LOG_DIR, f"bot.log.{yesterday}")
            if os.path.exists(yesterday_log):
                current_bot_log_file = yesterday_log
            else:
                return (None, {})
        result = subprocess.run(
            ["tail", "-n", "20", current_bot_log_file],
            capture_output=True, text=True, check=False, encoding="utf-8", errors="ignore",
        )
        if result.returncode != 0:
            return ("watchdog_log_read_error", {"error": result.stderr or "Unknown error"})
            
        log_content = result.stdout
        if "critical" in log_content.lower() or "error" in log_content.lower():
            last_error_line = ""
            for line in log_content.splitlines():
                if "ERROR" in line or "CRITICAL" in line:
                    last_error_line = line
            if last_error_line:
                return ("watchdog_log_error_found_details", {"details": f"...{escape_html(last_error_line)[-150:]}"})
            return ("watchdog_log_error_found_generic", {})
        return ("OK", {})
    except Exception as e:
        return ("watchdog_log_exception", {"error": escape_html(str(e))})

def parse_docker_timestamp(ts_str):
    try:
        ts = ts_str.replace("Z", "")
        if "." in ts:
            main, frac = ts.split(".", 1)
            ts = f"{main}.{frac[:6]}"
        return datetime.fromisoformat(ts)
    except:
        return None

def parse_systemd_timestamp(ts_str):
    try:
        parts = ts_str.split()
        date_part = next((p for p in parts if p.count("-") == 2), None)
        time_part = next((p for p in parts if p.count(":") == 2), None)
        if date_part and time_part:
            return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
    except:
        return None


def check_bot_service_systemd():
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state, last_service_start_dt
    actual_state = "unknown"
    status_output_full = "N/A"
    current_start_dt = None
    is_utc = False
    
    try:
        cmd = ["systemctl", "show", BOT_SERVICE_NAME, "-p", "ActiveState,SubState,ActiveEnterTimestamp"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        props = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v.strip()
        
        active_state = props.get("ActiveState", "unknown")
        sub_state = props.get("SubState", "unknown")
        timestamp_str = props.get("ActiveEnterTimestamp", "")
        
        if active_state == "active" and sub_state == "running":
            actual_state = "active"
            current_start_dt = parse_systemd_timestamp(timestamp_str)
        elif active_state == "activating":
            actual_state = "activating"
        elif active_state == "inactive" or active_state == "failed":
            actual_state = "inactive" if active_state == "inactive" else "failed"
            status_res = subprocess.run(["systemctl", "status", BOT_SERVICE_NAME], capture_output=True, text=True)
            status_output_full = status_res.stdout.strip()
            
    except Exception as e:
        logging.error(f"Systemd check error: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)
        return

    def restart_service_systemd():
        try:
            subprocess.run(["sudo", "systemctl", "restart", BOT_SERVICE_NAME], check=True)
        except Exception as e:
            send_or_edit_telegram_alert("watchdog_restart_fail", "bot_restart_fail", None, service_name=BOT_SERVICE_NAME, error=str(e))

    process_service_state(actual_state, status_output_full, restart_service_systemd, current_start_dt, is_utc)


def check_bot_service_docker():
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state
    if not docker_client:
        return
    actual_state = "unknown"
    container_status = "not_found"
    current_start_dt = None
    is_utc = True 
    container = None
    
    try:
        container = docker_client.containers.get(BOT_SERVICE_NAME)
        container_status = container.status
        if container_status == "running":
            actual_state = "active"
            ts_str = container.attrs['State']['StartedAt']
            current_start_dt = parse_docker_timestamp(ts_str)
        elif container_status == "restarting":
            actual_state = "activating"
        elif container_status in ["exited", "dead"]:
            actual_state = "failed"
        else:
            actual_state = "inactive"
    except docker.errors.NotFound:
        actual_state = "inactive"
    except Exception as e:
        logging.error(f"Docker check error: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)
        return

    def restart_service_docker():
        if container:
            try:
                container.restart(timeout=10)
            except Exception as e:
                send_or_edit_telegram_alert("watchdog_restart_fail", "bot_restart_fail", None, service_name=BOT_SERVICE_NAME, error=str(e))

    process_service_state(actual_state, f"Docker status: {container_status}", restart_service_docker, current_start_dt, is_utc)


def process_service_state(
    actual_state: str, 
    status_output_full: str, 
    restart_function: Callable[[], None],
    current_start_dt: Optional[datetime] = None,
    is_utc: bool = False
):
    global bot_service_was_down_or_activating, status_alert_message_id, current_reported_state, down_time_start, last_service_start_dt
    state_to_report = None
    alert_type = None
    message_key = None
    message_kwargs = {"bot_name": BOT_NAME}
    
    is_restart_detected = False
    
    if actual_state == "active" and current_start_dt:
        if last_service_start_dt is None:
            last_service_start_dt = current_start_dt
            now = datetime.utcnow() if is_utc else datetime.now()
            try:
                if (now - current_start_dt).total_seconds() < 120:
                    logging.info("Обнаружен свежий запуск бота.")
                    is_restart_detected = True
            except Exception as e:
                logging.warning(f"Ошибка сравнения времени: {e}")
                
        elif current_start_dt != last_service_start_dt:
            logging.info(f"Обнаружено изменение времени запуска.")
            last_service_start_dt = current_start_dt
            is_restart_detected = True

    if is_restart_detected:
        bot_service_was_down_or_activating = True
        if down_time_start is None:
             down_time_start = time.time()

    restart_flag_exists = os.path.exists(RESTART_FLAG_FILE)

    if restart_flag_exists and actual_state != "active":
        state_to_report = "restarting"
        alert_type = "bot_service_restarting"
        message_key = "watchdog_status_restarting_bot"
        bot_service_was_down_or_activating = True
        if down_time_start is None: down_time_start = time.time()
            
    elif restart_flag_exists and actual_state == "active":
        pass
    
    elif actual_state == "active":
        if bot_service_was_down_or_activating:
            time.sleep(2)
            log_status_key, log_kwargs = check_bot_log_for_errors()
            
            if log_status_key == "OK":
                state_to_report = "active_ok"
                alert_type = "bot_service_up_ok"
                message_key = "watchdog_status_active_ok"
                
                downtime_str = "N/A"
                if down_time_start:
                    d_seconds = int(time.time() - down_time_start)
                    downtime_str = str(timedelta(seconds=d_seconds))
                    down_time_start = None
                
                message_kwargs["downtime"] = downtime_str
                message_kwargs["uptime"] = get_system_uptime()
                message_kwargs["last_backup"] = get_last_backup_info()
                process_startup_flags()
                
            elif log_status_key:
                state_to_report = "active_error"
                alert_type = "bot_service_up_error"
                message_key = "watchdog_status_active_error"
                message_kwargs["details"] = get_text(log_status_key, ALERT_ADMIN_ID, **log_kwargs)
                process_startup_flags()
            else:
                state_to_report = "active_ok"
                alert_type = "bot_service_up_no_log_file"
                message_key = "watchdog_status_active_log_fail"
                process_startup_flags()

            bot_service_was_down_or_activating = False

    elif actual_state == "activating" and (not restart_flag_exists):
        state_to_report = "activating"
        alert_type = "bot_service_activating"
        message_key = "watchdog_status_activating"
        bot_service_was_down_or_activating = True
        if down_time_start is None: down_time_start = time.time()
            
    elif actual_state in ["inactive", "failed", "unknown"] and (not restart_flag_exists):
        state_to_report = "down"
        alert_type = "bot_service_down"
        message_key = "watchdog_status_down"
        if down_time_start is None: down_time_start = time.time()
        
        if actual_state == "failed":
            message_kwargs["reason"] = f" ({get_text('watchdog_status_down_failed', ALERT_ADMIN_ID)})"
        else:
            message_kwargs["reason"] = ""
            
        if not bot_service_was_down_or_activating:
            restart_function()
        bot_service_was_down_or_activating = True

    try:
        if state_to_report and state_to_report != current_reported_state:
            msg_id = status_alert_message_id if state_to_report not in ["down", "restarting"] else None
            new_id = send_or_edit_telegram_alert(message_key, alert_type, msg_id, **message_kwargs)
            if new_id:
                status_alert_message_id = new_id
                current_reported_state = state_to_report
    except Exception as e:
        logging.error(f"Alert error: {e}")


if __name__ == "__main__":
    if not ALERT_BOT_TOKEN or not ALERT_ADMIN_ID:
        sys.exit(1)
    load_user_settings()
    
    logging.info(f"Watchdog started. Mode: {DEPLOY_MODE}. Service: {BOT_SERVICE_NAME}")
    send_or_edit_telegram_alert("watchdog_status_restarting_wd", "watchdog_start", None, bot_name=BOT_NAME)
    
    while True:
        if DEPLOY_MODE == "docker":
            if DOCKER_AVAILABLE and docker_client:
                check_bot_service_docker()
            else:
                time.sleep(60)
        else:
            check_bot_service_systemd()
        time.sleep(CHECK_INTERVAL_SECONDS)