import os
import json
import logging
import re
import asyncio
import urllib.parse
import time
import aiohttp
import base64
import hashlib
import requests
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
try:
    from PIL import Image
except ImportError:
    Image = None

from . import config
from . import shared_state
from .i18n import get_text, get_user_lang
from .config import INSTALL_MODE, DEPLOY_MODE, DEBUG_MODE
from .config import (
    ALERTS_CONFIG_FILE,
    REBOOT_FLAG_FILE,
    RESTART_FLAG_FILE,
    CIPHER_SUITE,
    DATA_ENCRYPTION_KEY,
)
from .config import load_encrypted_json, save_encrypted_json


def anonymize_user(user_id: int, username: str = None) -> str:
    if DEBUG_MODE:
        user_str = f"User:{user_id}"
        if username:
            user_str += f" (@{username})"
        return user_str
    else:
        return "[USER]"


def encrypt_data(data: str) -> str:
    if not data:
        return ""
    try:
        return CIPHER_SUITE.encrypt(data.encode()).decode()
    except Exception as e:
        logging.error(f"Encryption error: {e}")
        return data


def decrypt_data(data: str) -> str:
    if not data:
        return ""
    try:
        return CIPHER_SUITE.decrypt(data.encode()).decode()
    except Exception:
        return data


def get_web_key() -> str:
    return hashlib.sha256(DATA_ENCRYPTION_KEY).hexdigest()[:32]


def encrypt_for_web(text: str) -> str:
    if not text:
        return ""
    try:
        key = get_web_key()
        text_str = str(text)
        encrypted_chars = []
        for i in range(len(text_str)):
            key_char = key[i % len(key)]
            encrypted_char = chr(ord(text_str[i]) ^ ord(key_char))
            encrypted_chars.append(encrypted_char)
        return base64.b64encode("".join(encrypted_chars).encode()).decode()
    except Exception as e:
        logging.error(f"Web encrypt error: {e}")
        return str(text)


def decrypt_for_web(text: str) -> str:
    if not text:
        return ""
    try:
        key = get_web_key()
        decoded_str = base64.b64decode(text).decode()
        decrypted_chars = []
        for i in range(len(decoded_str)):
            key_char = key[i % len(key)]
            decrypted_char = chr(ord(decoded_str[i]) ^ ord(key_char))
            decrypted_chars.append(decrypted_char)
        return "".join(decrypted_chars)
    except Exception as e:
        logging.error(f"Web decrypt error: {e}")
        return text


def get_host_path(path: str) -> str:
    if DEPLOY_MODE == "docker":
        if INSTALL_MODE == "root":
            if not path.startswith("/"):
                path = "/" + path
            host_path = f"/host{path}"
            if os.path.exists(host_path):
                return host_path
            elif os.path.exists(path):
                return path
            else:
                return host_path
        elif INSTALL_MODE == "secure":
            if path.startswith("/proc/"):
                secure_path = path.replace("/proc/", "/proc_host/", 1)
                if os.path.exists(secure_path):
                    return secure_path
    return path


def load_alerts_config():
    try:
        loaded_data = load_encrypted_json(ALERTS_CONFIG_FILE)
        if loaded_data:
            loaded_data_int_keys = {int(k): v for k, v in loaded_data.items()}
            shared_state.ALERTS_CONFIG.clear()
            shared_state.ALERTS_CONFIG.update(loaded_data_int_keys)
            logging.info("Alerts config loaded (secure).")
        else:
            shared_state.ALERTS_CONFIG.clear()
            logging.info("Alerts config empty or not found.")
    except Exception as e:
        logging.error(f"Error loading alerts_config.json: {e}")
        shared_state.ALERTS_CONFIG.clear()


def save_alerts_config():
    try:
        os.makedirs(os.path.dirname(ALERTS_CONFIG_FILE), exist_ok=True)
        config_to_save = {str(k): v for k, v in shared_state.ALERTS_CONFIG.items()}
        save_encrypted_json(ALERTS_CONFIG_FILE, config_to_save)
    except Exception as e:
        logging.error(f"Error saving alerts_config.json: {e}")


