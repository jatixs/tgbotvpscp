import logging
import time
import os
import json
import secrets
import asyncio
import hashlib
import subprocess
import ipaddress
from argon2 import PasswordHasher, exceptions as argon2_exceptions
import hmac
import requests
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from collections import deque

from . import nodes_db
from .config import (
    WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR,
    ADMIN_USER_ID, ENABLE_WEB_UI, save_system_config, BOT_LOG_DIR,
    WATCHDOG_LOG_DIR, NODE_LOG_DIR, WEB_AUTH_FILE, ADMIN_USERNAME, TOKEN,
    save_keyboard_config, KEYBOARD_CONFIG, DEPLOY_MODE
)
from . import config as current_config
from .shared_state import NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES, AUTH_TOKENS, ALERTS_CONFIG, AGENT_HISTORY, WEB_NOTIFICATIONS
from .i18n import STRINGS, get_user_lang, set_user_lang, get_text as _
from .config import DEFAULT_LANGUAGE
from .utils import get_country_flag, save_alerts_config, get_host_path, get_app_version
from .auth import save_users, get_user_name
from .keyboards import BTN_CONFIG_MAP
from modules import update as update_module
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
    ip = request.headers.get('X-Forwarded-For')
    if ip: return ip.split(',')[0]
    peer = request.transport.get_extra_info('peername')
    return peer[0] if peer else "unknown"

def check_user_password(user_id, input_pass):
    if user_id not in ALLOWED_USERS: return False
    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, str): return False
    stored_hash = user_data.get("password_hash")
    if not stored_hash: return user_id == ADMIN_USER_ID and input_pass == "admin"
    ph = PasswordHasher()
    try:
        return ph.verify(stored_hash, input_pass)
    except Exception:
        return False

def is_default_password_active(user_id):
    if user_id != ADMIN_USER_ID: return False
    if user_id not in ALLOWED_USERS: return False
    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, dict):
        p_hash = user_data.get("password_hash")
        return p_hash is None or p_hash == ""
    return True

def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f: return f.read()
    except FileNotFoundError: return "<h1>Template not found</h1>"

def get_current_user(request):
    token = request.cookies.get(COOKIE_NAME)
    if not token or token not in SERVER_SESSIONS: return None
    session = SERVER_SESSIONS[token]
    if time.time() > session['expires']:
        del SERVER_SESSIONS[token]
        return None
    uid = session['id']
    if uid not in ALLOWED_USERS: return None
    u_data = ALLOWED_USERS[uid]
    role = u_data.get("group", "users") if isinstance(u_data, dict) else u_data
    return {"id": uid, "role": role, "first_name": USER_NAMES.get(str(uid), f"ID: {uid}"), "photo_url": AGENT_FLAG}

def _get_avatar_html(user):
    raw = user.get('photo_url', '')
    if raw.startswith('http'): return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'

def check_telegram_auth(data, bot_token):
    auth_data = data.copy()
    check_hash = auth_data.pop('hash', '')
    if not check_hash: return False
    data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted(auth_data.items())])
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hash_calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if hash_calc != check_hash: return False
    if time.time() - int(auth_data.get('auth_date', 0)) > 86400: return False
    return True

