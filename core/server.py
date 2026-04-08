import logging
import time
import os
import json
import secrets
import asyncio
import hashlib
import ipaddress
from argon2 import PasswordHasher, exceptions as argon2_exceptions
import hmac
import aiohttp
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from collections import deque, OrderedDict
from jinja2 import Environment, FileSystemLoader, select_autoescape
from . import nodes_db
from .config import (
    WEB_SERVER_HOST,
    WEB_SERVER_PORT,
    NODE_OFFLINE_TIMEOUT,
    BASE_DIR,
    ADMIN_USER_ID,
    ENABLE_WEB_UI,
    save_system_config,
    BOT_LOG_DIR,
    WATCHDOG_LOG_DIR,
    NODE_LOG_DIR,
    ADMIN_USERNAME,
    TOKEN,
    save_keyboard_config,
    KEYBOARD_CONFIG,
    DEPLOY_MODE,
    TG_BOT_NAME,
    get_bot_config,
    set_bot_config,
)
from . import config as current_config
from .shared_state import (
    NODE_TRAFFIC_MONITORS,
    ALLOWED_USERS,
    USER_NAMES,
    AUTH_TOKENS,
    ALERTS_CONFIG,
    AGENT_HISTORY,
    WEB_NOTIFICATIONS,
    WEB_USER_LAST_READ,
)
from .i18n import STRINGS, get_user_lang, set_user_lang, get_text as _
from .config import DEFAULT_LANGUAGE
from .utils import (
    get_country_flag,
    save_alerts_config,
    get_host_path,
    get_app_version,
    encrypt_for_web,
    decrypt_for_web,
    get_web_key,
    generate_favicons,
    get_server_timezone_label,
)
from .auth import save_users, get_user_name
from .messaging import send_alert
from .keyboards import BTN_CONFIG_MAP
from modules.services import get_all_services_status, perform_service_action, get_user_role_level, \
    get_all_available_services, add_managed_service, remove_managed_service
from modules import update as update_module
from modules import traffic as traffic_module
from . import shared_state
from .utils import log_audit_event, AuditEvent

# Route modules (extracted from monolithic server.py)
from core.routes.terminal import (
    handle_terminal_page, handle_terminal_ws,
    handle_get_terminal_creds, handle_terminal_stats, handle_save_terminal_creds,
)
from core.routes.api_nodes import (
    handle_heartbeat, process_node_result_background,
    handle_node_details, handle_agent_stats, handle_agent_ipv4,
    handle_reset_traffic, handle_node_add, handle_node_delete, handle_node_rename,
    handle_nodes_list_json, handle_nodes_monitor_page,
    handle_nodes_monitor_list, handle_nodes_monitor_detail,
    handle_nodes_monitor_services, handle_nodes_monitor_command,
    handle_nodes_monitor_service_action,
)
from core.routes.api_frontend import (
    handle_get_logs, handle_get_sys_logs,
    api_get_notifications, api_read_notifications, api_clear_notifications,
    api_check_update, api_run_update,
    api_get_sessions, api_revoke_session, api_revoke_all_sessions,
    handle_dashboard, handle_settings_page,
    handle_save_notifications, handle_save_system_config,
    handle_save_keyboard_config, handle_save_metadata, handle_change_password,
    handle_get_telegram_only_mode, handle_set_telegram_only_mode,
    handle_clear_logs, handle_user_action, handle_set_language,
    handle_session_check_head, handle_login_page,
    handle_login_request, handle_login_password, handle_magic_login,
    handle_telegram_auth as handle_telegram_auth_route,
    handle_logout, handle_reset_request, handle_reset_page_render,
    handle_reset_confirm, handle_api_root,
)
from core.routes.sse import (
    handle_sse_stream, handle_sse_logs, handle_sse_node_details,
    handle_sse_services, handle_services_list,
    api_control_service, api_service_info, api_services_available, api_services_manage,
)