async def get_country_flag(ip_or_code: str) -> str:
    if not ip_or_code or ip_or_code in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"
    input_str = ip_or_code.strip().upper()
    if len(input_str) == 2 and input_str.isalpha():
        return "".join((chr(ord(char) - 65 + 127462) for char in input_str))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{ip_or_code}?fields=countryCode,status",
                timeout=2,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        country_code = data.get("countryCode")
                        if country_code and len(country_code) == 2:
                            return "".join(
                                (
                                    chr(ord(char.upper()) - 65 + 127462)
                                    for char in country_code
                                )
                            )
    except Exception as e:
        logging.warning(f"Error getting flag for {ip_or_code}: {e}")
    return "❓"


async def get_country_details(ip_or_code: str):
    flag = await get_country_flag(ip_or_code)
    country_name = None
    identifier = ip_or_code.strip().upper()
    if not identifier or identifier in ["localhost", "127.0.0.1", "::1"]:
        return ("🏠", None)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{identifier}?fields=country,status", timeout=2
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        country_name = data.get("country")
    except Exception as e:
        logging.warning(f"Error getting country details for {identifier}: {e}")
    return (flag, country_name)


def escape_html(text):
    if text is None:
        return ""
    text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def convert_json_to_vless(json_data, custom_name):
    try:
        config_data = json.loads(json_data)
        outbounds = config_data.get("outbounds")
        if not outbounds:
            raise ValueError("No outbounds")
        outbound = next((ob for ob in outbounds if ob.get("protocol") == "vless"), None)
        if not outbound:
            raise ValueError("No vless outbound")
        settings = outbound.get("settings")
        vnext = settings.get("vnext")
        if not vnext:
            raise ValueError("No vnext")
        server_info = vnext[0]
        user = server_info.get("users")[0]
        stream_settings = outbound.get("streamSettings")
        reality_settings = stream_settings.get("realitySettings")
        uuid = user["id"]
        address = server_info["address"]
        port = server_info["port"]
        host = reality_settings["serverName"]
        pbk = reality_settings["publicKey"]
        sid = reality_settings["shortId"]
        net_type = stream_settings["network"]
        params = {
            "security": "reality",
            "pbk": pbk,
            "host": host,
            "sni": host,
            "sid": sid,
            "type": net_type,
        }
        if "flow" in user:
            params["flow"] = user["flow"]
        if "fingerprint" in reality_settings:
            params["fp"] = reality_settings["fingerprint"]
        base = f"vless://{uuid}@{address}:{port}"
        encoded_params = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        encoded_name = urllib.parse.quote(custom_name)
        return f"{base}?{encoded_params}#{encoded_name}"
    except Exception as e:
        logging.error(f"VLESS convert error: {e}")
        return f"Error: {e}"


def format_traffic(bytes_value, lang: str):
    units = [
        get_text("unit_bytes", lang),
        get_text("unit_kb", lang),
        get_text("unit_mb", lang),
        get_text("unit_gb", lang),
        get_text("unit_tb", lang),
    ]
    try:
        value = float(bytes_value)
    except (ValueError, TypeError):
        return f"0 {units[0]}"
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"


def format_uptime(seconds, lang: str):
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return f"0{get_text('unit_second_short', lang)}"
    days = seconds // (24 * 3600)
    seconds %= 24 * 3600
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    day_unit = get_text("unit_day_short", lang)
    hour_unit = get_text("unit_hour_short", lang)
    min_unit = get_text("unit_minute_short", lang)
    parts = []
    if days > 0:
        parts.append(f"{days}{day_unit}")
    if hours > 0:
        parts.append(f"{hours}{hour_unit}")
    parts.append(f"{minutes}{min_unit}")
    return " ".join(parts)


def get_server_timezone_label():
    try:
        is_dst = time.daylight and time.localtime().tm_isdst > 0
        offset_seconds = -time.altzone if is_dst else -time.timezone
        offset_hours = offset_seconds // 3600
        return f" (GMT{('+' if offset_hours >= 0 else '')}{offset_hours})"
    except Exception:
        return ""