async def handle_get_logs(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Unauthorized"}, status=403)
    log_path = os.path.join(BASE_DIR, "logs", "bot", "bot.log")
    if not os.path.exists(log_path): return web.json_response({"logs": []})
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = list(deque(f, 300))
        return web.json_response({"logs": lines})
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_get_sys_logs(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': 
        return web.json_response({"error": "Unauthorized"}, status=403)
    try:
        cmd = ["journalctl", "-n", "100", "--no-pager"]
        if DEPLOY_MODE == "docker" and current_config.INSTALL_MODE == "root":
             if os.path.exists("/host/usr/bin/journalctl"):
                cmd = ["chroot", "/host", "/usr/bin/journalctl", "-n", "100", "--no-pager"]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            logs = stdout.decode('utf-8', errors='ignore').strip().split('\n')
            return web.json_response({"logs": logs})
        else:
            return web.json_response({"error": f"Error reading logs: {stderr.decode()}"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_get_notifications(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    uid = user['id']
    user_alerts = ALERTS_CONFIG.get(uid, {})
    filtered = [n for n in list(shared_state.WEB_NOTIFICATIONS) if user_alerts.get(n['type'], False)]
    last_read = shared_state.WEB_USER_LAST_READ.get(uid, 0)
    unread_count = sum(1 for n in filtered if n['time'] > last_read)
    return web.json_response({"notifications": filtered, "unread_count": unread_count})

async def api_read_notifications(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    shared_state.WEB_USER_LAST_READ[user['id']] = time.time()
    return web.json_response({"status": "ok"})

async def api_clear_notifications(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    shared_state.WEB_NOTIFICATIONS.clear()
    shared_state.WEB_USER_LAST_READ.clear()
    return web.json_response({"status": "ok"})

async def api_check_update(request):
    user = get_current_user(request)
    if not user: return web.json_response({'error': 'Unauthorized'}, status=401)
    try:
        l, r, b = await update_module.get_update_info()
        return web.json_response({'local_version': l, 'remote_version': r, 'target_branch': b, 'update_available': (b is not None)})
    except Exception as e: return web.json_response({'error': str(e)}, status=500)

async def api_run_update(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({'error': 'Unauthorized'}, status=401)
    try:
        data = await request.json()
        branch = data.get('branch', 'main').replace('origin/', '')
        await update_module.execute_bot_update(branch, restart_source="web:admin")
        return web.json_response({'status': 'Update started'})
    except Exception as e: return web.json_response({'error': str(e)}, status=500)

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    html = load_template("dashboard.html")
    uid, lang = user['id'], get_user_lang(user['id'])
    all_n = await nodes_db.get_all_nodes()
    
    role_color = "green" if user['role'] == "admins" else "gray"
    role_badge = f'<span class="ml-2 px-1.5 py-0.5 rounded text-[10px] border border-{role_color}-500/30 bg-{role_color}-100 dark:bg-{role_color}-500/20 text-{role_color}-600 dark:text-{role_color}-400 uppercase font-bold align-middle">{user["role"]}</span>'

    node_action_btn = ""
    settings_btn = ""
    if uid == ADMIN_USER_ID:
        node_action_btn = f"""<button onclick="openAddNodeModal()" class="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition shadow-lg shadow-blue-500/20"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>{_("web_add_node_section", lang)}</button>"""
        settings_btn = f"""<a href="/settings" class="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400" title="{_("web_settings_button", lang)}"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg></a>"""

    replacements = {
        "{web_title}": f"{_('web_dashboard_title', lang)} - VPS Bot",
        "{web_version}": APP_VERSION.lstrip('v'), "{cache_ver}": CACHE_VER,
        "{web_dashboard_title}": _("web_dashboard_title", lang),
        "{role_badge}": role_badge, "{user_avatar}": _get_avatar_html(user),
        "{user_name}": user['first_name'], "{nodes_count}": str(len(all_n)),
        "{active_nodes}": str(sum(1 for n in all_n.values() if time.time() - n.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT)),
        "{web_agent_stats_title}": _("web_agent_stats_title", lang), "{agent_ip}": AGENT_IP_CACHE,
        "{web_traffic_total}": _("web_traffic_total", lang), "{web_uptime}": _("web_uptime", lang),
        "{web_cpu}": _("web_cpu", lang), "{web_ram}": _("web_ram", lang), "{web_disk}": _("web_disk", lang),
        "{web_rx}": _("web_rx", lang), "{web_tx}": _("web_tx", lang),
        "{web_node_mgmt_title}": _("web_node_mgmt_title", lang), "{web_logs_title}": _("web_logs_title", lang),
        "{web_logs_footer}": _("web_logs_footer", lang), "{web_loading}": _("web_loading", lang),
        "{web_nodes_loading}": _("web_nodes_loading", lang),
        "{web_logs_btn_bot}": "Логи Бота" if lang == 'ru' else "Bot Logs",
        "{web_logs_btn_sys}": "Логи VPS" if lang == 'ru' else "VPS Logs",
        "{node_action_btn}": node_action_btn, "{settings_btn}": settings_btn,
        "{web_footer_powered}": _("web_footer_powered", lang), "{web_add_node_section}": _("web_add_node_section", lang),
        "{web_node_name_placeholder}": _("web_node_name_placeholder", lang), "{web_create_btn}": _("web_create_btn", lang),
        "{web_node_token}": _("web_node_token", lang), "{web_node_cmd}": _("web_node_cmd", lang),
        "{web_resources_chart}": _("web_resources_chart", lang), "{web_network_chart}": _("web_network_chart", lang),
        "{web_token_label}": _("web_token_label", lang), "{web_stats_total}": _("web_stats_total", lang),
        "{web_stats_active}": _("web_stats_active", lang), "{web_notifications_title}": _("web_notifications_title", lang),
        "{web_clear_notifications}": _("web_clear_notifications", lang), "{web_node_details_title}": _("web_node_details_title", lang),
        "{web_clear_logs_btn}": _("web_clear_logs_btn", lang), "{web_copied}": _("web_copied", lang),
        "{web_hint_cpu_usage}": _("web_hint_cpu_usage", lang), "{web_hint_ram_usage}": _("web_hint_ram_usage", lang),
        "{web_hint_disk_usage}": _("web_hint_disk_usage", lang), "{web_hint_traffic_in}": _("web_hint_traffic_in", lang),
        "{web_hint_traffic_out}": _("web_hint_traffic_out", lang),
    }
    for k, v in replacements.items(): html = html.replace(k, str(v))
    
    i18n_data = {
        "web_cpu": _("web_cpu", lang), "web_ram": _("web_ram", lang), "web_no_nodes": _("web_no_nodes", lang),
        "web_loading": _("web_loading", lang), "web_error": _("web_error", lang, error=""), "web_copied": _("web_copied", lang),
        "web_no_notifications": _("web_no_notifications", lang), "web_clear_notifications": _("web_clear_notifications", lang),
        "modal_title_confirm": _("modal_title_confirm", lang), "modal_btn_ok": _("modal_btn_ok", lang), "modal_btn_cancel": _("modal_btn_cancel", lang),
        "web_time_d": "д" if lang == 'ru' else "d", "web_time_h": "ч" if lang == 'ru' else "h", "web_time_m": "м" if lang == 'ru' else "m",
        "unit_bytes": _("unit_bytes", lang), "unit_kb": _("unit_kb", lang), "unit_mb": _("unit_mb", lang),
        "unit_gb": _("unit_gb", lang), "unit_tb": _("unit_tb", lang), "unit_pb": _("unit_pb", lang),
        "web_notif_cleared": STRINGS[lang].get("web_notif_cleared", "Уведомления очищены")
    }
    html = html.replace("{i18n_json}", json.dumps(i18n_data))
    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    try: data = await request.json()
    except: return web.json_response({"error": "Invalid JSON"}, status=400)
    token = data.get("token")
    node = await nodes_db.get_node_by_token(token)
    if not token or not node: return web.json_response({"error": "Auth fail"}, status=401)
    stats = data.get("stats", {})
    bot = request.app.get('bot')
    if bot and data.get("results"):
        for res in data["results"]:
            asyncio.create_task(process_node_result_background(bot, res.get("user_id"), res.get("command"), res.get("result"), token, node.get("name", "Node")))
    ip = stats.get("external_ip", request.transport.get_extra_info('peername')[0])
    await nodes_db.update_node_heartbeat(token, ip, stats)
    tasks = node.get("tasks", [])
    if tasks: await nodes_db.clear_node_tasks(token)
    return web.json_response({"status": "ok", "tasks": tasks})

async def process_node_result_background(bot, user_id, cmd, text, token, node_name):
    if not user_id or not text: return
    try:
        if cmd == "traffic" and user_id in NODE_TRAFFIC_MONITORS:
            m = NODE_TRAFFIC_MONITORS[user_id]
            if m.get("token") == token:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Stop", callback_data=f"node_stop_traffic_{token}")]])
                try: await bot.edit_message_text(text=text, chat_id=user_id, message_id=m["message_id"], reply_markup=kb, parse_mode="HTML")
                except: pass
                return
        await bot.send_message(chat_id=user_id, text=f"🖥 <b>{node_name}:</b>\n\n{text}", parse_mode="HTML")
    except: pass

async def handle_node_details(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    token = request.query.get("token")
    node = await nodes_db.get_node_by_token(token)
    if not node: return web.json_response({"error": "Node not found"}, status=404)
    return web.json_response({"name": node.get("name"), "ip": node.get("ip"), "stats": node.get("stats"), "history": node.get("history", []), "token": token})

async def handle_agent_stats(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    import psutil
    net = psutil.net_io_counters()
    stats = {"cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent, "disk": psutil.disk_usage(get_host_path('/')).percent, "ip": AGENT_IP_CACHE, "net_sent": net.bytes_sent, "net_recv": net.bytes_recv, "boot_time": psutil.boot_time()}
    return web.json_response({"stats": stats, "history": AGENT_HISTORY})

async def handle_node_add(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Admin required"}, status=403)
    data = await request.json()
    token = await nodes_db.create_node(data.get("name", "NewNode"))
    host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
    proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
    cmd = f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh) --agent={proto}://{host} --token={token}"
    return web.json_response({"status": "ok", "token": token, "command": cmd})

async def handle_node_delete(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Admin required"}, status=403)
    data = await request.json()
    await nodes_db.delete_node(data.get("token"))
    return web.json_response({"status": "ok"})

async def handle_nodes_list_json(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    all_n = await nodes_db.get_all_nodes()
    nodes_data = []
    for token, node in all_n.items():
        st = "offline"
        if node.get("is_restarting"): st = "restarting"
        elif time.time() - node.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT: st = "online"
        nodes_data.append({"token": token, "name": node.get("name"), "ip": node.get("ip"), "status": st, "cpu": node.get("stats",{}).get("cpu",0)})
    return web.json_response({"nodes": nodes_data})

async def handle_settings_page(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    html = load_template("settings.html")
    lang = get_user_lang(user['id'])
    # Аналогично handle_dashboard заполняем i18n_json
    i18n_data = {"web_notif_cleared": STRINGS[lang].get("web_notif_cleared", "Уведомления очищены")}
    html = html.replace("{i18n_json}", json.dumps(i18n_data))
    return web.Response(text=html, content_type='text/html')

async def handle_login_page(request):
    if get_current_user(request): raise web.HTTPFound('/')
    global BOT_USERNAME_CACHE
    if BOT_USERNAME_CACHE is None:
        try:
            bot = request.app.get('bot')
            if bot: me = await bot.get_me(); BOT_USERNAME_CACHE = me.username
        except: BOT_USERNAME_CACHE = ""
    html = load_template("login.html")
    alert = f"""<div class="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/50 rounded-xl flex items-start gap-3"><svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-yellow-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg><span class="text-xs text-yellow-200 font-medium">{_("web_default_pass_alert", DEFAULT_LANGUAGE)}</span></div>""" if is_default_password_active(ADMIN_USER_ID) else ""
    html = html.replace("{default_pass_alert}", alert).replace("{error_block}", "").replace("{bot_username}", BOT_USERNAME_CACHE or "").replace("style.css", f"style.css?v={CACHE_VER}")
    i18n_data = {"web_error": _("web_error", DEFAULT_LANGUAGE, error=""), "web_conn_error": _("web_conn_error", DEFAULT_LANGUAGE, error=""), "modal_title_alert": _("modal_title_alert", DEFAULT_LANGUAGE), "modal_btn_ok": _("modal_btn_ok", DEFAULT_LANGUAGE), "modal_btn_cancel": _("modal_btn_cancel", DEFAULT_LANGUAGE)}
    html = html.replace("{i18n_json}", json.dumps(i18n_data)) if "{i18n_json}" in html else html.replace("</body>", f"<script>const I18N = {json.dumps(i18n_data)};</script></body>")
    return web.Response(text=html, content_type='text/html')

async def handle_login_request(request):
    data = await request.post()
    try: uid = int(data.get("user_id", 0))
    except: uid = 0
    if uid not in ALLOWED_USERS: return web.Response(text="User not found", status=403)
    token = secrets.token_urlsafe(32); AUTH_TOKENS[token] = {"user_id": uid, "created_at": time.time()}
    host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
    proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
    link = f"{proto}://{host}/api/login/magic?token={token}"
    bot = request.app.get('bot')
    if bot:
        try:
            lang = get_user_lang(uid); kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("web_login_btn", lang), url=link)]])
            await bot.send_message(uid, _("web_login_header", lang), reply_markup=kb, parse_mode="HTML")
            return web.HTTPFound('/login?sent=true')
        except: pass
    return web.Response(text="Bot Error", status=500)

async def handle_login_password(request):
    data = await request.post(); ip = get_client_ip(request)
    if not check_rate_limit(ip): return web.Response(text="Rate limited. Wait 5 mins.", status=429)
    try: uid = int(data.get("user_id", 0))
    except: return web.Response(text="Invalid ID", status=400)
    if uid != ADMIN_USER_ID: return web.Response(text="Denied", status=403)
    if check_user_password(uid, data.get("password")):
        st = secrets.token_hex(32); SERVER_SESSIONS[st] = {"id": uid, "expires": time.time() + 604800}
        resp = web.HTTPFound('/'); resp.set_cookie(COOKIE_NAME, st, max_age=604800, httponly=True, samesite='Lax'); return resp
    add_login_attempt(ip); return web.Response(text="Invalid password", status=403)

async def handle_magic_login(request):
    token = request.query.get("token")
    if not token or token not in AUTH_TOKENS: return web.Response(text="Link expired", status=403)
    td = AUTH_TOKENS.pop(token)
    if time.time() - td["created_at"] > LOGIN_TOKEN_TTL: return web.Response(text="Expired", status=403)
    uid = td["user_id"]; st = secrets.token_hex(32); SERVER_SESSIONS[st] = {"id": uid, "expires": time.time() + 2592000}
    resp = web.HTTPFound('/'); resp.set_cookie(COOKIE_NAME, st, max_age=2592000, httponly=True, samesite='Lax'); return resp

async def handle_telegram_auth(request):
    try:
        data = await request.json()
        if not check_telegram_auth(data, TOKEN): return web.json_response({"error": "Invalid"}, status=403)
        uid = int(data.get('id'))
        if uid not in ALLOWED_USERS: return web.json_response({"error": "Denied"}, status=403)
        st = secrets.token_hex(32); SERVER_SESSIONS[st] = {"id": uid, "expires": time.time() + 2592000}
        resp = web.json_response({"status": "ok"}); resp.set_cookie(COOKIE_NAME, st, max_age=2592000, httponly=True, samesite='Lax'); return resp
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_logout(request):
    token = request.cookies.get(COOKIE_NAME)
    if token and token in SERVER_SESSIONS: del SERVER_SESSIONS[token]
    resp = web.HTTPFound('/login'); resp.del_cookie(COOKIE_NAME); return resp

async def handle_reset_request(request):
    try:
        data = await request.json()
        uid = int(data.get("user_id", 0))
        if uid != ADMIN_USER_ID: return web.json_response({"error": "not_found"}, status=404)
        token = secrets.token_urlsafe(32); RESET_TOKENS[token] = {"ts": time.time(), "user_id": uid}
        host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
        proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
        link = f"{proto}://{host}/reset_password?token={token}"
        bot = request.app.get('bot')
        if bot:
            lang = get_user_lang(uid); kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("web_reset_btn", lang), url=link)]])
            await bot.send_message(uid, _("web_reset_header", lang), reply_markup=kb, parse_mode="HTML"); return web.json_response({"status": "ok"})
        return web.json_response({"error": "bot_not_ready"}, status=500)
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_reset_page_render(request):
    token = request.query.get("token")
    if not token or token not in RESET_TOKENS or time.time() - RESET_TOKENS[token]["ts"] > RESET_TOKEN_TTL: return web.Response(text="Expired", status=403)
    html = load_template("reset_password.html").replace("{web_version}", CACHE_VER)
    i18n_data = {"web_error": _("web_error", DEFAULT_LANGUAGE, error=""), "modal_btn_ok": _("modal_btn_ok", DEFAULT_LANGUAGE), "modal_btn_cancel": _("modal_btn_cancel", DEFAULT_LANGUAGE)}
    html = html.replace("{i18n_json}", json.dumps(i18n_data)) if "{i18n_json}" in html else html.replace("</body>", f"<script>const I18N = {json.dumps(i18n_data)};</script></body>")
    return web.Response(text=html, content_type='text/html')

async def handle_reset_confirm(request):
    try:
        data = await request.json(); token, new_pass = data.get("token"), data.get("password")
        if not token or token not in RESET_TOKENS: return web.json_response({"error": "Expired"}, status=403)
        uid = RESET_TOKENS[token]["user_id"]
        if uid != ADMIN_USER_ID or len(new_pass) < 4: return web.json_response({"error": "Invalid"}, status=400)
        ALLOWED_USERS[uid] = {"group": "admins", "password_hash": PasswordHasher().hash(new_pass)}; save_users(); del RESET_TOKENS[token]
        return web.json_response({"status": "ok"})
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_api_root(request): return web.Response(text="VPS Bot API")

async def cleanup_server():
    global AGENT_TASK
    if AGENT_TASK and not AGENT_TASK.done():
        AGENT_TASK.cancel()
        try: await AGENT_TASK
        except asyncio.CancelledError: pass

async def start_web_server(bot_instance: Bot):
    global AGENT_TASK
    app = web.Application(); app['bot'] = bot_instance
    app.router.add_post('/api/heartbeat', handle_heartbeat)
    if ENABLE_WEB_UI:
        if os.path.exists(STATIC_DIR): app.router.add_static('/static', STATIC_DIR)
        app.router.add_get('/', handle_dashboard)
        app.router.add_get('/settings', handle_settings_page)
        app.router.add_get('/login', handle_login_page)
        app.router.add_post('/api/login/request', handle_login_request)
        app.router.add_get('/api/login/magic', handle_magic_login)
        app.router.add_post('/api/login/password', handle_login_password)
        app.router.add_post('/api/logout', handle_logout)
        app.router.add_get('/api/node/details', handle_node_details)
        app.router.add_get('/api/agent/stats', handle_agent_stats)
        app.router.add_get('/api/nodes/list', handle_nodes_list_json)
        app.router.add_get('/api/logs', handle_get_logs)
        app.router.add_get('/api/logs/system', handle_get_sys_logs)
        app.router.add_get('/api/notifications/list', api_get_notifications)
        app.router.add_post('/api/notifications/read', api_read_notifications)
        app.router.add_post('/api/notifications/clear', api_clear_notifications)
        app.router.add_get('/reset_password', handle_reset_page_render)
        app.router.add_post('/api/reset/confirm', handle_reset_confirm)
    else: app.router.add_get('/', handle_api_root)
    AGENT_TASK = asyncio.create_task(agent_monitor()); runner = web.AppRunner(app, access_log=None); await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start(); return runner

async def agent_monitor():
    global AGENT_IP_CACHE
    import psutil, requests
    try: AGENT_IP_CACHE = requests.get("https://api.ipify.org", timeout=3).text
    except: pass
    while True:
        try:
            cpu, ram, net = psutil.cpu_percent(interval=None), psutil.virtual_memory().percent, psutil.net_io_counters()
            AGENT_HISTORY.append({"t": int(time.time()), "c": cpu, "r": ram, "rx": net.bytes_recv, "tx": net.bytes_sent})
            if len(AGENT_HISTORY) > 60: AGENT_HISTORY.pop(0)
        except: pass
        await asyncio.sleep(2)