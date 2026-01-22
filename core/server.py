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
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from collections import deque
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
    WEB_AUTH_FILE,
    ADMIN_USERNAME,
    TOKEN,
    save_keyboard_config,
    KEYBOARD_CONFIG,
    DEPLOY_MODE,
    TG_BOT_NAME,
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
)
from .auth import save_users, get_user_name
from .keyboards import BTN_CONFIG_MAP
from modules import update as update_module
from modules import traffic as traffic_module
from . import shared_state

COOKIE_NAME = "vps_agent_session"
LOGIN_TOKEN_TTL = 300
RESET_TOKEN_TTL = 600
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "core", "static")
AGENT_FLAG = "🏳️"
AGENT_IP_CACHE = "Loading..."
RESET_TOKENS = {}
SERVER_SESSIONS = {}
LOGIN_ATTEMPTS = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_BLOCK_TIME = 300
BOT_USERNAME_CACHE = None
APP_VERSION = get_app_version()
CACHE_VER = str(int(time.time()))
AGENT_TASK = None
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


def get_client_ip(request):
    ip = request.headers.get("X-Forwarded-For")
    if ip:
        return ip.split(",")[0]
    peer = request.transport.get_extra_info("peername")
    return peer[0] if peer else "unknown"


def check_user_password(user_id, input_pass):
    if user_id not in ALLOWED_USERS:
        return False
    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, str):
        return False
    stored_hash = user_data.get("password_hash")
    if not stored_hash:
        return user_id == ADMIN_USER_ID and input_pass == "admin"
    ph = PasswordHasher()
    try:
        return ph.verify(stored_hash, input_pass)
    except Exception:
        return False
    ph = PasswordHasher()
    try:
        return ph.verify(stored_hash, input_pass)
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