COOKIE_NAME = "vps_agent_session"
CSRF_TOKEN_COOKIE = "csrf_token"
LOGIN_TOKEN_TTL = 300
RESET_TOKEN_TTL = 600
CSRF_TOKEN_TTL = 3600
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "core", "static")
AGENT_FLAG = "🏳️"
AGENT_IP_CACHE = "Loading..."
AGENT_PING_CACHE = "n/a"
AGENT_PING_LAST_UPDATE = 0
AGENT_PING_TIMEOUT = 5  # Ping measurement timeout in seconds
RESET_TOKENS = {}
SERVER_SESSIONS = {}
CSRF_TOKENS = {}  # Store CSRF tokens with expiry
LOGIN_ATTEMPTS = {}
MAX_LOGIN_ATTEMPTS = 5
MAX_API_REQUESTS = 100  # Requests per minute per IP
LOGIN_BLOCK_TIME = 300
API_RATE_WINDOW = 60
BOT_USERNAME_CACHE = None
APP_VERSION = get_app_version()
CACHE_VER = str(int(time.time()))
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max file size
AGENT_TASK = None
RECENT_SSH_LOGINS = {}  # SSH cache for recent logins
JINJA_ENV = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"])
)


def check_rate_limit(ip):
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_BLOCK_TIME]
    LOGIN_ATTEMPTS[ip] = attempts
    return len(attempts) < MAX_LOGIN_ATTEMPTS


def add_login_attempt(ip):
    if ip not in LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[ip] = []
    LOGIN_ATTEMPTS[ip].append(time.time())


class RateLimitStore:
    """LRU-based rate limit storage with safe eviction (no full clear)."""

    def __init__(self, max_size: int = 5000, window: int = API_RATE_WINDOW):
        self._store: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._window = window

    def check(self, key: str, max_requests: int = MAX_API_REQUESTS) -> bool:
        now = time.time()
        # Evict oldest 25% when over capacity (NOT full clear)
        if len(self._store) > self._max_size:
            evict_count = self._max_size // 4
            for _ in range(min(evict_count, len(self._store))):
                self._store.popitem(last=False)

        if key not in self._store:
            self._store[key] = []
        # Remove expired timestamps
        self._store[key] = [t for t in self._store[key] if now - t < self._window]
        if len(self._store[key]) >= max_requests:
            return False
        self._store[key].append(now)
        self._store.move_to_end(key)
        return True

    def clear_expired(self):
        """Remove all entries with only expired timestamps."""
        now = time.time()
        expired_keys = []
        for key, timestamps in self._store.items():
            fresh = [t for t in timestamps if now - t < self._window]
            if not fresh:
                expired_keys.append(key)
            else:
                self._store[key] = fresh
        for key in expired_keys:
            del self._store[key]


API_RATE_LIMITER = RateLimitStore()


def check_api_rate_limit(ip, endpoint):
    """Check API rate limit - max requests per minute."""
    key = f"{ip}:{endpoint}"
    return API_RATE_LIMITER.check(key)


def generate_csrf_token():
    """Generate a secure CSRF token."""
    token = secrets.token_urlsafe(32)
    CSRF_TOKENS[token] = time.time() + CSRF_TOKEN_TTL
    return token


def verify_csrf_token(token):
    """Verify CSRF token validity."""
    if token not in CSRF_TOKENS:
        return False
    if time.time() > CSRF_TOKENS[token]:
        del CSRF_TOKENS[token]
        return False
    # Clean up expired tokens periodically
    if len(CSRF_TOKENS) > 1000:
        now = time.time()
        expired = [t for t, exp_time in CSRF_TOKENS.items() if now > exp_time]
        for t in expired:
            del CSRF_TOKENS[t]
    return True


def mask_sensitive_data(data, mask_length=6):
    """Mask sensitive data like IPs and tokens for logging."""
    if not isinstance(data, str) or len(data) < mask_length:
        return "***"
    return data[:mask_length] + "*" * (len(data) - mask_length)