async def detect_xray_client():
    try:
        # Use subprocess.exec instead of shell for better security
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "--format", "{{.Names}} {{.Image}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()
        if not output:
            return (None, None)
        for line in output.split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                name, image = (parts[0], parts[1])
                if (
                    "amnezia" in image.lower()
                    and "xray" in image.lower()
                    or name == "amnezia-xray"
                ):
                    return ("amnezia", name)
                if "marzban" in image.lower() or "marzban" in name:
                    return ("marzban", name)
        return (None, None)
    except Exception:
        return (None, None)


async def initial_restart_check(bot: Bot):
    if os.path.exists(RESTART_FLAG_FILE):
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
            if ":" in content:
                cid, mid = content.split(":", 1)
                await bot.edit_message_text(
                    chat_id=int(cid),
                    message_id=int(mid),
                    text=get_text("utils_bot_restarted", get_user_lang(int(cid))),
                )
        except Exception as e:
            logging.error(f"Restart check error: {e}")
        finally:
            if os.path.exists(RESTART_FLAG_FILE):
                os.remove(RESTART_FLAG_FILE)


async def initial_reboot_check(bot: Bot):
    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                uid = int(f.read().strip())
            await bot.send_message(
                chat_id=uid,
                text=get_text("utils_server_rebooted", get_user_lang(uid)),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Reboot check error: {e}")
        finally:
            if os.path.exists(REBOOT_FLAG_FILE):
                os.remove(REBOOT_FLAG_FILE)


def get_app_version() -> str:
    if config.INSTALLED_VERSION:
        ver = config.INSTALLED_VERSION.strip()
        return ver if ver.startswith("v") else f"v{ver}"
    try:
        changelog_path = os.path.join(config.BASE_DIR, "CHANGELOG.md")
        if os.path.exists(changelog_path):
            with open(changelog_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search("## \\[(\\d+\\.\\d+\\.\\d+)\\]", content)
                if match:
                    return f"v{match.group(1)}"
    except Exception:
        pass
    return "v1.0.0"


def update_env_variable(key: str, value: str, env_path: str = None):
    if env_path is None:
        try:
            from core import config

            env_path = config.ENV_FILE_PATH
        except ImportError:
            env_path = "/opt/tg-bot/.env"
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        new_lines = []
        found = False
        value_str = str(value).replace('"', '\\"')
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f'{key}="{value_str}"\n')
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f'{key}="{value_str}"\n')
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 384)
        with os.fdopen(fd, "w") as f:
            f.writelines(new_lines)
    except Exception as e:
        logging.error(f"Error updating env variable {key}: {e}")