async def handle_get_logs(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Unauthorized"}, status=403)
    log_path = os.path.join(BASE_DIR, "logs", "bot", "bot.log")
    if not os.path.exists(log_path):
        return web.json_response({"logs": ["Logs not found."]})
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = list(deque(f, 300))
        return web.json_response({"logs": lines})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_get_sys_logs(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Unauthorized"}, status=403)
    try:
        cmd = ["journalctl", "-n", "100", "--no-pager"]
        if DEPLOY_MODE == "docker" and current_config.INSTALL_MODE == "root":
            if os.path.exists("/host/usr/bin/journalctl"):
                cmd = [
                    "chroot",
                    "/host",
                    "/usr/bin/journalctl",
                    "-n",
                    "100",
                    "--no-pager",
                ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            logs = stdout.decode("utf-8", errors="ignore").strip().split("\n")
            return web.json_response({"logs": logs})
        else:
            return web.json_response(
                {"error": f"Error reading logs: {stderr.decode()}"}
            )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_get_notifications(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    uid = user["id"]
    lang = get_user_lang(uid)
    user_alerts = ALERTS_CONFIG.get(uid, {})
    
    filtered = []
    for n in list(shared_state.WEB_NOTIFICATIONS):
        if user_alerts.get(n["type"], False):
            n_copy = n.copy()
            if "text_map" in n_copy and isinstance(n_copy["text_map"], dict):
                text_map = n_copy["text_map"]
                localized_text = text_map.get(lang) or text_map.get(DEFAULT_LANGUAGE)
                if localized_text:
                    n_copy["text"] = localized_text
                del n_copy["text_map"]
            filtered.append(n_copy)

    last_read = shared_state.WEB_USER_LAST_READ.get(uid, 0)
    unread_count = sum((1 for n in filtered if n["time"] > last_read))
    return web.json_response({"notifications": filtered, "unread_count": unread_count})


async def api_read_notifications(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    uid = user["id"]
    shared_state.WEB_USER_LAST_READ[uid] = time.time()
    return web.json_response({"status": "ok"})


async def api_clear_notifications(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    shared_state.WEB_NOTIFICATIONS.clear()
    shared_state.WEB_USER_LAST_READ.clear()
    return web.json_response({"status": "ok"})


async def api_check_update(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        info = await update_module.get_update_info()
        if len(info) == 4:
            local_ver, remote_ver, target_branch, update_available = info
        elif len(info) == 3:
            local_ver, remote_ver, target_branch = info
            update_available = target_branch is not None
        else:
            return web.json_response(
                {"error": "Invalid update module response"}, status=500
            )
        return web.json_response(
            {
                "local_version": local_ver,
                "remote_version": remote_ver,
                "target_branch": target_branch,
                "update_available": update_available,
            }
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_run_update(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        branch = data.get("branch")
        if not branch:
            return web.json_response({"error": "No branch specified"}, status=400)
        branch = branch.replace("origin/", "")
        await update_module.execute_bot_update(branch, restart_source="web:admin")
        return web.json_response({"status": "Update started, server restarting..."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_get_sessions(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    current_token = request.cookies.get(COOKIE_NAME)
    user_sessions = []
    expired_tokens = []
    is_main_admin = user["id"] == ADMIN_USER_ID
    for token, session in SERVER_SESSIONS.items():
        if time.time() > session["expires"]:
            expired_tokens.append(token)
            continue
        if is_main_admin or session["id"] == user["id"]:
            is_current = token == current_token
            s_uid = session["id"]
            user_name = USER_NAMES.get(str(s_uid), f"ID: {s_uid}")
            ip_raw = session.get("ip", "Unknown")
            ip_enc = encrypt_for_web(ip_raw)
            user_sessions.append(
                {
                    "token_prefix": token[:6] + "...",
                    "id": token,
                    "ip": ip_enc,
                    "ua": session.get("ua", "Unknown"),
                    "created": session.get("created", 0),
                    "current": is_current,
                    "user_id": s_uid,
                    "user_name": user_name,
                    "is_mine": s_uid == user["id"],
                }
            )
    for t in expired_tokens:
        del SERVER_SESSIONS[t]
    user_sessions.sort(
        key=lambda x: (not x["current"], not x["is_mine"], x["created"]), reverse=True
    )
    return web.json_response({"sessions": user_sessions})


async def api_revoke_session(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        target_token = data.get("token")
        current_token = request.cookies.get(COOKIE_NAME)
        if target_token == current_token:
            return web.json_response(
                {"error": "Cannot revoke current session"}, status=400
            )
        if target_token in SERVER_SESSIONS:
            if (
                user["id"] == ADMIN_USER_ID
                or SERVER_SESSIONS[target_token]["id"] == user["id"]
            ):
                del SERVER_SESSIONS[target_token]
                return web.json_response({"status": "ok"})
        return web.json_response(
            {"error": "Session not found or access denied"}, status=404
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_revoke_all_sessions(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    current_token = request.cookies.get(COOKIE_NAME)
    uid = user["id"]
    count = 0
    for token in list(SERVER_SESSIONS.keys()):
        session = SERVER_SESSIONS[token]
        if session["id"] == uid and token != current_token:
            del SERVER_SESSIONS[token]
            count += 1
    return web.json_response({"status": "ok", "revoked_count": count})


async def handle_dashboard(request):
    user = get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")
    if is_default_password_active(user["id"]):
        token = secrets.token_urlsafe(32)
        RESET_TOKENS[token] = {"ts": time.time(), "user_id": user["id"]}
        raise web.HTTPFound(f"/reset_password?token={token}")
    user_id = user["id"]
    lang = get_user_lang(user_id)
    all_nodes = await nodes_db.get_all_nodes()
    nodes_count = len(all_nodes)
    active_nodes = sum(
        (
            1
            for n in all_nodes.values()
            if time.time() - n.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT
        )
    )
    role = user.get("role", "users")
    is_main_admin = user_id == ADMIN_USER_ID
    is_admin = role == "admins" or is_main_admin
    role_color = "green" if role == "admins" else "gray"
    role_badge_html = f'<span class="ml-2 px-2 py-0.5 rounded text-[10px] border border-{role_color}-500/30 bg-{role_color}-100 dark:bg-{role_color}-500/20 text-{role_color}-600 dark:text-{role_color}-400 uppercase font-bold align-middle">{role}</span>'
    node_action_btn = ""
    settings_btn = ""
    if user_id == ADMIN_USER_ID:
        node_action_btn = f"""<button onclick="openAddNodeModal()" class="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition shadow-lg shadow-blue-500/20"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>{_('web_add_node_section', lang)}</button>"""
        settings_btn = f'<a href="/settings" class="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400" title="{_('web_settings_button', lang)}"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg></a>'
    clean_version = APP_VERSION.lstrip("v")
    display_version = f"v{clean_version}"
    users_json = "null"
    nodes_json = "null"
    if is_admin:
        ulist = [
            {
                "id": uid,
                "name": USER_NAMES.get(str(uid), f"ID: {uid}"),
                "role": (
                    ALLOWED_USERS[uid].get("group", "users")
                    if isinstance(ALLOWED_USERS[uid], dict)
                    else ALLOWED_USERS[uid]
                ),
            }
            for uid in ALLOWED_USERS
            if uid != ADMIN_USER_ID
        ]
        users_json = json.dumps(ulist)
        nlist = [
            {
                "token": encrypt_for_web(t),
                "name": n.get("name", "Unknown"),
                "ip": encrypt_for_web(n.get("ip", "Unknown")),
            }
            for t, n in all_nodes.items()
        ]
        nodes_json = json.dumps(nlist)
    
    can_reset = traffic_module.can_reset_traffic()
    
    context = {
        "web_title": f"{_('web_dashboard_title', lang)} - {TG_BOT_NAME}",
        "web_brand_name": TG_BOT_NAME,
        "web_version": display_version,
        "role_badge": role_badge_html,
        "cache_ver": CACHE_VER,
        "web_dashboard_title": _("web_dashboard_title", lang),
        "user_avatar": _get_avatar_html(user),
        "user_name": user.get("first_name", "User"),
        "nodes_count": str(nodes_count),
        "active_nodes": str(active_nodes),
        "web_agent_stats_title": _("web_agent_stats_title", lang),
        "agent_ip": encrypt_for_web(AGENT_IP_CACHE),
        "web_traffic_total": _("web_traffic_total", lang),
        "web_uptime": _("web_uptime", lang),
        "web_cpu": _("web_cpu", lang),
        "web_ram": _("web_ram", lang),
        "web_disk": _("web_disk", lang),
        "web_rx": _("web_rx", lang),
        "web_tx": _("web_tx", lang),
        "web_download": _("web_download", lang),
        "web_upload": _("web_upload", lang),
        "web_node_mgmt_title": _("web_node_mgmt_title", lang),
        "web_logs_title": _("web_logs_title", lang),
        "web_logs_footer": _("web_logs_footer", lang),
        "web_loading": _("web_loading", lang),
        "web_nodes_loading": _("web_nodes_loading", lang),
        "web_logs_btn_bot": "Логи Бота" if lang == "ru" else "Bot Logs",
        "web_logs_btn_sys": "Логи VPS" if lang == "ru" else "VPS Logs",
        "node_action_btn": node_action_btn,
        "settings_btn": settings_btn,
        "web_footer_powered": _("web_footer_powered", lang),
        "web_hint_cpu_usage": _("web_hint_cpu_usage", lang),
        "web_hint_ram_usage": _("web_hint_ram_usage", lang),
        "web_hint_disk_usage": _("web_hint_disk_usage", lang),
        "web_hint_traffic_in": _("web_hint_traffic_in", lang),
        "web_hint_traffic_out": _("web_hint_traffic_out", lang),
        "web_add_node_section": _("web_add_node_section", lang),
        "web_node_name_placeholder": _("web_node_name_placeholder", lang),
        "web_create_btn": _("web_create_btn", lang),
        "web_node_token": _("web_node_token", lang),
        "web_node_cmd": _("web_node_cmd", lang),
        "web_copied": _("web_copied", lang),
        "web_resources_chart": _("web_resources_chart", lang),
        "web_network_chart": _("web_network_chart", lang),
        "web_token_label": _("web_token_label", lang),
        "web_stats_total": _("web_stats_total", lang),
        "web_stats_active": _("web_stats_active", lang),
        "web_notifications_title": _("web_notifications_title", lang),
        "web_clear_notifications": _("web_clear_notifications", lang),
        "web_node_details_title": _("web_node_details_title", lang),
        "web_clear_logs_btn": _("web_clear_logs_btn", lang),
        "web_logout": _("web_logout", lang),
        "web_access_denied": _("web_access_denied", lang),
        "web_logs_protected_desc": _("web_logs_protected_desc", lang),
        "web_node_last_seen_label": _("web_node_last_seen", lang),
        "web_node_traffic": _("web_node_traffic", lang),
        "web_reset_traffic_btn": _("web_reset_traffic_btn", lang),
        "user_role_js": f"const USER_ROLE = '{role}'; const IS_MAIN_ADMIN = {str(is_main_admin).lower()}; const WEB_KEY = '{get_web_key()}';",
        "is_main_admin": is_main_admin,
        "reset_allowed": can_reset,
        "web_search_placeholder": _("web_search_placeholder", lang),
        "i18n_json": json.dumps(
            {
                "web_cpu": _("web_cpu", lang),
                "web_ram": _("web_ram", lang),
                "web_no_nodes": _("web_no_nodes", lang),
                "web_loading": _("web_loading", lang),
                "web_error": _("web_error", lang, error=""),
                "web_conn_error": _("web_conn_error", lang, error=""),
                "web_log_empty": _("web_log_empty", lang),
                "web_access_denied": _("web_access_denied", lang),
                "web_copied": _("web_copied", lang),
                "web_no_notifications": _("web_no_notifications", lang),
                "web_clear_notifications": _("web_clear_notifications", lang),
                "web_notifications_cleared": _("web_notifications_cleared", lang),
                "modal_title_alert": _("modal_title_alert", lang),
                "modal_title_confirm": _("modal_title_confirm", lang),
                "web_clear_notif_confirm": _("web_clear_notifications", lang) + "?",
                "modal_btn_ok": _("modal_btn_ok", lang),
                "modal_btn_cancel": _("modal_btn_cancel", lang),
                "web_time_d": _("unit_day_short", lang),
                "web_time_h": _("unit_hour_short", lang),
                "web_time_m": _("unit_minute_short", lang),
                "unit_bytes": _("unit_bytes", lang),
                "unit_kb": _("unit_kb", lang),
                "unit_mb": _("unit_mb", lang),
                "unit_gb": _("unit_gb", lang),
                "unit_tb": _("unit_tb", lang),
                "unit_pb": _("unit_pb", lang),
                "web_search_nothing_found": _("web_search_nothing_found", lang),
                "web_node_modal_loading": _("web_node_modal_loading", lang),
                "web_node_status_online": _("web_node_status_online", lang),
                "web_node_last_seen": _("web_node_last_seen", lang),
                "web_node_traffic": _("web_node_traffic", lang),
                "web_label_cpu": _("web_label_cpu", lang),
                "web_label_ram": _("web_label_ram", lang),
                "web_label_disk": _("web_label_disk", lang),
                "web_label_status": _("web_label_status", lang),
                "modal_title_info": _("web_node_details_title", lang),
                "web_click_copy": _("web_click_copy", lang),
                "web_top_cpu": _("web_top_cpu", lang),
                "web_top_ram": _("web_top_ram", lang),
                "web_top_disk": _("web_top_disk", lang),
                "web_hint_traffic_in": _("web_hint_traffic_in", lang),
                "web_hint_traffic_out": _("web_hint_traffic_out", lang),
                "web_log_connecting": _("web_log_connecting", lang),
                "web_status_restart": _("web_status_restart", lang),
                "web_session_expired": _("web_session_expired", lang),
                "web_please_relogin": _("web_please_relogin", lang),
                "web_login_btn": _("web_login_btn", lang),
                "web_weak_conn": _("web_weak_conn", lang),
                "web_conn_problem": _("web_conn_problem", lang),
                "web_refresh_stream": _("web_refresh_stream", lang),
                "web_fatal_conn": _("web_fatal_conn", lang),
                "web_server_rebooting": _("web_server_rebooting", lang),
                "web_reloading_page": _("web_reloading_page", lang),
                "web_node_rename_success": _("web_node_rename_success", lang),
                "web_node_rename_error": _("web_node_rename_error", lang),
                "web_traffic_reset_confirm": _("web_traffic_reset_confirm", lang),
                "traffic_reset_done": _("web_traffic_reset_no_emoji", lang),
            }
        ),
    }
    template = JINJA_ENV.get_template("dashboard.html")
    html = template.render(**context)
    return web.Response(text=html, content_type="text/html")


async def handle_heartbeat(request):
    signature = request.headers.get("X-Signature")
    if not signature:
        return web.json_response({"error": "Signature missing"}, status=401)
    try:
        body_bytes = await request.read()
        data = json.loads(body_bytes)
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    token = data.get("token")
    if not token:
        return web.json_response({"error": "Token missing"}, status=401)
    expected_signature = hmac.new(
        token.encode(), body_bytes, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        safe_ip = str(request.remote).replace("\n", "").replace("\r", "")
        logging.warning(f"Invalid signature from {safe_ip}")
        return web.json_response({"error": "Invalid signature"}, status=403)
    node = await nodes_db.get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Auth fail"}, status=401)
    stats = data.get("stats", {})
    results = data.get("results", [])
    bot = request.app.get("bot")
    if bot and results:
        for res in results:
            asyncio.create_task(
                process_node_result_background(
                    bot,
                    res.get("user_id"),
                    res.get("command"),
                    res.get("result"),
                    token,
                    node.get("name", "Node"),
                )
            )
    if node.get("is_restarting"):
        await nodes_db.update_node_extra(token, "is_restarting", False)
    ip = request.transport.get_extra_info("peername")[0]
    if stats.get("external_ip"):
        ip = stats.get("external_ip")
    else:
        try:
            ip_obj = ipaddress.ip_address(ip)
            if (
                (ip_obj.is_private or ip_obj.is_loopback)
                and AGENT_IP_CACHE
                and (AGENT_IP_CACHE not in ["Loading...", "Unknown"])
            ):
                ip = AGENT_IP_CACHE
        except ValueError:
            pass
    await nodes_db.update_node_heartbeat(token, ip, stats)
    current_node = await nodes_db.get_node_by_token(token)
    tasks_to_send = current_node.get("tasks", [])
    if tasks_to_send:
        await nodes_db.clear_node_tasks(token)
    return web.json_response({"status": "ok", "tasks": tasks_to_send})


async def process_node_result_background(bot, user_id, cmd, text, token, node_name):
    if not user_id or not text:
        return
    try:
        if cmd == "traffic" and user_id in NODE_TRAFFIC_MONITORS:
            monitor = NODE_TRAFFIC_MONITORS[user_id]
            if monitor.get("token") == token:
                msg_id = monitor.get("message_id")
                stop_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⏹ Stop",
                                callback_data=f"node_stop_traffic_{token}",
                            )
                        ]
                    ]
                )
                try:
                    await bot.edit_message_text(
                        text=text,
                        chat_id=user_id,
                        message_id=msg_id,
                        reply_markup=stop_kb,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                return
        await bot.send_message(
            chat_id=user_id,
            text=f"🖥 <b>Ответ от {node_name}:</b>\n\n{text}",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"Background send error: {e}")


async def handle_node_details(request):
    if not get_current_user(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    token = decrypt_for_web(request.query.get("token"))
    if not token:
        return web.json_response({"error": "Token required"}, status=400)
    node = await nodes_db.get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Node not found"}, status=404)
    return web.json_response(
        {
            "name": node.get("name"),
            "ip": encrypt_for_web(node.get("ip")),
            "stats": node.get("stats"),
            "history": node.get("history", []),
            "token": encrypt_for_web(token),
            "last_seen": node.get("last_seen", 0),
            "is_restarting": node.get("is_restarting", False),
        }
    )


async def handle_agent_stats(request):
    if not get_current_user(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    import psutil

    current_stats = {
        "cpu": 0,
        "ram": 0,
        "disk": 0,
        "ip": encrypt_for_web(AGENT_IP_CACHE),
        "net_sent": 0,
        "net_recv": 0,
        "boot_time": 0,
    }
    try:
        net = psutil.net_io_counters()
        # ИСПОЛЬЗУЕМ СКОРРЕКТИРОВАННЫЙ ТРАФИК
        rx_total, tx_total = traffic_module.get_current_traffic_total()
        
        net_if = psutil.net_io_counters(pernic=True)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(get_host_path("/"))
        freq = psutil.cpu_freq()
        proc_cpu = await asyncio.to_thread(_get_top_processes, "cpu")
        proc_ram = await asyncio.to_thread(_get_top_processes, "ram")
        proc_disk = await asyncio.to_thread(_get_top_processes, "disk")
        current_stats.update(
            {
                "net_sent": tx_total, # Используем скорректированное значение
                "net_recv": rx_total, # Используем скорректированное значение
                "boot_time": psutil.boot_time(),
                "ram_total": mem.total,
                "ram_free": mem.available,
                "disk_total": disk.total,
                "disk_free": disk.free,
                "cpu_freq": freq.current if freq else 0,
                "process_cpu": proc_cpu,
                "process_ram": proc_ram,
                "process_disk": proc_disk,
                "interfaces": {k: v._asdict() for k, v in net_if.items()},
            }
        )
    except Exception:
        pass
    if AGENT_HISTORY:
        latest = AGENT_HISTORY[-1]
        current_stats.update({"cpu": latest["c"], "ram": latest["r"]})
        try:
            current_stats["disk"] = psutil.disk_usage(get_host_path("/")).percent
        except Exception:
            pass
    return web.json_response({"stats": current_stats, "history": AGENT_HISTORY})


async def handle_reset_traffic(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        # Сброс к системным значениям (как в selftest), убираем оффсет
        traffic_module.TRAFFIC_OFFSET["rx"] = 0
        traffic_module.TRAFFIC_OFFSET["tx"] = 0
        
        # Удаляем бэкапы
        try:
            import glob
            files = glob.glob(os.path.join(traffic_module.config.TRAFFIC_BACKUP_DIR, "traffic_backup_*.json"))
            for f in files:
                os.remove(f)
        except Exception:
            pass
            
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_node_add(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        name = data.get("name")
        if not name:
            return web.json_response({"error": "Name required"}, status=400)
        token = await nodes_db.create_node(name)
        host = request.headers.get("Host", f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        proto = (
            "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        )
        lang = get_user_lang(user["id"])
        script = "deploy_en.sh" if lang == "en" else "deploy.sh"
        cmd = f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/{script}) --agent={proto}://{host} --token={token}"
        return web.json_response(
            {
                "status": "ok",
                "token": encrypt_for_web(token),
                "command": encrypt_for_web(cmd),
            }
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_node_delete(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        token = decrypt_for_web(data.get("token"))
        if not token:
            return web.json_response({"error": "Token required"}, status=400)
        await nodes_db.delete_node(token)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_node_rename(request):
    user = get_current_user(request)
    if not user or user["id"] != ADMIN_USER_ID:
        return web.json_response({"error": "Only Main Admin required"}, status=403)
    try:
        data = await request.json()
        token = decrypt_for_web(data.get("token"))
        new_name = data.get("name")
        if not token or not new_name:
            return web.json_response({"error": "Token and name required"}, status=400)
        success = await nodes_db.update_node_name(token, new_name.strip())
        if success:
            return web.json_response({"status": "ok"})
        else:
            return web.json_response({"error": "Node not found"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_nodes_list_json(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    all_nodes = await nodes_db.get_all_nodes()
    nodes_data = []
    now = time.time()
    for token, node in all_nodes.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        status = "offline"
        if is_restarting:
            status = "restarting"
        elif now - last_seen < NODE_OFFLINE_TIMEOUT:
            status = "online"
        stats = node.get("stats", {})
        nodes_data.append(
            {
                "token": encrypt_for_web(token),
                "name": node.get("name", "Unknown"),
                "ip": encrypt_for_web(node.get("ip", "Unknown")),
                "status": status,
                "cpu": stats.get("cpu", 0),
                "ram": stats.get("ram", 0),
                "disk": stats.get("disk", 0),
            }
        )
    return web.json_response({"nodes": nodes_data})


async def handle_settings_page(request):
    user = get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")
    user_id = user["id"]
    role = user.get("role", "users")
    is_admin = role == "admins"
    is_main_admin = user_id == ADMIN_USER_ID
    lang = get_user_lang(user_id)
    user_alerts = ALERTS_CONFIG.get(user_id, {})
    users_json = "null"
    nodes_json = "null"
    if is_admin:
        ulist = [
            {
                "id": uid,
                "name": USER_NAMES.get(str(uid), f"ID: {uid}"),
                "role": (
                    ALLOWED_USERS[uid].get("group", "users")
                    if isinstance(ALLOWED_USERS[uid], dict)
                    else ALLOWED_USERS[uid]
                ),
            }
            for uid in ALLOWED_USERS
            if uid != ADMIN_USER_ID
        ]
        users_json = json.dumps(ulist)
        all_nodes = await nodes_db.get_all_nodes()
        nlist = [
            {
                "token": encrypt_for_web(t),
                "name": n.get("name", "Unknown"),
                "ip": encrypt_for_web(n.get("ip", "Unknown")),
            }
            for t, n in all_nodes.items()
        ]
        nodes_json = json.dumps(nlist)
    
    can_reset = True
    
    keyboard_config_json = json.dumps(KEYBOARD_CONFIG)
    
    i18n_data = {
        "web_saving_btn": _("web_saving_btn", lang),
        "web_saved_btn": _("web_saved_btn", lang),
        "web_save_btn": _("web_save_btn", lang),
        "web_change_btn": _("web_change_btn", lang),
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "web_confirm_delete_user": _("web_confirm_delete_user", lang),
        "web_no_users": _("web_no_users", lang),
        "web_clear_logs_confirm": _("web_clear_logs_confirm", lang),
        "web_logs_cleared": _("web_logs_cleared", lang),
        "error_traffic_interval_low": _("error_traffic_interval_low", lang),
        "error_traffic_interval_high": _("error_traffic_interval_high", lang),
        "web_logs_clearing": _("web_logs_clearing", lang),
        "web_logs_cleared_alert": _("web_logs_cleared_alert", lang),
        "web_pass_changed": _("web_pass_changed", lang),
        "web_pass_mismatch": _("web_pass_mismatch", lang),
        "web_clear_bot_confirm": _("web_clear_bot_confirm", lang),
        "web_clear_node_confirm": _("web_clear_node_confirm", lang),
        "web_clear_all_confirm": _("web_clear_all_confirm", lang),
        "web_logs_cleared_bot": _("web_logs_cleared_bot", lang),
        "web_logs_cleared_node": _("web_logs_cleared_node", lang),
        "web_logs_cleared_all": _("web_logs_cleared_all", lang),
        "modal_title_alert": _("modal_title_alert", lang),
        "modal_title_confirm": _("modal_title_confirm", lang),
        "modal_title_prompt": _("modal_title_prompt", lang),
        "modal_btn_ok": _("modal_btn_ok", lang),
        "modal_btn_cancel": _("modal_btn_cancel", lang),
        "web_kb_active": _("web_kb_active", lang),
        "web_kb_all_on_alert": _("web_kb_all_on_alert", lang),
        "web_kb_all_off_alert": _("web_kb_all_off_alert", lang),
        "web_no_nodes": _("web_no_nodes", lang),
        "web_copied": _("web_copied", lang),
        "web_kb_cat_monitoring": _("web_kb_cat_monitoring", lang),
        "web_kb_cat_security": _("web_kb_cat_security", lang),
        "web_kb_cat_management": _("web_kb_cat_management", lang),
        "web_kb_cat_system": _("web_kb_cat_system", lang),
        "web_kb_cat_tools": _("web_kb_cat_tools", lang),
        "web_update_checking": _("web_update_checking", lang),
        "web_update_available_title": _("web_update_available_title", lang),
        "web_update_info": _("web_update_info", lang),
        "web_update_uptodate": _("web_update_uptodate", lang),
        "web_update_started": _("web_update_started", lang),
        "web_update_error": _("web_update_error", lang),
        "web_no_notifications": _("web_no_notifications", lang),
        "web_clear_notifications": _("web_clear_notifications", lang),
        "web_sessions_title": _("web_sessions_title", lang),
        "web_session_current": _("web_session_current", lang),
        "web_session_revoke": _("web_session_revoke", lang),
        "web_logout": _("web_logout", lang),
        "web_ip": _("web_ip", lang),
        "web_device": _("web_device", lang),
        "web_last_active": _("web_last_active", lang),
        "web_sessions_revoked_alert": _("web_sessions_revoked_alert", lang),
        "web_session_current_label": _("web_session_current_label", lang),
        "web_sessions_revoke_all": _("web_sessions_revoke_all", lang),
        "web_update_placeholder": _("web_update_placeholder", lang),
        "web_update_check_btn": _("web_update_check_btn", lang),
        "web_update_do_btn": _("web_update_do_btn", lang),
        "web_notifications_title": _("web_notifications_title", lang),
        "web_fill_field": _("web_fill_field", lang),
        "web_conn_error_short": _("web_conn_error_short", lang),
        "web_error_short": _("web_error_short", lang),
        "web_success": _("web_success", lang),
        "web_no_sessions": _("web_no_sessions", lang),
        "web_error_loading_sessions": _("web_error_loading_sessions", lang),
        "web_kb_enable_all": _("web_kb_enable_all", lang),
        "web_kb_disable_all": _("web_kb_disable_all", lang),
        "web_click_copy": _("web_click_copy", lang),
        "web_server_name_placeholder": _("web_server_name_placeholder", lang),
        "web_session_expired": _("web_session_expired", lang),
        "web_please_relogin": _("web_please_relogin", lang),
        "web_login_btn": _("web_login_btn", lang),
        "web_add_user_prompt": _("web_add_user_prompt", lang),
        "web_weak_conn": _("web_weak_conn", lang),
        "web_conn_problem": _("web_conn_problem", lang),
        "web_refresh_stream": _("web_refresh_stream", lang),
        "web_fatal_conn": _("web_fatal_conn", lang),
        "web_server_rebooting": _("web_server_rebooting", lang),
        "web_reloading_page": _("web_reloading_page", lang),
        "web_node_rename_success": _("web_node_rename_success", lang),
        "web_node_rename_error": _("web_node_rename_error", lang),
        "web_traffic_reset_confirm": _("web_traffic_reset_confirm", lang),
        "web_traffic_reset_no_emoji": _("web_traffic_reset_no_emoji", lang),
    }
    for btn_key, conf_key in BTN_CONFIG_MAP.items():
        i18n_data[f"lbl_{conf_key}"] = _(btn_key, lang)
    context = {
        "web_title": f"{_('web_settings_page_title', lang)} - {TG_BOT_NAME}",
        "web_brand_name": TG_BOT_NAME,
        "user_name": user.get("first_name"),
        "user_avatar": _get_avatar_html(user),
        "users_data_json": users_json,
        "nodes_data_json": nodes_json,
        "keyboard_config_json": keyboard_config_json,
        "val_cpu": str(current_config.CPU_THRESHOLD),
        "val_ram": str(current_config.RAM_THRESHOLD),
        "val_disk": str(current_config.DISK_THRESHOLD),
        "val_traffic": str(current_config.TRAFFIC_INTERVAL),
        "val_timeout": str(current_config.NODE_OFFLINE_TIMEOUT),
        "web_settings_page_title": _("web_settings_page_title", lang),
        "web_back": _("web_back", lang),
        "web_notif_section": _("web_notif_section", lang),
        "notifications_alert_name_res": _("notifications_alert_name_res", lang),
        "notifications_alert_name_logins": _("notifications_alert_name_logins", lang),
        "notifications_alert_name_bans": _("notifications_alert_name_bans", lang),
        "notifications_alert_name_downtime": _(
            "notifications_alert_name_downtime", lang
        ),
        "web_save_btn": _("web_save_btn", lang),
        "web_users_section": _("web_users_section", lang),
        "web_add_user_btn": _("web_add_user_btn", lang),
        "web_user_id": _("web_user_id", lang),
        "web_user_name": _("web_user_name", lang),
        "web_user_role": _("web_user_role", lang),
        "web_user_action": _("web_user_action", lang),
        "web_add_node_section": _("web_add_node_section", lang),
        "web_node_name_placeholder": _("web_node_name_placeholder", lang),
        "web_no_users": _("web_no_users", lang),
        "web_create_btn": _("web_create_btn", lang),
        "web_node_token": _("web_node_token", lang),
        "web_node_cmd": _("web_node_cmd", lang),
        "web_sys_settings_section": _("web_sys_settings_section", lang),
        "web_thresholds_title": _("web_thresholds_title", lang),
        "web_intervals_title": _("web_intervals_title", lang),
        "web_logs_mgmt_title": _("web_logs_mgmt_title", lang),
        "web_cpu_threshold": _("web_cpu_threshold", lang),
        "web_ram_threshold": _("web_ram_threshold", lang),
        "web_disk_threshold": _("web_disk_threshold", lang),
        "web_traffic_interval": _("web_traffic_interval", lang),
        "web_node_timeout": _("web_node_timeout", lang),
        "web_clear_logs_btn": _("web_clear_logs_btn", lang),
        "web_reset_traffic_btn": _("web_reset_traffic_btn", lang),
        "web_security_section": _("web_security_section", lang),
        "web_change_password_title": _("web_change_password_title", lang),
        "web_current_password": _("web_current_password", lang),
        "web_new_password": _("web_new_password", lang),
        "web_confirm_password": _("web_confirm_password", lang),
        "web_change_btn": _("web_change_btn", lang),
        "web_hint_cpu_threshold": _("web_hint_cpu_threshold", lang),
        "web_hint_ram_threshold": _("web_hint_ram_threshold", lang),
        "web_hint_disk_threshold": _("web_hint_disk_threshold", lang),
        "web_hint_traffic_interval": _("web_hint_traffic_interval", lang),
        "web_hint_node_timeout": _("web_hint_node_timeout", lang),
        "web_keyboard_title": _("web_keyboard_title", lang),
        "web_soon_placeholder": _("web_soon_placeholder", lang),
        "web_node_mgmt_title": _("web_node_mgmt_title", lang),
        "web_kb_desc": _("web_kb_desc", lang),
        "web_kb_btn_config": _("web_kb_btn_config", lang),
        "web_kb_enable_all": _("web_kb_enable_all", lang),
        "web_kb_disable_all": _("web_kb_disable_all", lang),
        "web_kb_modal_title": _("web_kb_modal_title", lang),
        "web_kb_done": _("web_kb_done", lang),
        "web_version": APP_VERSION.lstrip("v"),
        "cache_ver": CACHE_VER,
        "web_update_section": _("web_update_section", lang),
        "web_update_placeholder": _("web_update_placeholder", lang),
        "web_update_check_btn": _("web_update_check_btn", lang),
        "web_update_do_btn": _("web_update_do_btn", lang),
        "web_notifications_title": _("web_notifications_title", lang),
        "web_clear_notifications": _("web_clear_notifications", lang),
        "web_notifications_cleared": _("web_notifications_cleared", lang),
        "web_logout": _("web_logout", lang),
        "web_sessions_title": _("web_sessions_title", lang),
        "web_sessions_view_all": _("web_sessions_view_all", lang),
        "web_sessions_revoke_all": _("web_sessions_revoke_all", lang),
        "web_sessions_modal_title": _("web_sessions_modal_title", lang),
        "user_role_js": f"const USER_ROLE = '{role}'; const IS_MAIN_ADMIN = {str(is_main_admin).lower()}; const WEB_KEY = '{get_web_key()}';",
        "is_main_admin": is_main_admin,
        "reset_allowed": can_reset,
        "check_resources": "checked" if user_alerts.get("resources", False) else "",
        "check_logins": "checked" if user_alerts.get("logins", False) else "",
        "check_bans": "checked" if user_alerts.get("bans", False) else "",
        "check_downtime": "checked" if user_alerts.get("downtime", False) else "",
        "i18n_json": json.dumps(i18n_data),
    }
    template = JINJA_ENV.get_template("settings.html")
    html = template.render(**context)
    return web.Response(text=html, content_type="text/html")

async def handle_save_notifications(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Auth required"}, status=401)
    try:
        data = await request.json()
        uid = user["id"]
        if uid not in ALERTS_CONFIG:
            ALERTS_CONFIG[uid] = {}
        for k in ["resources", "logins", "bans", "downtime"]:
            if k in data:
                ALERTS_CONFIG[uid][k] = bool(data[k])
        save_alerts_config()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_save_system_config(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        save_system_config(data)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_save_keyboard_config(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        save_keyboard_config(data)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_change_password(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if user["id"] != ADMIN_USER_ID:
        return web.json_response({"error": "Main Admin only"}, status=403)
    try:
        data = await request.json()
        if not check_user_password(user["id"], data.get("current_password")):
            return web.json_response({"error": "Wrong password"}, status=400)
        new_pass = data.get("new_password")
        if not new_pass or len(new_pass) < 4:
            return web.json_response({"error": "Too short"}, status=400)
        ph = PasswordHasher()
        new_hash = ph.hash(new_pass)
        if isinstance(ALLOWED_USERS[user["id"]], str):
            ALLOWED_USERS[user["id"]] = {
                "group": ALLOWED_USERS[user["id"]],
                "password_hash": new_hash,
            }
        else:
            ALLOWED_USERS[user["id"]]["password_hash"] = new_hash
        save_users()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_clear_logs(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = {}
        try:
            data = await request.json()
        except Exception:
            pass
        target = data.get("type", "all")
        dirs_to_clear = []
        if target == "bot":
            dirs_to_clear = [BOT_LOG_DIR, WATCHDOG_LOG_DIR]
        elif target == "node":
            dirs_to_clear = [NODE_LOG_DIR]
        elif target == "all":
            dirs_to_clear = [BOT_LOG_DIR, WATCHDOG_LOG_DIR, NODE_LOG_DIR]
        else:
            dirs_to_clear = [BOT_LOG_DIR, WATCHDOG_LOG_DIR, NODE_LOG_DIR]
        for d in dirs_to_clear:
            if os.path.exists(d):
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp):
                        with open(fp, "w") as f_obj:
                            f_obj.truncate(0)
        return web.json_response({"status": "ok", "target": target})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_user_action(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        act = data.get("action")
        tid = int(data.get("id", 0))
        if not tid or tid == ADMIN_USER_ID:
            return web.json_response({"error": "Invalid ID"}, status=400)
        if act == "delete":
            if tid in ALLOWED_USERS:
                del ALLOWED_USERS[tid]
                if str(tid) in USER_NAMES:
                    del USER_NAMES[str(tid)]
                if tid in ALERTS_CONFIG:
                    del ALERTS_CONFIG[tid]
                save_users()
                save_alerts_config()
                return web.json_response({"status": "ok"})
        elif act == "add":
            if tid in ALLOWED_USERS:
                return web.json_response({"error": "Exists"}, status=400)
            ALLOWED_USERS[tid] = {
                "group": data.get("role", "users"),
                "password_hash": None,
            }
            bot = request.app.get("bot")
            if bot:
                await get_user_name(bot, tid)
            else:
                USER_NAMES[str(tid)] = f"User {tid}"
            save_users()
            return web.json_response({"status": "ok", "name": USER_NAMES.get(str(tid))})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"error": "Unknown"}, status=400)


async def handle_set_language(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        lang = data.get("lang")
        if lang in ["ru", "en"]:
            set_user_lang(user["id"], lang)
            return web.json_response({"status": "ok"})
        return web.json_response({"error": "Invalid language"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_session_check_head(request):
    if not get_current_user(request):
        return web.Response(status=401)
    return web.Response(status=200)


async def handle_login_page(request):
    if get_current_user(request):
        raise web.HTTPFound("/")
    global BOT_USERNAME_CACHE
    if BOT_USERNAME_CACHE is None:
        try:
            bot = request.app.get("bot")
            if bot:
                me = await bot.get_me()
                BOT_USERNAME_CACHE = me.username
        except Exception as e:
            logging.error(f"Error fetching bot username: {e}")
            BOT_USERNAME_CACHE = ""
    lang_cookie = request.cookies.get("guest_lang", DEFAULT_LANGUAGE)
    lang = lang_cookie if lang_cookie in ["ru", "en"] else DEFAULT_LANGUAGE
    keys = [
        "web_error",
        "web_conn_error",
        "modal_title_alert",
        "modal_title_confirm",
        "modal_title_prompt",
        "modal_btn_ok",
        "modal_btn_cancel",
        "login_cookie_title",
        "login_cookie_text",
        "login_cookie_btn",
        "login_support_title",
        "login_support_desc",
        "login_github_tooltip",
        "login_support_tooltip",
        "web_title",
        "web_current_password",
        "web_login_btn",
        "login_forgot_pass",
        "login_secure_gateway",
        "login_pass_btn",
        "login_back_magic",
        "login_or",
        "login_reset_title",
        "login_reset_desc",
        "login_btn_send_link",
        "login_btn_back",
        "btn_back",
        "login_support_btn_pay",
        "login_link_sent_title",
        "login_link_sent_desc",
        "reset_success_title",
        "reset_success_desc",
        "login_error_user_not_found",
        "web_default_pass_alert",
        "web_brand_name",
        "login_secure_gateway",
    ]
    i18n_all = {}
    for l in ["ru", "en"]:
        d = {k: _(k, l) for k in keys}
        d["web_error"] = _("web_error", l, error="")
        d["web_conn_error"] = _("web_conn_error", l, error="")
        i18n_all[l] = d
    current_data = i18n_all.get(lang, i18n_all["en"])
    injection = (
        f"{json.dumps(current_data)};\n        const I18N_ALL = {json.dumps(i18n_all)}"
    )
    alert = ""
    if is_default_password_active(ADMIN_USER_ID):
        alert = f'<div class="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/50 rounded-xl flex items-start gap-3"><svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-yellow-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg><span class="text-xs text-yellow-200 font-medium" data-i18n="web_default_pass_alert">{_('web_default_pass_alert', lang)}</span></div>'
    context = {
        "web_title": TG_BOT_NAME,
        "default_pass_alert": alert,
        "error_block": "",
        "bot_username": BOT_USERNAME_CACHE or "",
        "web_version": CACHE_VER,
        "current_lang": lang,
        "i18n_json": injection,
    }
    template = JINJA_ENV.get_template("login.html")
    html = template.render(**context)
    return web.Response(text=html, content_type="text/html")


async def handle_login_request(request):
    data = await request.post()
    try:
        uid = int(data.get("user_id", 0))
    except Exception:
        uid = 0
    if uid not in ALLOWED_USERS:
        return web.Response(text="User not found", status=403)
    token = secrets.token_urlsafe(32)
    AUTH_TOKENS[token] = {"user_id": uid, "created_at": time.time()}
    host = request.headers.get("Host", f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
    proto = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
    link = f"{proto}://{host}/api/login/magic?token={token}"
    bot = request.app.get("bot")
    if bot:
        try:
            lang = get_user_lang(uid)
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=_("web_login_btn", lang), url=link)]
                ]
            )
            await bot.send_message(
                uid, _("web_login_header", lang), reply_markup=kb, parse_mode="HTML"
            )
            return web.HTTPFound("/login?sent=true")
        except Exception:
            pass
    return web.Response(text="Bot Error", status=500)


async def handle_login_password(request):
    data = await request.post()
    ip = get_client_ip(request)
    if not check_rate_limit(ip):
        return web.Response(text="Rate limited. Wait 5 mins.", status=429)
    try:
        uid = int(data.get("user_id", 0))
    except Exception:
        return web.Response(text="Invalid ID", status=400)
    if uid != ADMIN_USER_ID:
        return web.Response(text="Password login for Main Admin only.", status=403)
    if check_user_password(uid, data.get("password")):
        st = secrets.token_hex(32)
        SERVER_SESSIONS[st] = {
            "id": uid,
            "expires": time.time() + 604800,
            "ip": get_client_ip(request),
            "ua": request.headers.get("User-Agent", "Unknown Device"),
            "created": time.time(),
        }
        resp = web.HTTPFound("/")
        resp.set_cookie(COOKIE_NAME, st, max_age=604800, httponly=True, samesite="Lax")
        return resp
    add_login_attempt(ip)
    return web.Response(text="Invalid password", status=403)


async def handle_magic_login(request):
    token = request.query.get("token")
    if not token or token not in AUTH_TOKENS:
        return web.Response(text="Link expired", status=403)
    td = AUTH_TOKENS.pop(token)
    if time.time() - td["created_at"] > LOGIN_TOKEN_TTL:
        return web.Response(text="Expired", status=403)
    uid = td["user_id"]
    if uid not in ALLOWED_USERS:
        return web.Response(text="Denied", status=403)
    st = secrets.token_hex(32)
    SERVER_SESSIONS[st] = {
        "id": uid,
        "expires": time.time() + 2592000,
        "ip": get_client_ip(request),
        "ua": request.headers.get("User-Agent", "Unknown Device"),
        "created": time.time(),
    }
    resp = web.HTTPFound("/")
    resp.set_cookie(COOKIE_NAME, st, max_age=2592000, httponly=True, samesite="Lax")
    return resp


async def handle_telegram_auth(request):
    try:
        data = await request.json()
        if not check_telegram_auth(data, TOKEN):
            return web.json_response({"error": "Invalid hash or expired"}, status=403)
        uid = int(data.get("id"))
        if uid not in ALLOWED_USERS:
            return web.json_response({"error": "User not allowed"}, status=403)
        st = secrets.token_hex(32)
        SERVER_SESSIONS[st] = {
            "id": uid,
            "expires": time.time() + 2592000,
            "ip": get_client_ip(request),
            "ua": request.headers.get("User-Agent", "Unknown Device"),
            "created": time.time(),
            "photo_url": data.get("photo_url"),
        }
        resp = web.json_response({"status": "ok"})
        resp.set_cookie(COOKIE_NAME, st, max_age=2592000, httponly=True, samesite="Lax")
        return resp
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_logout(request):
    token = request.cookies.get(COOKIE_NAME)
    if token and token in SERVER_SESSIONS:
        del SERVER_SESSIONS[token]
    resp = web.HTTPFound("/login")
    resp.del_cookie(COOKIE_NAME)
    return resp


async def handle_reset_request(request):
    try:
        data = await request.json()
        try:
            uid = int(data.get("user_id", 0))
        except Exception:
            uid = 0
        if uid != ADMIN_USER_ID:
            adm = (
                f"https://t.me/{ADMIN_USERNAME}"
                if ADMIN_USERNAME
                else f"tg://user?id={ADMIN_USER_ID}"
            )
            return web.json_response(
                {"error": "not_found", "admin_url": adm}, status=404
            )
        token = secrets.token_urlsafe(32)
        RESET_TOKENS[token] = {"ts": time.time(), "user_id": uid}
        host = request.headers.get("Host", f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        proto = (
            "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        )
        link = f"{proto}://{host}/reset_password?token={token}"
        bot = request.app.get("bot")
        if bot:
            try:
                lang = get_user_lang(uid)
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=_("web_reset_btn", lang), url=link)]
                    ]
                )
                await bot.send_message(
                    uid, _("web_reset_header", lang), reply_markup=kb, parse_mode="HTML"
                )
                return web.json_response({"status": "ok"})
            except Exception:
                return web.json_response({"error": "bot_send_error"}, status=500)
        return web.json_response({"error": "bot_not_ready"}, status=500)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_reset_page_render(request):
    token = request.query.get("token")
    if not token or token not in RESET_TOKENS:
        return web.Response(text="Expired", status=403)
    if time.time() - RESET_TOKENS[token]["ts"] > RESET_TOKEN_TTL:
        del RESET_TOKENS[token]
        return web.Response(text="Expired", status=403)
    lang = DEFAULT_LANGUAGE
    i18n_data = {
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "modal_title_alert": _("modal_title_alert", lang),
        "modal_title_confirm": _("modal_title_confirm", lang),
        "modal_title_prompt": _("modal_title_prompt", lang),
        "modal_btn_ok": _("modal_btn_ok", lang),
        "modal_btn_cancel": _("modal_btn_cancel", lang),
        "web_brand_name": _("web_brand_name", lang),
        "reset_page_title": _("login_reset_title", lang),
        "web_new_password": _("web_new_password", lang),
        "web_confirm_password": _("web_confirm_password", lang),
        "web_save_btn": _("web_save_btn", lang),
        "pass_strength_weak": _("pass_strength_weak", lang),
        "pass_strength_fair": _("pass_strength_fair", lang),
        "pass_strength_good": _("pass_strength_good", lang),
        "pass_strength_strong": _("pass_strength_strong", lang),
        "pass_hint_title": _("pass_hint_title", lang),
        "pass_req_length": _("pass_req_length", lang),
        "pass_req_num": _("pass_req_num", lang),
        "pass_match_error": _("pass_match_error", lang),
        "pass_is_empty": _("pass_is_empty", lang),
        "web_redirecting": _("web_redirecting", lang),
        "web_logging_in": _("web_logging_in", lang),
    }
    context = {
        "web_title": f"Reset Password - {TG_BOT_NAME}",
        "web_version": CACHE_VER,
        "token": token,
        "i18n_json": json.dumps(i18n_data),
    }
    template = JINJA_ENV.get_template("reset_password.html")
    html = template.render(**context)
    return web.Response(text=html, content_type="text/html")


async def handle_reset_confirm(request):
    try:
        data = await request.json()
        token = data.get("token")
        new_pass = data.get("password")
        if not token or token not in RESET_TOKENS:
            return web.json_response({"error": "Expired"}, status=403)
        uid = RESET_TOKENS[token]["user_id"]
        if uid != ADMIN_USER_ID:
            del RESET_TOKENS[token]
            return web.json_response({"error": "Denied"}, status=403)
        if not new_pass or len(new_pass) < 4:
            return web.json_response({"error": "Short pass"}, status=400)
        ph = PasswordHasher()
        new_hash = ph.hash(new_pass)
        if isinstance(ALLOWED_USERS[uid], str):
            ALLOWED_USERS[uid] = {
                "group": ALLOWED_USERS[uid],
                "password_hash": new_hash,
            }
        else:
            ALLOWED_USERS[uid]["password_hash"] = new_hash
        save_users()
        del RESET_TOKENS[token]
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_root(request):
    return web.Response(text="VPS Bot API")


async def handle_sse_stream(request):
    user = get_current_user(request)
    if not user:
        return web.Response(status=401)
    current_token = request.cookies.get(COOKIE_NAME)
    resp = web.StreamResponse(status=200, reason="OK")
    resp.headers["Content-Type"] = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Connection"] = "keep-alive"
    await resp.prepare(request)
    shutdown_event = request.app.get("shutdown_event")
    import psutil

    uid = user["id"]
    try:
        while True:
            if shared_state.IS_RESTARTING:
                try:
                    await resp.write(b"event: shutdown\ndata: restarting\n\n")
                except Exception:
                    pass
                break
            try:
                if request.transport is None or request.transport.is_closing():
                    break
            except Exception:
                break
            if current_token and current_token not in SERVER_SESSIONS:
                try:
                    await resp.write(b"event: session_status\ndata: expired\n\n")
                except Exception:
                    pass
                break
            current_stats = {
                "cpu": 0,
                "ram": 0,
                "disk": 0,
                "ip": encrypt_for_web(AGENT_IP_CACHE),
                "net_sent": 0,
                "net_recv": 0,
                "boot_time": 0,
            }
            try:
                net = psutil.net_io_counters()
                # ИСПОЛЬЗУЕМ СКОРРЕКТИРОВАННЫЙ ТРАФИК И ТУТ
                rx_total, tx_total = traffic_module.get_current_traffic_total()
                
                net_if = psutil.net_io_counters(pernic=True)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage(get_host_path("/"))
                freq = psutil.cpu_freq()
                proc_cpu = await asyncio.to_thread(_get_top_processes, "cpu")
                proc_ram = await asyncio.to_thread(_get_top_processes, "ram")
                proc_disk = await asyncio.to_thread(_get_top_processes, "disk")
                current_stats.update(
                    {
                        "net_sent": tx_total, # Используем скорректированное значение
                        "net_recv": rx_total, # Используем скорректированное значение
                        "boot_time": psutil.boot_time(),
                        "ram_total": mem.total,
                        "ram_free": mem.available,
                        "disk_total": disk.total,
                        "disk_free": disk.free,
                        "cpu_freq": freq.current if freq else 0,
                        "process_cpu": proc_cpu,
                        "process_ram": proc_ram,
                        "process_disk": proc_disk,
                        "interfaces": {k: v._asdict() for k, v in net_if.items()},
                    }
                )
            except Exception:
                pass
            if AGENT_HISTORY:
                latest = AGENT_HISTORY[-1]
                current_stats.update({"cpu": latest["c"], "ram": latest["r"]})
                try:
                    current_stats["disk"] = psutil.disk_usage(
                        get_host_path("/")
                    ).percent
                except Exception:
                    pass
            payload_stats = {"stats": current_stats, "history": AGENT_HISTORY}
            try:
                await resp.write(
                    f"event: agent_stats\ndata: {json.dumps(payload_stats)}\n\n".encode(
                        "utf-8"
                    )
                )
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                break
            all_nodes = await nodes_db.get_all_nodes()
            nodes_data = []
            now = time.time()
            for token, node in all_nodes.items():
                last_seen = node.get("last_seen", 0)
                is_restarting = node.get("is_restarting", False)
                status = "offline"
                if is_restarting:
                    status = "restarting"
                elif now - last_seen < NODE_OFFLINE_TIMEOUT:
                    status = "online"
                stats = node.get("stats", {})
                nodes_data.append(
                    {
                        "token": encrypt_for_web(token),
                        "name": node.get("name", "Unknown"),
                        "ip": encrypt_for_web(node.get("ip", "Unknown")),
                        "status": status,
                        "cpu": stats.get("cpu", 0),
                        "ram": stats.get("ram", 0),
                        "disk": stats.get("disk", 0),
                    }
                )
            try:
                await resp.write(
                    f"event: nodes_list\ndata: {json.dumps({'nodes': nodes_data})}\n\n".encode(
                        "utf-8"
                    )
                )
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                break
            user_alerts = ALERTS_CONFIG.get(uid, {})
            user_lang = get_user_lang(uid)
            
            filtered = []
            for n in list(shared_state.WEB_NOTIFICATIONS):
                if user_alerts.get(n["type"], False):
                    n_copy = n.copy()
                    if "text_map" in n_copy and isinstance(n_copy["text_map"], dict):
                        text_map = n_copy["text_map"]
                        localized_text = text_map.get(user_lang) or text_map.get(DEFAULT_LANGUAGE)
                        if localized_text:
                            n_copy["text"] = localized_text
                        del n_copy["text_map"]
                    filtered.append(n_copy)

            last_read = shared_state.WEB_USER_LAST_READ.get(uid, 0)
            unread_count = sum((1 for n in filtered if n["time"] > last_read))
            notif_payload = {"notifications": filtered, "unread_count": unread_count}
            try:
                await resp.write(
                    f"event: notifications\ndata: {json.dumps(notif_payload)}\n\n".encode(
                        "utf-8"
                    )
                )
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                break
            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=3.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        if "closing transport" not in str(e) and "'NoneType' object" not in str(e):
            logging.error(f"SSE Stream Error: {e}")
    return resp


async def handle_sse_logs(request):
    user = get_current_user(request)
    if not user or user["role"] != "admins":
        return web.Response(status=403)
    log_type = request.query.get("type", "bot")
    resp = web.StreamResponse(status=200, reason="OK")
    resp.headers["Content-Type"] = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Connection"] = "keep-alive"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.enable_compression(False)
    await resp.prepare(request)
    shutdown_event = request.app.get("shutdown_event")
    journal_bin = ["journalctl"]
    if DEPLOY_MODE == "docker" and current_config.INSTALL_MODE == "root":
        if os.path.exists("/host/usr/bin/journalctl"):
            journal_bin = ["chroot", "/host", "/usr/bin/journalctl"]
        elif os.path.exists("/host/bin/journalctl"):
            journal_bin = ["chroot", "/host", "/bin/journalctl"]

    async def fetch_sys_logs(cursor=None, lines=None):
        cmd = journal_bin + ["--no-pager", "--show-cursor"]
        if cursor:
            cmd.extend(["--after-cursor", cursor])
        elif lines:
            cmd.extend(["-n", str(lines)])
        else:
            cmd.extend(["-n", "300"])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return ([f"Error: {stderr.decode('utf-8', errors='ignore')}"], cursor)
            raw_output = stdout.decode("utf-8", errors="ignore").strip().split("\n")
            log_lines = []
            new_cursor = cursor
            for line in raw_output:
                if line.startswith("__CURSOR="):
                    new_cursor = line.split("=", 1)[1]
                elif line:
                    log_lines.append(line)
            return (log_lines, new_cursor)
        except Exception as e:
            return ([f"Error executing journalctl: {str(e)}"], cursor)

    bot_log_path = os.path.join(BASE_DIR, "logs", "bot", "bot.log")
    last_pos = 0
    sys_cursor = None
    last_sent_lines_hash = None
    last_activity = time.time()
    KEEPALIVE_INTERVAL = 25
    if log_type == "bot":
        clean_lines = []
        if os.path.exists(bot_log_path):
            try:

                def read_history():
                    with open(
                        bot_log_path, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        lines = list(deque(f, 300))
                        f.seek(0, 2)
                        return (lines, f.tell())

                history_lines, last_pos = await asyncio.to_thread(read_history)
                if history_lines:
                    clean_lines = [l.rstrip() for l in history_lines]
            except Exception as e:
                logging.error(f"Error reading bot history: {e}")
        await resp.write(
            f"event: logs\ndata: {json.dumps({'logs': clean_lines})}\n\n".encode(
                "utf-8"
            )
        )
        await resp.drain()
        last_activity = time.time()
    elif log_type == "sys":
        history_lines = []
        sys_cursor = None
        try:
            history_lines, sys_cursor = await fetch_sys_logs(lines=300)
        except Exception as e:
            logging.error(f"Error fetching sys logs: {e}")
        logs_to_send = history_lines if history_lines else []
        await resp.write(
            f"event: logs\ndata: {json.dumps({'logs': logs_to_send})}\n\n".encode(
                "utf-8"
            )
        )
        await resp.drain()
        last_activity = time.time()
    try:
        while True:
            if shared_state.IS_RESTARTING:
                await resp.write(b"event: shutdown\ndata: restarting\n\n")
                await resp.drain()
                break
            if request.transport is None or request.transport.is_closing():
                break
            data_sent = False
            if log_type == "bot":
                if os.path.exists(bot_log_path):

                    def read_updates(cursor):
                        new_data = []
                        new_cursor = cursor
                        try:
                            current_size = os.path.getsize(bot_log_path)
                            if current_size < cursor:
                                cursor = 0
                            if current_size > cursor:
                                with open(
                                    bot_log_path, "r", encoding="utf-8", errors="ignore"
                                ) as f:
                                    f.seek(cursor)
                                    new_data = f.readlines()
                                    new_cursor = f.tell()
                        except Exception:
                            pass
                        return (new_data, new_cursor)

                    new_lines, last_pos = await asyncio.to_thread(
                        read_updates, last_pos
                    )
                    if new_lines:
                        clean_lines = [l.rstrip() for l in new_lines]
                        await resp.write(
                            f"event: logs\ndata: {json.dumps({'logs': clean_lines})}\n\n".encode(
                                "utf-8"
                            )
                        )
                        await resp.drain()
                        data_sent = True
            elif log_type == "sys":
                new_lines = []
                try:
                    if sys_cursor:
                        new_lines, sys_cursor = await fetch_sys_logs(cursor=sys_cursor)
                    else:
                        new_lines, sys_cursor = await fetch_sys_logs(lines=10)
                except Exception as e:
                    logging.error(f"Error streaming sys logs: {e}")
                if not sys_cursor and new_lines:
                    current_hash = hash(tuple(new_lines))
                    if current_hash == last_sent_lines_hash:
                        new_lines = []
                    else:
                        last_sent_lines_hash = current_hash
                if new_lines:
                    await resp.write(
                        f"event: logs\ndata: {json.dumps({'logs': new_lines})}\n\n".encode(
                            "utf-8"
                        )
                    )
                    await resp.drain()
                    data_sent = True
            if data_sent:
                last_activity = time.time()
            elif time.time() - last_activity > KEEPALIVE_INTERVAL:
                try:
                    await resp.write(b": keepalive\n\n")
                    await resp.drain()
                    last_activity = time.time()
                except Exception:
                    break
            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        if "closing transport" not in str(e) and "'NoneType' object" not in str(e):
            logging.error(f"SSE Logs Error: {e}")
            try:
                safe_msg = json.dumps({"error": "Internal Server Error"})
                await resp.write(f"event: error\ndata: {safe_msg}\n\n".encode("utf-8"))
            except Exception:
                pass
    return resp


async def handle_sse_node_details(request):
    user = get_current_user(request)
    if not user:
        return web.Response(status=401)
    token = decrypt_for_web(request.query.get("token"))
    if not token:
        return web.Response(status=400)
    resp = web.StreamResponse(status=200, reason="OK")
    resp.headers["Content-Type"] = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Connection"] = "keep-alive"
    await resp.prepare(request)
    shutdown_event = request.app.get("shutdown_event")
    try:
        while True:
            if shared_state.IS_RESTARTING:
                try:
                    await resp.write(b"event: shutdown\ndata: restarting\n\n")
                except Exception:
                    pass
                break
            try:
                if request.transport is None or request.transport.is_closing():
                    break
            except Exception:
                break
            node = await nodes_db.get_node_by_token(token)
            if node:
                payload = {
                    "name": node.get("name"),
                    "ip": encrypt_for_web(node.get("ip")),
                    "stats": node.get("stats"),
                    "history": node.get("history", []),
                    "token": encrypt_for_web(token),
                    "last_seen": node.get("last_seen", 0),
                    "is_restarting": node.get("is_restarting", False),
                }
                try:
                    await resp.write(
                        f"event: node_details\ndata: {json.dumps(payload)}\n\n".encode(
                            "utf-8"
                        )
                    )
                except (ConnectionResetError, BrokenPipeError, ConnectionError):
                    break
            else:
                try:
                    await resp.write(
                        f"event: error\ndata: {json.dumps({'error': 'Node not found'})}\n\n".encode(
                            "utf-8"
                        )
                    )
                except (ConnectionResetError, BrokenPipeError, ConnectionError):
                    pass
                break
            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=3.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        if "closing transport" not in str(e) and "'NoneType' object" not in str(e):
            logging.error(f"SSE Node Details Error: {e}")
    return resp


async def cleanup_server():
    global AGENT_TASK
    if AGENT_TASK and (not AGENT_TASK.done()):
        AGENT_TASK.cancel()
        try:
            await AGENT_TASK
        except asyncio.CancelledError:
            pass


async def start_web_server(bot_instance: Bot):
    global AGENT_FLAG, AGENT_TASK
    app = web.Application()
    app["bot"] = bot_instance
    app["shutdown_event"] = asyncio.Event()

    async def on_shutdown(app):
        app["shutdown_event"].set()

    app.on_shutdown.append(on_shutdown)
    app.router.add_post("/api/heartbeat", handle_heartbeat)
    if ENABLE_WEB_UI:
        logging.info("Web UI ENABLED.")
        if os.path.exists(STATIC_DIR):
            app.router.add_static("/static", STATIC_DIR)
        app.router.add_get("/", handle_dashboard)
        app.router.add_get("/settings", handle_settings_page)
        app.router.add_get("/login", handle_login_page)
        app.router.add_post("/api/login/request", handle_login_request)
        app.router.add_get("/api/login/magic", handle_magic_login)
        app.router.add_post("/api/login/password", handle_login_password)
        app.router.add_post("/api/login/reset", handle_reset_request)
        app.router.add_get("/reset_password", handle_reset_page_render)
        app.router.add_post("/api/reset/confirm", handle_reset_confirm)
        app.router.add_post("/api/auth/telegram", handle_telegram_auth)
        app.router.add_post("/logout", handle_logout)
        app.router.add_get("/api/node/details", handle_node_details)
        app.router.add_get("/api/agent/stats", handle_agent_stats)
        app.router.add_get("/api/nodes/list", handle_nodes_list_json)
        app.router.add_get("/api/logs", handle_get_logs)
        app.router.add_get("/api/logs/system", handle_get_sys_logs)
        app.router.add_post("/api/settings/save", handle_save_notifications)
        app.router.add_post("/api/settings/language", handle_set_language)
        app.router.add_head("/api/settings/language", handle_session_check_head)
        app.router.add_post("/api/settings/system", handle_save_system_config)
        app.router.add_post("/api/settings/password", handle_change_password)
        app.router.add_post("/api/settings/keyboard", handle_save_keyboard_config)
        app.router.add_post("/api/logs/clear", handle_clear_logs)
        # НОВЫЙ ЭНДПОИНТ ДЛЯ СБРОСА ТРАФИКА
        app.router.add_post("/api/traffic/reset", handle_reset_traffic)
        app.router.add_post("/api/users/action", handle_user_action)
        app.router.add_post("/api/nodes/add", handle_node_add)
        app.router.add_post("/api/nodes/delete", handle_node_delete)
        app.router.add_post("/api/nodes/rename", handle_node_rename)
        app.router.add_get("/api/events", handle_sse_stream)
        app.router.add_get("/api/events/logs", handle_sse_logs)
        app.router.add_get("/api/events/node", handle_sse_node_details)
        app.router.add_get("/api/update/check", api_check_update)
        app.router.add_post("/api/update/run", api_run_update)
        app.router.add_get("/api/notifications/list", api_get_notifications)
        app.router.add_post("/api/notifications/read", api_read_notifications)
        app.router.add_post("/api/notifications/clear", api_clear_notifications)
        app.router.add_get("/api/sessions/list", api_get_sessions)
        app.router.add_post("/api/sessions/revoke", api_revoke_session)
        app.router.add_post("/api/sessions/revoke_all", api_revoke_all_sessions)
    else:
        logging.info("Web UI DISABLED.")
        app.router.add_get("/", handle_api_root)
    AGENT_TASK = asyncio.create_task(agent_monitor())
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
    global AGENT_IP_CACHE, AGENT_FLAG
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
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            net = psutil.net_io_counters()
            point = {
                "t": int(time.time()),
                "c": cpu,
                "r": ram,
                "rx": net.bytes_recv,
                "tx": net.bytes_sent,
            }
            AGENT_HISTORY.append(point)
            if len(AGENT_HISTORY) > 60:
                AGENT_HISTORY.pop(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(2)