# WAF (Web Application Firewall) Rules
WAF_ATTACK_PATTERNS = [
    # SQL Injection patterns (очищено от слишком агрессивных символов)
    (r"(?i)(union|select|insert|update|delete|drop|create|alter|exec|execute)\s+", "SQL_INJECTION"),
    (r"(?i)(%20|\s)(or|and)(\s|%20)+.*=", "SQL_INJECTION"),

    # XSS (Cross-Site Scripting) patterns
    (r"(?i)<script[^>]*>.*?</script>", "XSS"),
    (r"(?i)javascript:", "XSS"),
    (r"(?i)on\w+\s*=", "XSS"),
    (r"(?i)<iframe[^>]*>", "XSS"),
    (r"(?i)<embed[^>]*>", "XSS"),
    (r"(?i)<object[^>]*>", "XSS"),

    # Path Traversal patterns
    (r"\.\./", "PATH_TRAVERSAL"),
    (r"\.\.\\", "PATH_TRAVERSAL"),
    (r"%2e%2e/", "PATH_TRAVERSAL"),
    (r"%2e%2e\\", "PATH_TRAVERSAL"),

    (r"[;&|`]", "COMMAND_INJECTION"),
    (r"(?i)(bash|sh|cmd|powershell|wget|curl)\s", "COMMAND_INJECTION"),
]

import re


def check_waf_patterns(data: str) -> tuple[bool, str]:
    """
    Проверяет данные на наличие паттернов атак

    Returns:
        (is_attack, attack_type): True если обнаружена атака, тип атаки
    """
    if not isinstance(data, str):
        return False, ""

    data_lower = data.lower()

    for pattern, attack_type in WAF_ATTACK_PATTERNS:
        if re.search(pattern, data_lower, re.IGNORECASE):
            return True, attack_type

    return False, ""


def validate_input_length(data: str, max_length: int = 1000) -> bool:
    """Checks input data length"""
    if not isinstance(data, str):
        return True
    return len(data) <= max_length


def validate_file_upload(filename: str, content_type: str, file_size: int) -> tuple[bool, str]:
    """
    Валидация загружаемых файлов

    Returns:
        (is_valid, error_message)
    """
    # Разрешенные расширения
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.log', '.zip'}

    # Проверка расширения
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type {ext} not allowed"

    # Проверка размера (50MB)
    if file_size > MAX_FILE_SIZE:
        return False, f"File size {file_size} exceeds limit {MAX_FILE_SIZE}"

    # Проверка MIME type
    allowed_mimes = {
        'image/jpeg', 'image/png', 'image/gif',
        'application/pdf', 'text/plain', 'application/zip'
    }
    if content_type not in allowed_mimes:
        return False, f"Content type {content_type} not allowed"

    return True, ""


def get_client_ip(request):
    peer = request.transport.get_extra_info("peername")
    real_ip = peer[0] if peer else "unknown"
    if real_ip in ("127.0.0.1", "::1", "localhost"):
        xfwd = request.headers.get("X-Forwarded-For")
        if xfwd:
            return xfwd.split(",")[0].strip()
            
    return real_ip


def check_user_password(user_id, input_pass):
    """Securely check user password with constant-time comparison."""
    if user_id not in ALLOWED_USERS:
        # Always perform verification to prevent timing attacks
        PasswordHasher().verify("$argon2id$v=19$m=102400,t=8,p=1$00000000000000000000000000000000$1234567890ABCDEF",
                                "dummy")
        return False
    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, str):
        return False
    stored_hash = user_data.get("password_hash")
    if not stored_hash:
        # Admin user with no password set
        result = user_id == ADMIN_USER_ID and input_pass == "admin"
        # Use constant-time comparison for default password too
        return hmac.compare_digest(str(result), "True")
    ph = PasswordHasher()
    try:
        ph.verify(stored_hash, input_pass)
        return True
    except argon2_exceptions.VerifyMismatchError:
        return False
    except Exception:
        return False


def is_default_password_active(user_id):
    if user_id != ADMIN_USER_ID:
        return False
    if user_id not in ALLOWED_USERS:
        return False
    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, dict):
        p_hash = user_data.get("password_hash")
        if p_hash is None:
            return True
        if p_hash == "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918":
            return True
        try:
            ph = PasswordHasher()
            return ph.verify(p_hash, "admin")
        except Exception:
            return False
    return True