def generate_favicons(source_url_or_path: str, output_dir: str):
    """
    Generates a set of favicons and a manifest from the source image.
    Supports: URL (http), Local path, Base64 (data:image).
    Completely overwrites the target directory content.
    """
    if not Image:
        logging.error("Pillow not installed. Cannot generate favicons.")
        return False

    # 0. Clean directory before generation
    if os.path.exists(output_dir):
        try:
            for filename in os.listdir(output_dir):
                file_path = os.path.join(output_dir, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            logging.info(f"Favicon directory {output_dir} cleaned.")
        except Exception as e:
            logging.error(f"Error cleaning favicon directory: {e}")
    else:
        os.makedirs(output_dir, exist_ok=True)

    try:
        img = None
        
        # 1. Load image (Base64 / URL / Path)
        if source_url_or_path.startswith('data:image'):
            try:
                # Handle Base64 (data:image/png;base64,...)
                if "," in source_url_or_path:
                    header, encoded = source_url_or_path.split(",", 1)
                else:
                    encoded = source_url_or_path
                img_data = base64.b64decode(encoded)
                img = Image.open(BytesIO(img_data))
            except Exception as e:
                logging.error(f"Failed to decode base64 image: {e}")
                return False
                
        elif source_url_or_path.startswith('http'):
            try:
                response = requests.get(source_url_or_path, timeout=10)
                if response.status_code == 200:
                    img = Image.open(BytesIO(response.content))
            except Exception as e:
                logging.error(f"Failed to download image: {e}")
                
        elif os.path.exists(source_url_or_path):
            img = Image.open(source_url_or_path)

        if not img:
            log_source = source_url_or_path[:50] + "..." if len(source_url_or_path) > 50 else source_url_or_path
            logging.error(f"Failed to load source image for favicon: {log_source}")
            return False

        # Convert to RGBA to preserve transparency
        img = img.convert("RGBA")
        
        # Default theme for manifest (white)
        theme_color_hex = "#ffffff"

        # 2. Slice and save PNG (with transparency)
        icons_config = [
            ("favicon-16x16.png", (16, 16)),
            ("favicon-32x32.png", (32, 32)),
            ("apple-touch-icon.png", (180, 180)),
            ("android-chrome-192x192.png", (192, 192)),
            ("android-chrome-512x512.png", (512, 512))
        ]

        for filename, size in icons_config:
            resized_img = img.resize(size, Image.Resampling.LANCZOS)
            resized_img.save(os.path.join(output_dir, filename), format="PNG")

        # 3. Save ICO (multi-size, supports transparency)
        img.save(os.path.join(output_dir, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

        # 4. Generate site.webmanifest
        manifest_content = {
            "name": "TG Bot Panel",
            "short_name": "BotPanel",
            "icons": [
                {
                    "src": "/static/favicons/android-chrome-192x192.png",
                    "sizes": "192x192",
                    "type": "image/png"
                },
                {
                    "src": "/static/favicons/android-chrome-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png"
                }
            ],
            "theme_color": theme_color_hex,
            "background_color": theme_color_hex,
            "display": "standalone"
        }
        
        with open(os.path.join(output_dir, "site.webmanifest"), "w", encoding="utf-8") as f:
            json.dump(manifest_content, f, indent=2)

        logging.info(f"Favicons generated successfully in {output_dir}. Theme: {theme_color_hex}")
        return True

    except Exception as e:
        logging.error(f"Error generating favicons: {e}")
        return False


# --- Audit Logging ---

# Path to the audit log file (using config.BASE_DIR)
AUDIT_LOG_DIR = os.path.join(config.BASE_DIR, "logs", "audit")
AUDIT_LOG_FILE = os.path.join(AUDIT_LOG_DIR, "audit.log")

# Audit event types
class AuditEvent:
    # User actions
    USER_ADDED = "USER_ADDED"
    USER_DELETED = "USER_DELETED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    
    # Node actions
    NODE_ADDED = "NODE_ADDED"
    NODE_DELETED = "NODE_DELETED"
    NODE_RENAMED = "NODE_RENAMED"
    
    # System actions
    SYSTEM_UPDATE_STARTED = "SYSTEM_UPDATE_STARTED"
    SYSTEM_UPDATE_COMPLETED = "SYSTEM_UPDATE_COMPLETED"
    SYSTEM_REBOOT = "SYSTEM_REBOOT"
    SYSTEM_RESTART = "SYSTEM_RESTART"
    SYSTEM_OPTIMIZE = "SYSTEM_OPTIMIZE"
    
    # Security settings
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    PASSWORD_RESET = "PASSWORD_RESET"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    KEYBOARD_CHANGED = "KEYBOARD_CHANGED"
    
    # Data actions
    LOGS_CLEARED = "LOGS_CLEARED"
    TRAFFIC_RESET = "TRAFFIC_RESET"
    BACKUP_CREATED = "BACKUP_CREATED"
    BACKUP_RESTORED = "BACKUP_RESTORED"
    
    # Service actions
    SERVICE_STARTED = "SERVICE_STARTED"
    SERVICE_STOPPED = "SERVICE_STOPPED"
    SERVICE_RESTARTED = "SERVICE_RESTARTED"
    
    # Authentication
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_REVOKED = "SESSION_REVOKED"
    
    # Dangerous actions
    SHELL_COMMAND_EXECUTED = "SHELL_COMMAND_EXECUTED"
    FILE_UPLOADED = "FILE_UPLOADED"
    FILE_DELETED = "FILE_DELETED"


def init_audit_log():
    """Initialize audit log directory"""
    try:
        Path(AUDIT_LOG_DIR).mkdir(parents=True, exist_ok=True)
        if not os.path.exists(AUDIT_LOG_FILE):
            with open(AUDIT_LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(f"# Audit Log Started: {datetime.utcnow().isoformat()}Z\n")
    except Exception as e:
        logging.error(f"Failed to initialize audit log: {e}")


def log_audit_event(
    event_type: str,
    user_id: int,
    details: Optional[Dict[str, Any]] = None,
    severity: str = "INFO",
    ip_address: Optional[str] = None
):
    """
    Records an audit event to the log
    
    Args:
        event_type: Event type (from AuditEvent)
        user_id: Telegram User ID
        details: Additional event details (will be serialized to JSON)
        severity: Severity level (INFO, WARNING, CRITICAL)
        ip_address: User IP address (if available)
    """
    try:
        # Create directory if it doesn't exist
        if not os.path.exists(AUDIT_LOG_DIR):
            init_audit_log()
        
        # Format the entry
        timestamp = datetime.utcnow().isoformat() + "Z"
        is_admin = user_id == config.ADMIN_USER_ID
        role = "ADMIN" if is_admin else "USER"
        
        log_entry = {
            "timestamp": timestamp,
            "event": event_type,
            "user_id": user_id,
            "role": role,
            "severity": severity,
            "ip_address": ip_address or "N/A",
            "details": details or {}
        }
        
        # Write to file
        with open(AUDIT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        
        # Duplicate to main log for critical events
        if severity == "CRITICAL":
            logging.critical(f"AUDIT: {event_type} by user {user_id} | {details}")
        elif severity == "WARNING":
            logging.warning(f"AUDIT: {event_type} by user {user_id}")
        else:
            logging.info(f"AUDIT: {event_type} by user {user_id}")
            
    except Exception as e:
        logging.error(f"Failed to write audit log: {e}")


def get_audit_logs(limit: int = 100, event_filter: Optional[str] = None) -> list:
    """
    Retrieves the latest entries from the audit log
    
    Args:
        limit: Maximum number of entries
        event_filter: Filter by event type
    
    Returns:
        List of audit entries
    """
    try:
        if not os.path.exists(AUDIT_LOG_FILE):
            return []
        
        logs = []
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    entry = json.loads(line)
                    if event_filter and entry.get('event') != event_filter:
                        continue
                    logs.append(entry)
                except json.JSONDecodeError:
                    continue
        
        # Return last N entries
        return logs[-limit:] if len(logs) > limit else logs
        
    except Exception as e:
        logging.error(f"Failed to read audit logs: {e}")
        return []


def clear_old_audit_logs(days_to_keep: int = 90):
    """
    Removes audit entries older than the specified number of days
    
    Args:
        days_to_keep: How many days to keep logs
    """
    try:
        if not os.path.exists(AUDIT_LOG_FILE):
            return
        
        cutoff_time = time.time() - (days_to_keep * 86400)
        temp_file = AUDIT_LOG_FILE + ".tmp"
        kept_count = 0
        removed_count = 0
        
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as f_in:
            with open(temp_file, 'w', encoding='utf-8') as f_out:
                for line in f_in:
                    if line.startswith('#'):
                        f_out.write(line)
                        continue
                    
                    try:
                        entry = json.loads(line.strip())
                        entry_time = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00')).timestamp()
                        
                        if entry_time >= cutoff_time:
                            f_out.write(line)
                            kept_count += 1
                        else:
                            removed_count += 1
                    except (json.JSONDecodeError, KeyError, ValueError):
                        # Keep corrupted entries
                        # Сохраняем поврежденные записи -> Keep corrupted entries
                        f_out.write(line)
        
        # Replace original file
        os.replace(temp_file, AUDIT_LOG_FILE)
        logging.info(f"Audit log cleanup: kept {kept_count}, removed {removed_count} entries")
        
    except Exception as e:
        logging.error(f"Failed to clean audit logs: {e}")
        # Remove temporary file in case of error
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


# Initialize on successful load
init_audit_log()