def _get_top_processes(metric):
    import psutil

    def sizeof_fmt(num):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f} {unit}"
            num /= 1024.0
        return f"{num:.1f} PB"

    try:
        attrs = ["pid", "name", "cpu_percent", "memory_percent"]
        if metric == "disk":
            attrs.append("io_counters")
        procs = []
        for p in psutil.process_iter(attrs):
            try:
                p_info = p.info
                p_info["name"] = p_info["name"][:15]
                procs.append(p_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        if metric == "cpu":
            sorted_procs = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[
                :5
            ]
            return [f"{p['name']} ({p['cpu_percent']}%)" for p in sorted_procs]
        elif metric == "ram":
            sorted_procs = sorted(
                procs, key=lambda p: p["memory_percent"], reverse=True
            )[:5]
            return [f"{p['name']} ({p['memory_percent']:.1f}%)" for p in sorted_procs]
        elif metric == "disk":

            def get_io(p):
                io = p.get("io_counters")
                return io.read_bytes + io.write_bytes if io else 0

            sorted_procs = sorted(procs, key=get_io, reverse=True)[:5]
            return [f"{p['name']} ({sizeof_fmt(get_io(p))})" for p in sorted_procs]
        return []
    except Exception as e:
        logging.error(f"Error getting processes: {e}")
        return []


def get_current_user(request):
    token = request.cookies.get(COOKIE_NAME)
    if not token or token not in SERVER_SESSIONS:
        return None
    session = SERVER_SESSIONS[token]
    if time.time() > session["expires"]:
        del SERVER_SESSIONS[token]
        return None
    uid = session["id"]
    if uid not in ALLOWED_USERS:
        return None
    u_data = ALLOWED_USERS[uid]
    role = u_data.get("group", "users") if isinstance(u_data, dict) else u_data
    photo = session.get("photo_url", AGENT_FLAG)
    return {
        "id": uid,
        "role": role,
        "first_name": USER_NAMES.get(str(uid), f"ID: {uid}"),
        "photo_url": photo,
    }


def _get_avatar_html(user):
    raw = user.get("photo_url", "")
    if raw.startswith("http"):
        return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'


def check_telegram_auth(data, bot_token):
    auth_data = data.copy()
    check_hash = auth_data.pop("hash", "")
    if not check_hash:
        return False
    data_check_arr = []
    for key, value in sorted(auth_data.items()):
        data_check_arr.append(f"{key}={value}")
    data_check_string = "\n".join(data_check_arr)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hash_calc = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if hash_calc != check_hash:
        return False
    auth_date = int(auth_data.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return False
    return True

async def cleanup_monitor():
    """Periodic cleanup of expired sessions and tokens to save memory."""
    while True:
        try:
            now = time.time()
            expired_sessions = [token for token, sess in SERVER_SESSIONS.items() if now > sess["expires"]]
            for token in expired_sessions:
                del SERVER_SESSIONS[token]
            expired_resets = [token for token, data in RESET_TOKENS.items() if now - data["ts"] > RESET_TOKEN_TTL]
            for token in expired_resets:
                del RESET_TOKENS[token]
            expired_auth = [token for token, data in AUTH_TOKENS.items() if now - data["created_at"] > LOGIN_TOKEN_TTL]
            for token in expired_auth:
                del AUTH_TOKENS[token]

            # Prevent AUTH_TOKENS memory leak by limiting size
            if len(AUTH_TOKENS) > 1000:
                # Sort by creation time and remove oldest 25%
                sorted_tokens = sorted(AUTH_TOKENS.items(), key=lambda x: x[1]["created_at"])
                remove_count = len(AUTH_TOKENS) // 4
                for token, _ in sorted_tokens[:remove_count]:
                    try:
                        del AUTH_TOKENS[token]
                    except KeyError:
                        pass

            # Clean up API rate limits via LRU store
            API_RATE_LIMITER.clear_expired()
            for ip in list(LOGIN_ATTEMPTS.keys()):
                LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < LOGIN_BLOCK_TIME]
                if not LOGIN_ATTEMPTS[ip]:
                    del LOGIN_ATTEMPTS[ip]
        except Exception as e:
            logging.error(f"Cleanup task error: {e}")

        await asyncio.sleep(600)


async def measure_agent_ping():
    """Measure ping: try ICMP first (faster/accurate), fallback to HTTPS if blocked"""
    import subprocess
    import platform
    
    # Try ICMP ping first
    try:
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", "2000", "8.8.8.8"]
            pattern = r"[=<](\d+)\s*ms"
        else:
            cmd = ["ping", "-c", "1", "-W", "2", "8.8.8.8"]
            pattern = r"time=([\d\.]+)\s*ms"
        
        proc = await asyncio.to_thread(
            lambda: subprocess.run(cmd, capture_output=True, timeout=5)
        )
        ping_match = re.search(pattern, proc.stdout.decode())
        if ping_match:
            return str(round(float(ping_match.group(1)), 1))
    except Exception:
        pass
    
    # Fallback to HTTPS ping if ICMP failed/blocked
    targets = [
        "https://www.google.com",
        "https://www.cloudflare.com",
        "https://1.1.1.1"
    ]
    
    timeout = aiohttp.ClientTimeout(total=AGENT_PING_TIMEOUT)
    
    for target in targets:
        try:
            t1 = time.time()
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(target, allow_redirects=False) as resp:
                    await resp.read()
                    if resp.status in (200, 301, 302, 403, 204):
                        result = str(int((time.time() - t1) * 1000))
                        return result
        except Exception:
            continue
    
    return None


async def cleanup_server():
    global AGENT_TASK  # noqa: F824
    if AGENT_TASK and (not AGENT_TASK.done()):
        AGENT_TASK.cancel()
        try:
            await AGENT_TASK
        except asyncio.CancelledError:
            pass


# ===== WAF EXEMPTIONS =====
# Endpoints where WAF body checking is too aggressive (terminal commands, config saves)
WAF_EXEMPT_PATHS = {
    "/api/terminal/ws", "/api/terminal/creds",
    "/api/settings/system", "/api/settings/keyboard",
    "/api/heartbeat", "/api/settings/metadata",
}

# ===== CSRF EXEMPTIONS =====
# Endpoints exempt from CSRF (public auth, node heartbeat)
CSRF_EXEMPT_PATHS = {
    "/api/heartbeat", "/api/login/request", "/api/login/password",
    "/api/auth/telegram", "/api/login/reset", "/api/reset/confirm",
    "/logout",
}


async def start_web_server(bot_instance: Bot):
    global AGENT_FLAG, AGENT_TASK  # noqa: F824
    app = web.Application()
    app["bot"] = bot_instance
    app["shutdown_event"] = asyncio.Event()

    # === Rate Limiting Middleware ===
    @web.middleware
    async def rate_limit_middleware(request, handler):
        if request.path.startswith("/api/") and request.method in ["POST", "PUT", "DELETE"]:
            ip = get_client_ip(request)
            endpoint = request.path
            if not check_api_rate_limit(ip, endpoint):
                logging.warning(f"Rate limit exceeded for IP: {mask_sensitive_data(ip)}")
                return web.json_response(
                    {"error": "Rate limit exceeded. Max 100 requests/minute per IP"},
                    status=429
                )
        return await handler(request)

    # === WAF Middleware (FIXED: request.read() instead of request.text()) ===
    @web.middleware
    async def waf_middleware(request, handler):
        if request.method in ["POST", "PUT"]:
            # Skip WAF for exempt paths (terminal, config, heartbeat)
            if request.path in WAF_EXEMPT_PATHS:
                return await handler(request)

            ip = get_client_ip(request)

            # Check Query String
            if request.query_string:
                qs = request.query_string if isinstance(request.query_string, str) else request.query_string.decode('utf-8', errors='ignore')
                is_attack, attack_type = check_waf_patterns(qs)
                if is_attack:
                    logging.critical(f"WAF: {attack_type} detected in query from IP {mask_sensitive_data(ip)}")
                    return web.json_response({"error": "Malicious request detected"}, status=403)

            # FIXED: Use request.read() which caches internally,
            # so subsequent request.json() calls still work
            try:
                body = await request.read()
                if body:
                    body_text = body.decode('utf-8', errors='ignore')
                    is_attack, attack_type = check_waf_patterns(body_text)
                    if is_attack:
                        logging.critical(f"WAF: {attack_type} detected in body from IP {mask_sensitive_data(ip)}")
                        return web.json_response({"error": "Malicious request detected"}, status=403)

                    if not validate_input_length(body_text, max_length=10000):
                        logging.warning(f"WAF: Request too large from IP {mask_sensitive_data(ip)}")
                        return web.json_response({"error": "Request too large"}, status=413)
            except Exception as e:
                logging.error(f"WAF middleware error: {e}")

        return await handler(request)

    # === CSRF Middleware ===
    @web.middleware
    async def csrf_middleware(request, handler):
        if request.method in ("POST", "PUT", "DELETE"):
            if request.path not in CSRF_EXEMPT_PATHS:
                csrf_token = request.headers.get("X-CSRF-Token")
                if not csrf_token or not verify_csrf_token(csrf_token):
                    return web.json_response({"error": "CSRF token invalid or missing"}, status=403)
        return await handler(request)

    app.middlewares.append(rate_limit_middleware)
    app.middlewares.append(waf_middleware)
    app.middlewares.append(csrf_middleware)

    async def on_shutdown(app):
        app["shutdown_event"].set()

    app.on_shutdown.append(on_shutdown)
    # CSRF token endpoint (for frontend to fetch tokens)
    async def handle_csrf_token(request):
        user = get_current_user(request)
        if not user:
            return web.json_response({"error": "Unauthorized"}, status=401)
        token = generate_csrf_token()
        return web.json_response({"csrf_token": token})

    app.router.add_get("/api/csrf-token", handle_csrf_token)
    app.router.add_post("/api/heartbeat", handle_heartbeat)
    if ENABLE_WEB_UI:
        logging.info("Web UI ENABLED.")
        if os.path.exists(STATIC_DIR):
            app.router.add_static("/static", STATIC_DIR)

        # Добавляем маршрут для манифеста
        async def handle_manifest(request):
            manifest_path = os.path.join(STATIC_DIR, "favicons", "site.webmanifest")
            if os.path.exists(manifest_path):
                return web.FileResponse(manifest_path)
            return web.Response(status=404)

        app.router.add_get("/site.webmanifest", handle_manifest)
        app.router.add_get("/", handle_dashboard)
        app.router.add_get("/terminal", handle_terminal_page)
        app.router.add_get("/api/terminal/ws", handle_terminal_ws)
        app.router.add_get("/api/terminal/creds", handle_get_terminal_creds)
        app.router.add_post("/api/terminal/creds", handle_save_terminal_creds)
        app.router.add_get("/api/terminal/stats", handle_terminal_stats)
        app.router.add_get("/settings", handle_settings_page)
        app.router.add_get("/nodes", handle_nodes_monitor_page)
        app.router.add_get("/login", handle_login_page)
        app.router.add_post("/api/login/request", handle_login_request)
        app.router.add_get("/api/login/magic", handle_magic_login)
        app.router.add_post("/api/login/password", handle_login_password)
        app.router.add_post("/api/login/reset", handle_reset_request)
        app.router.add_get("/reset_password", handle_reset_page_render)
        app.router.add_post("/api/reset/confirm", handle_reset_confirm)
        app.router.add_post("/api/auth/telegram", handle_telegram_auth_route)
        app.router.add_post("/logout", handle_logout)
        app.router.add_get("/api/node/details", handle_node_details)
        app.router.add_get("/api/agent/stats", handle_agent_stats)
        app.router.add_get("/api/nodes/list", handle_nodes_list_json)
        app.router.add_get("/api/nodes/monitor/list", handle_nodes_monitor_list)
        app.router.add_get("/api/nodes/monitor/detail", handle_nodes_monitor_detail)
        app.router.add_get("/api/nodes/monitor/services", handle_nodes_monitor_services)
        app.router.add_post("/api/nodes/monitor/command", handle_nodes_monitor_command)
        app.router.add_post("/api/nodes/monitor/service_action", handle_nodes_monitor_service_action)
        app.router.add_get("/api/logs", handle_get_logs)
        app.router.add_get("/api/logs/system", handle_get_sys_logs)
        app.router.add_post("/api/settings/save", handle_save_notifications)
        app.router.add_post("/api/settings/language", handle_set_language)
        app.router.add_head("/api/settings/language", handle_session_check_head)
        app.router.add_post("/api/settings/system", handle_save_system_config)
        app.router.add_post("/api/settings/password", handle_change_password)
        app.router.add_get("/api/security/telegram_only_mode", handle_get_telegram_only_mode)
        app.router.add_post("/api/security/telegram_only_mode", handle_set_telegram_only_mode)
        app.router.add_post("/api/settings/keyboard", handle_save_keyboard_config)
        app.router.add_post("/api/settings/metadata", handle_save_metadata)
        app.router.add_post("/api/logs/clear", handle_clear_logs)
        app.router.add_get("/api/agent/ipv4", handle_agent_ipv4)
        app.router.add_post("/api/traffic/reset", handle_reset_traffic)
        app.router.add_post("/api/users/action", handle_user_action)
        app.router.add_post("/api/nodes/add", handle_node_add)
        app.router.add_post("/api/nodes/delete", handle_node_delete)
        app.router.add_post("/api/nodes/rename", handle_node_rename)
        app.router.add_get("/api/events", handle_sse_stream)
        app.router.add_get("/api/events/logs", handle_sse_logs)
        app.router.add_get("/api/events/node", handle_sse_node_details)
        app.router.add_get("/api/events/services", handle_sse_services)
        app.router.add_get("/api/update/check", api_check_update)
        app.router.add_post("/api/update/run", api_run_update)
        app.router.add_get("/api/notifications/list", api_get_notifications)
        app.router.add_post("/api/notifications/read", api_read_notifications)
        app.router.add_post("/api/notifications/clear", api_clear_notifications)
        app.router.add_get("/api/sessions/list", api_get_sessions)
        app.router.add_post("/api/sessions/revoke", api_revoke_session)
        app.router.add_post("/api/sessions/revoke_all", api_revoke_all_sessions)
        app.router.add_get("/api/services", handle_services_list)
        app.router.add_get("/api/services/available", api_services_available)
        app.router.add_get("/api/services/info/{name}", api_service_info)
        app.router.add_post("/api/services/manage", api_services_manage)
        app.router.add_post("/api/services/{action}", api_control_service)
    else:
        logging.info("Web UI DISABLED.")
        app.router.add_get("/", handle_api_root)
    AGENT_TASK = asyncio.create_task(agent_monitor())
    asyncio.create_task(cleanup_monitor())
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    try:
        await site.start()
        logging.info(f"Web Server started on {WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        return runner
    except Exception as e:
        logging.error(f"Failed to start Web Server: {e}")
        return None


async def agent_monitor():
    global AGENT_IP_CACHE, AGENT_FLAG, AGENT_PING_CACHE, AGENT_PING_LAST_UPDATE
    import psutil
    import requests

    try:
        AGENT_IP_CACHE = await asyncio.to_thread(
            lambda: requests.get("https://api.ipify.org", timeout=3).text
        )
    except Exception:
        pass
    try:
        AGENT_FLAG = await get_country_flag(AGENT_IP_CACHE)
    except Exception:
        pass
    
    # Measure initial ping
    ping_result = await measure_agent_ping()
    AGENT_PING_CACHE = ping_result if ping_result else "n/a"
    AGENT_PING_LAST_UPDATE = time.time()
    
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            ram_pct = round((mem.total - mem.available) / mem.total * 100, 1) if mem.total > 0 else 0
            net = psutil.net_io_counters()
            point = {
                "t": int(time.time()),
                "c": cpu,
                "r": ram_pct,
                "rx": net.bytes_recv,
                "tx": net.bytes_sent,
            }
            AGENT_HISTORY.append(point)
            if len(AGENT_HISTORY) > 60:
                AGENT_HISTORY.pop(0)
            
            # Update ping interval based on config
            ping_int = getattr(current_config, "PING_INTERVAL", 30)
            if time.time() - AGENT_PING_LAST_UPDATE > ping_int:
                ping_result = await measure_agent_ping()
                AGENT_PING_CACHE = ping_result if ping_result else "n/a"
                AGENT_PING_LAST_UPDATE = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(2)
