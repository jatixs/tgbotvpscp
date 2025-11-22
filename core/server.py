import logging
import time
import os
import json
import secrets
import asyncio
import requests
import psutil
import hashlib
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .nodes_db import get_node_by_token, update_node_heartbeat, create_node, delete_node
from .config import (
    WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR, ADMIN_USER_ID, ENABLE_WEB_UI,
    save_system_config, BOT_LOG_DIR, WATCHDOG_LOG_DIR, WEB_AUTH_FILE, ADMIN_USERNAME
)
from . import config as current_config
from .shared_state import NODES, NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES, AUTH_TOKENS, ALERTS_CONFIG, AGENT_HISTORY
from .i18n import STRINGS, get_user_lang, set_user_lang, get_text as _
from .config import DEFAULT_LANGUAGE
from .utils import get_country_flag, save_alerts_config, get_host_path
from .auth import save_users, get_user_name

COOKIE_NAME = "vps_agent_session"
LOGIN_TOKEN_TTL = 300 
RESET_TOKEN_TTL = 600 # 10 минут на сброс
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "core", "static")

AGENT_FLAG = "🏳️"
AGENT_IP_CACHE = "Loading..."

RESET_TOKENS = {} # {token: {"ts": timestamp, "user_id": user_id}}

# --- PASSWORD UTILS ---

def check_user_password(user_id, input_pass):
    """Проверяет пароль для КОНКРЕТНОГО пользователя"""
    if user_id not in ALLOWED_USERS:
        return False
    
    user_data = ALLOWED_USERS[user_id]
    # Если формат старый (строка), пароля нет
    if isinstance(user_data, str):
        return False
        
    stored_hash = user_data.get("password_hash")
    
    if not stored_hash:
        # Дефолтный "admin" только для Главного Админа, если хеш не задан
        if user_id == ADMIN_USER_ID and input_pass == "admin":
            return True
        return False

    return hashlib.sha256(input_pass.encode()).hexdigest() == stored_hash

def is_default_password_active(user_id):
    """Проверяет, используется ли дефолтный пароль для админа"""
    if user_id != ADMIN_USER_ID: return False
    if user_id not in ALLOWED_USERS: return False
    user_data = ALLOWED_USERS[user_id]
    
    # Хеш от "admin"
    default_hash = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"
    
    if isinstance(user_data, dict):
        p_hash = user_data.get("password_hash")
        return p_hash == default_hash or p_hash is None
    return True 

# --- HELPERS ---

def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Template not found</h1>"

def get_current_user(request):
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie: return None
    try:
        user_data = json.loads(cookie)
        uid = int(user_data.get('id'))
        
        if uid not in ALLOWED_USERS: return None
        
        u_data = ALLOWED_USERS[uid]
        role = u_data.get("group", "users") if isinstance(u_data, dict) else u_data
        
        user_data['role'] = role
        return user_data
    except: return None

def _get_avatar_html(user):
    raw = user.get('photo_url', '')
    if raw.startswith('http'): return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'

# --- BACKGROUND TASKS ---
async def agent_monitor():
    global AGENT_IP_CACHE
    psutil.cpu_percent(interval=None)
    try:
        def get_ip():
            try: return requests.get("https://api.ipify.org", timeout=3).text
            except: return "Unknown"
        AGENT_IP_CACHE = await asyncio.to_thread(get_ip)
    except: pass

    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            disk_path = get_host_path('/')
            try: disk = psutil.disk_usage(disk_path).percent
            except: disk = 0
            net = psutil.net_io_counters()
            point = {
                "t": int(time.time()),
                "c": cpu, "r": ram, "rx": net.bytes_recv, "tx": net.bytes_sent
            }
            AGENT_HISTORY.append(point)
            if len(AGENT_HISTORY) > 60: AGENT_HISTORY.pop(0)
        except Exception as e:
            logging.error(f"Agent monitor error: {e}")
        await asyncio.sleep(2)

async def process_node_result_background(bot, user_id, cmd, text, token, node_name):
    if not user_id or not text: return
    try:
        if cmd == "traffic" and user_id in NODE_TRAFFIC_MONITORS:
            monitor = NODE_TRAFFIC_MONITORS[user_id]
            if monitor.get("token") == token:
                msg_id = monitor.get("message_id")
                stop_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏹ Stop", callback_data=f"node_stop_traffic_{token}")]
                ])
                try:
                    await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=stop_kb, parse_mode="HTML")
                except Exception: pass 
                return
        full_text = f"🖥 <b>Ответ от {node_name}:</b>\n\n{text}"
        await bot.send_message(chat_id=user_id, text=full_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Background message send error (User: {user_id}): {e}")

# --- HANDLERS ---

async def handle_get_logs(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Unauthorized"}, status=403)
    log_path = os.path.join(BASE_DIR, "logs", "bot", "bot.log")
    if not os.path.exists(log_path): return web.json_response({"logs": ["Файл логов не найден."]})
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            if len(lines) > 300: lines = lines[-300:]
        return web.json_response({"logs": lines})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    
    html = load_template("dashboard.html")
    user_id = user['id']
    lang = get_user_lang(user_id)
    
    nodes_count = len(NODES)
    active_nodes = sum(1 for n in NODES.values() if time.time() - n.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT)
    
    role = user.get('role', 'users')
    role_color = "green" if role == "admins" else "gray"
    role_badge = f'<span class="px-2 py-0.5 rounded text-[10px] border border-{role_color}-500/30 bg-{role_color}-100 dark:bg-{role_color}-500/20 text-{role_color}-600 dark:text-{role_color}-400 uppercase font-bold">{role}</span>'

    # --- ЛОГИКА КНОПКИ (Добавить / Обновить) ---
    if user_id == ADMIN_USER_ID:
        # Главный админ -> Кнопка "Добавить" (ссылка на настройки)
        node_action_btn = f"""
        <a href="/settings" class="inline-flex items-center gap-1.5 py-1 px-2 rounded-lg bg-purple-50 dark:bg-white/5 border border-purple-100 dark:border-white/5 text-[10px] text-purple-600 dark:text-purple-300 font-medium transition hover:bg-purple-100 dark:hover:bg-white/10 cursor-pointer">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
            {_("web_add_user_btn", lang)}
        </a>
        """
    else:
        # Остальные -> Кнопка "Обновить" (перезагрузка страницы)
        node_action_btn = f"""
        <button onclick="location.reload()" class="inline-flex items-center gap-1.5 py-1 px-2 rounded-lg bg-purple-50 dark:bg-white/5 border border-purple-100 dark:border-white/5 text-[10px] text-purple-600 dark:text-purple-300 font-medium transition hover:bg-purple-100 dark:hover:bg-white/10 cursor-pointer">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
            {_("web_refresh", lang)}
        </button>
        """

    admin_controls_html = ""
    if role == "admins":
        admin_controls_html = f"""
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
            <a href="/settings" class="flex items-center justify-center gap-2 p-4 bg-white/60 dark:bg-white/5 border border-white/40 dark:border-white/10 rounded-xl hover:bg-white/80 dark:hover:bg-white/10 transition group shadow-sm hover:shadow-md backdrop-blur-md">
                <div class="p-2 bg-blue-100 dark:bg-blue-500/20 rounded-lg text-blue-600 dark:text-blue-400 group-hover:scale-110 transition">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" /></svg>
                </div>
                <span class="font-bold text-gray-700 dark:text-gray-200">{_("web_settings_button", lang)}</span>
            </a>
            <button onclick="openLogsModal()" class="flex items-center justify-center gap-2 p-4 bg-white/60 dark:bg-white/5 border border-white/40 dark:border-white/10 rounded-xl hover:bg-white/80 dark:hover:bg-white/10 transition group shadow-sm hover:shadow-md backdrop-blur-md">
                <div class="p-2 bg-yellow-100 dark:bg-yellow-500/20 rounded-lg text-yellow-600 dark:text-yellow-400 group-hover:scale-110 transition">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                </div>
                <span class="font-bold text-gray-700 dark:text-gray-200">{_("web_logs_button", lang)}</span>
            </button>
        </div>
        """

    replacements = {
        "{web_title}": f"{_('web_dashboard_title', lang)} - Web Bot",
        "{web_dashboard_title}": _("web_dashboard_title", lang),
        "{role_badge}": role_badge,
        "{user_avatar}": _get_avatar_html(user),
        "{user_name}": user.get('first_name', 'User'),
        "{nodes_count}": str(nodes_count),
        "{active_nodes}": str(active_nodes),
        "{web_agent_stats_title}": _("web_agent_stats_title", lang),
        "{web_uptime}": _("web_uptime", lang),
        "{web_cpu}": _("web_cpu", lang),
        "{web_ram}": _("web_ram", lang),
        "{web_disk}": _("web_disk", lang),
        "{web_traffic_total}": _("web_traffic_total", lang),
        "{web_node_mgmt_title}": _("web_node_mgmt_title", lang),
        "{web_nodes_loading}": _("web_nodes_loading", lang),
        "{admin_controls_html}": admin_controls_html,
        "{web_node_details_title}": _("web_node_details_title", lang),
        "{web_token_label}": _("web_token_label", lang),
        "{web_copied}": _("web_copied", lang),
        "{web_resources_chart}": _("web_resources_chart", lang),
        "{web_network_chart}": _("web_network_chart", lang),
        "{web_logs_title}": _("web_logs_title", lang),
        "{web_refresh}": _("web_refresh", lang),
        "{web_loading}": _("web_loading", lang),
        "{web_logs_footer}": _("web_logs_footer", lang),
        "{web_stats_total}": _("web_stats_total", lang),
        "{web_stats_active}": _("web_stats_active", lang),
        "{node_action_btn}": node_action_btn,
    }

    for k, v in replacements.items():
        html = html.replace(k, v)

    i18n_data = {
        "web_cpu": _("web_cpu", lang),
        "web_ram": _("web_ram", lang),
        "web_no_nodes": _("web_no_nodes", lang),
        "web_loading": _("web_loading", lang),
        "web_access_denied": _("web_access_denied", lang),
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "web_log_empty": _("web_log_empty", lang)
    }
    html = html.replace("{i18n_json}", json.dumps(i18n_data))
    return web.Response(text=html, content_type='text/html')

async def handle_settings_page(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    
    html = load_template("settings.html")
    user_id = user['id']
    is_admin = user['role'] == 'admins'
    lang = get_user_lang(user_id)
    user_alerts = ALERTS_CONFIG.get(user_id, {})
    
    users_json = "null"
    if is_admin:
        users_list = []
        for uid, role in ALLOWED_USERS.items():
            if uid == ADMIN_USER_ID: continue
            user_info = ALLOWED_USERS[uid]
            user_role = user_info.get("group", "users") if isinstance(user_info, dict) else user_info
            name = USER_NAMES.get(str(uid), f"ID: {uid}")
            users_list.append({"id": uid, "name": name, "role": user_role})
        users_json = json.dumps(users_list)

    html = html.replace("{web_title}", f"{_('web_settings_page_title', lang)} - Web Bot")
    html = html.replace("{user_name}", user.get('first_name', 'User'))
    html = html.replace("{user_avatar}", _get_avatar_html(user))
    html = html.replace("{users_data_json}", users_json)
    
    for key in ["web_settings_page_title", "web_back", "web_notif_section", "notifications_alert_name_res", 
                "notifications_alert_name_logins", "notifications_alert_name_bans", "notifications_alert_name_downtime",
                "web_save_btn", "web_users_section", "web_add_user_btn", "web_user_id", "web_user_name", 
                "web_user_role", "web_user_action", "web_add_node_section", "web_node_name_placeholder", 
                "web_create_btn", "web_node_token", "web_node_cmd", "web_sys_settings_section", "web_thresholds_title",
                "web_intervals_title", "web_logs_mgmt_title", "web_cpu_threshold", "web_ram_threshold", 
                "web_disk_threshold", "web_traffic_interval", "web_node_timeout", "web_clear_logs_btn",
                "web_security_section", "web_change_password_title", "web_current_password", 
                "web_new_password", "web_confirm_password", "web_change_btn"]:
        html = html.replace(f"{{{key}}}", _(key, lang))

    html = html.replace("{val_cpu}", str(current_config.CPU_THRESHOLD))
    html = html.replace("{val_ram}", str(current_config.RAM_THRESHOLD))
    html = html.replace("{val_disk}", str(current_config.DISK_THRESHOLD))
    html = html.replace("{val_traffic}", str(current_config.TRAFFIC_INTERVAL))
    html = html.replace("{val_timeout}", str(current_config.NODE_OFFLINE_TIMEOUT))
    
    for alert in ['resources', 'logins', 'bans', 'downtime']:
        checked = "checked" if user_alerts.get(alert, False) else ""
        html = html.replace(f"{{check_{alert}}}", checked)
        
    if user_id != ADMIN_USER_ID:
        html = html.replace('<div class="bg-white/60 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/10 rounded-2xl p-6 mb-6 shadow-lg dark:shadow-none" id="securitySection">', '<div class="hidden">')

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
        "web_pass_mismatch": _("web_pass_mismatch", lang)
    }
    html = html.replace("{i18n_json}", json.dumps(i18n_data))
    return web.Response(text=html, content_type='text/html')

async def handle_save_notifications(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Auth required"}, status=401)
    try:
        data = await request.json()
        user_id = user['id']
        if user_id not in ALERTS_CONFIG: ALERTS_CONFIG[user_id] = {}
        for key in ['resources', 'logins', 'bans', 'downtime']:
            if key in data: ALERTS_CONFIG[user_id][key] = bool(data[key])
        save_alerts_config()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_save_system_config(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        traffic_interval = int(data.get("TRAFFIC_INTERVAL", 0))
        lang = get_user_lang(user['id'])
        if traffic_interval < 5:
            return web.json_response({"error": _("error_traffic_interval_low", lang)}, status=400)
        if traffic_interval > 100:
            return web.json_response({"error": _("error_traffic_interval_high", lang)}, status=400)
        save_system_config(data)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_change_password(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    
    user_id = user['id']
    if user_id != ADMIN_USER_ID:
         return web.json_response({"error": "Only Main Admin can change password"}, status=403)
    
    try:
        data = await request.json()
        current_pass = data.get("current_password")
        new_pass = data.get("new_password")
        
        if not check_user_password(user_id, current_pass):
            lang = get_user_lang(user_id)
            return web.json_response({"error": _("web_pass_wrong_current", lang)}, status=400)
        
        if not new_pass or len(new_pass) < 4:
             return web.json_response({"error": "Password too short"}, status=400)

        new_hash = hashlib.sha256(new_pass.encode()).hexdigest()
        
        if isinstance(ALLOWED_USERS[user_id], str):
             ALLOWED_USERS[user_id] = {"group": ALLOWED_USERS[user_id], "password_hash": new_hash}
        else:
             ALLOWED_USERS[user_id]["password_hash"] = new_hash
             
        save_users()
            
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_clear_logs(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Admin required"}, status=403)
    try:
        for d in [BOT_LOG_DIR, WATCHDOG_LOG_DIR]:
            if os.path.exists(d):
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp): 
                        with open(fp, 'w') as file: pass 
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_user_action(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        action = data.get('action')
        target_id = int(data.get('id', 0))
        if not target_id: return web.json_response({"error": "Invalid ID"}, status=400)
        if target_id == ADMIN_USER_ID: return web.json_response({"error": "Cannot affect Main Admin"}, status=400)
        
        if action == 'delete':
            if target_id in ALLOWED_USERS:
                del ALLOWED_USERS[target_id]
                if str(target_id) in USER_NAMES: del USER_NAMES[str(target_id)]
                if target_id in ALERTS_CONFIG: del ALERTS_CONFIG[target_id]
                save_users()
                save_alerts_config()
                return web.json_response({"status": "ok"})
        elif action == 'add':
            if target_id in ALLOWED_USERS: return web.json_response({"error": "User exists"}, status=400)
            # Новые пользователи без пароля
            ALLOWED_USERS[target_id] = {"group": data.get('role', 'users'), "password_hash": None}
            bot = request.app.get('bot')
            if bot: await get_user_name(bot, target_id)
            else: USER_NAMES[str(target_id)] = f"User {target_id}"
            save_users()
            return web.json_response({"status": "ok", "name": USER_NAMES.get(str(target_id))})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"error": "Unknown action"}, status=400)

async def handle_node_add(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': return web.json_response({"error": "Admin required"}, status=403)
    try:
        data = await request.json()
        name = data.get("name")
        if not name: return web.json_response({"error": "Name required"}, status=400)
        token = create_node(name)
        host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
        proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
        
        user_id = user['id']
        lang = get_user_lang(user_id)
        script_name = "deploy_en.sh" if lang == "en" else "deploy.sh"

        cmd = f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/{script_name}) --agent={proto}://{host} --token={token}"
        
        return web.json_response({"status": "ok", "token": token, "command": cmd})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_nodes_list_json(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    nodes_data = []
    now = time.time()
    for token, node in NODES.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        status = "offline"
        if is_restarting: status = "restarting"
        elif now - last_seen < NODE_OFFLINE_TIMEOUT: status = "online"
        stats = node.get("stats", {})
        nodes_data.append({
            "token": token, "name": node.get("name", "Unknown"), "ip": node.get("ip", "Unknown"),
            "status": status, "cpu": stats.get("cpu", 0), "ram": stats.get("ram", 0), "disk": stats.get("disk", 0)
        })
    return web.json_response({"nodes": nodes_data})

async def handle_set_language(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        lang = data.get("lang")
        if lang in ["ru", "en"]:
            set_user_lang(user['id'], lang)
            return web.json_response({"status": "ok"})
        return web.json_response({"error": "Invalid language"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# --- FORGOT PASSWORD HANDLERS ---

async def handle_reset_request(request):
    try:
        data = await request.json()
        try: user_id = int(data.get("user_id", 0))
        except: user_id = 0
        
        if user_id != ADMIN_USER_ID:
            admin_url = f"https://t.me/{ADMIN_USERNAME}" if ADMIN_USERNAME else f"tg://user?id={ADMIN_USER_ID}"
            return web.json_response({"error": "not_found", "admin_url": admin_url}, status=404)

        token = secrets.token_urlsafe(32)
        RESET_TOKENS[token] = {"ts": time.time(), "user_id": user_id}
        
        host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
        proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
        reset_link = f"{proto}://{host}/reset_password?token={token}"
        
        bot = request.app.get('bot')
        if bot:
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔐 Сбросить пароль", url=reset_link)]])
                await bot.send_message(user_id, "<b>🆘 Сброс пароля Web-панели</b>\n\nНажмите кнопку ниже для установки нового пароля.", reply_markup=kb, parse_mode="HTML")
                return web.json_response({"status": "ok"})
            except Exception as e:
                logging.error(f"Failed to send reset link: {e}")
                return web.json_response({"error": "bot_send_error"}, status=500)
        
        return web.json_response({"error": "bot_not_ready"}, status=500)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_reset_page_render(request):
    token = request.query.get("token")
    
    if not token or token not in RESET_TOKENS:
        return web.Response(text="Link expired or invalid.", status=403)
    if time.time() - RESET_TOKENS[token]["ts"] > RESET_TOKEN_TTL:
        del RESET_TOKENS[token]
        return web.Response(text="Link expired.", status=403)

    html = load_template("login.html")
    html = html.replace("{error_block}", "")
    html = html.replace("{default_pass_alert}", "")
    return web.Response(text=html, content_type='text/html')

async def handle_reset_confirm(request):
    try:
        data = await request.json()
        token = data.get("token")
        new_pass = data.get("password")
        
        if not token or token not in RESET_TOKENS:
             return web.json_response({"error": "Token expired"}, status=403)
        
        user_id = RESET_TOKENS[token]["user_id"]
        
        if user_id != ADMIN_USER_ID:
             del RESET_TOKENS[token]
             return web.json_response({"error": "Access denied"}, status=403)

        if not new_pass or len(new_pass) < 4:
             return web.json_response({"error": "Password too short"}, status=400)

        new_hash = hashlib.sha256(new_pass.encode()).hexdigest()
        
        if isinstance(ALLOWED_USERS[user_id], str):
             ALLOWED_USERS[user_id] = {"group": ALLOWED_USERS[user_id], "password_hash": new_hash}
        else:
             ALLOWED_USERS[user_id]["password_hash"] = new_hash
             
        save_users()
        
        del RESET_TOKENS[token]
        
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# --- LOGIN PAGE ---

async def handle_login_page(request):
    if get_current_user(request): raise web.HTTPFound('/')
    html = load_template("login.html")
    
    alert_block = ""
    if is_default_password_active(ADMIN_USER_ID):
        lang = DEFAULT_LANGUAGE
        alert_msg = _("web_default_pass_alert", lang)
        alert_block = f"""
        <div class="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/50 rounded-xl flex items-start gap-3">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-yellow-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span class="text-xs text-yellow-200 font-medium">{alert_msg}</span>
        </div>
        """
    
    html = html.replace("{default_pass_alert}", alert_block)
    html = html.replace("{error_block}", "")
    return web.Response(text=html, content_type='text/html')

async def handle_login_request(request):
    data = await request.post()
    try: user_id = int(data.get("user_id", 0))
    except: user_id = 0
    
    if user_id not in ALLOWED_USERS: return web.Response(text="User not found", status=403)
    
    token = secrets.token_urlsafe(32)
    AUTH_TOKENS[token] = {"user_id": user_id, "created_at": time.time()}
    host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
    proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
    magic_link = f"{proto}://{host}/api/login/magic?token={token}"
    
    bot = request.app.get('bot')
    if bot:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Войти в панель", url=magic_link)]])
            await bot.send_message(user_id, "<b>🔐 Вход в Web-панель</b>", reply_markup=kb, parse_mode="HTML")
            return web.HTTPFound('/login?sent=true')
        except: pass
    return web.Response(text="Bot Error", status=500)

async def handle_login_password(request):
    data = await request.post()
    try:
        user_id = int(data.get("user_id", 0))
    except:
        return web.Response(text="Invalid User ID", status=400)
        
    password = data.get("password")
    
    if user_id != ADMIN_USER_ID:
         return web.Response(text="Password login available for Main Admin only.", status=403)

    if check_user_password(user_id, password):
        u_data = ALLOWED_USERS[user_id]
        role = u_data.get("group", "users") if isinstance(u_data, dict) else u_data
        name = USER_NAMES.get(str(user_id), f"ID: {user_id}")
        
        session = {
            "id": user_id, 
            "first_name": name, 
            "username": str(user_id), 
            "photo_url": AGENT_FLAG, 
            "role": role, 
            "type": "password"
        }
        resp = web.HTTPFound('/')
        resp.set_cookie(COOKIE_NAME, json.dumps(session), max_age=604800)
        return resp
        
    return web.Response(text="Invalid password", status=403)

async def handle_magic_login(request):
    token = request.query.get("token")
    if not token or token not in AUTH_TOKENS: return web.Response(text="Link expired", status=403)
    td = AUTH_TOKENS.pop(token)
    if time.time() - td["created_at"] > LOGIN_TOKEN_TTL: return web.Response(text="Expired", status=403)
    uid = td["user_id"]
    if uid not in ALLOWED_USERS: return web.Response(text="Denied", status=403)
    
    u_data = ALLOWED_USERS[uid]
    role = u_data.get("group", "users") if isinstance(u_data, dict) else u_data
    
    session = {"id": uid, "first_name": USER_NAMES.get(str(uid), f"ID:{uid}"), "photo_url": "https://cdn-icons-png.flaticon.com/512/149/149071.png", "role": role, "type": "telegram"}
    resp = web.HTTPFound('/')
    resp.set_cookie(COOKIE_NAME, json.dumps(session), max_age=2592000)
    return resp

async def handle_logout(request):
    resp = web.HTTPFound('/login')
    resp.del_cookie(COOKIE_NAME)
    return resp

async def handle_heartbeat(request):
    try: data = await request.json()
    except: return web.json_response({"error": "Invalid JSON"}, status=400)
    token = data.get("token")
    if not token or not get_node_by_token(token): return web.json_response({"error": "Auth fail"}, status=401)
    node = get_node_by_token(token)
    stats = data.get("stats", {})
    results = data.get("results", [])
    bot = request.app.get('bot')
    if bot and results:
        for res in results:
            asyncio.create_task(process_node_result_background(bot, res.get("user_id"), res.get("command"), res.get("result"), token, node.get("name", "Node")))
    node["is_restarting"] = False 
    update_node_heartbeat(token, request.transport.get_extra_info('peername')[0], stats)
    tasks_to_send = list(node.get("tasks", []))
    if tasks_to_send: node["tasks"] = []
    return web.json_response({"status": "ok", "tasks": tasks_to_send})

async def handle_node_details(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    token = request.query.get("token")
    if not token or token not in NODES: return web.json_response({"error": "Node not found"}, status=404)
    node = NODES[token]
    return web.json_response({
        "name": node.get("name"), "ip": node.get("ip"), "stats": node.get("stats"),
        "history": node.get("history", []), "token": token, "last_seen": node.get("last_seen", 0),
        "is_restarting": node.get("is_restarting", False)
    })

async def handle_agent_stats(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    current_stats = {"cpu": 0, "ram": 0, "disk": 0, "ip": AGENT_IP_CACHE, "net_sent": 0, "net_recv": 0, "boot_time": 0}
    try:
        net_io = psutil.net_io_counters()
        current_stats["net_sent"] = net_io.bytes_sent; current_stats["net_recv"] = net_io.bytes_recv; current_stats["boot_time"] = psutil.boot_time()
    except: pass
    if AGENT_HISTORY:
        latest = AGENT_HISTORY[-1]
        current_stats["cpu"] = latest["c"]; current_stats["ram"] = latest["r"]
        try: current_stats["disk"] = psutil.disk_usage(get_host_path('/')).percent
        except: pass
    return web.json_response({"stats": current_stats, "history": AGENT_HISTORY})

async def handle_api_root(request):
    return web.Response(text="VPS Bot API Server is running.")

async def start_web_server(bot_instance: Bot):
    global AGENT_FLAG
    app = web.Application()
    app['bot'] = bot_instance
    
    app.router.add_post('/api/heartbeat', handle_heartbeat)

    if ENABLE_WEB_UI:
        logging.info("Web UI is ENABLED. Registering UI routes...")
        if os.path.exists(STATIC_DIR): app.router.add_static('/static', STATIC_DIR)
        app.router.add_get('/', handle_dashboard)
        app.router.add_get('/settings', handle_settings_page)
        app.router.add_get('/login', handle_login_page)
        app.router.add_post('/api/login/request', handle_login_request)
        app.router.add_get('/api/login/magic', handle_magic_login)
        app.router.add_post('/api/login/password', handle_login_password)
        app.router.add_post('/api/login/reset', handle_reset_request)
        app.router.add_get('/reset_password', handle_reset_page_render)
        app.router.add_post('/api/reset/confirm', handle_reset_confirm)
        app.router.add_post('/logout', handle_logout)
        app.router.add_get('/api/node/details', handle_node_details)
        app.router.add_get('/api/agent/stats', handle_agent_stats)
        app.router.add_get('/api/nodes/list', handle_nodes_list_json)
        app.router.add_get('/api/logs', handle_get_logs)
        app.router.add_post('/api/settings/save', handle_save_notifications)
        app.router.add_post('/api/settings/language', handle_set_language)
        app.router.add_post('/api/settings/system', handle_save_system_config)
        app.router.add_post('/api/settings/password', handle_change_password)
        app.router.add_post('/api/logs/clear', handle_clear_logs)
        app.router.add_post('/api/users/action', handle_user_action)
        app.router.add_post('/api/nodes/add', handle_node_add)
    else:
        logging.info("Web UI is DISABLED. Only API is active.")
        app.router.add_get('/', handle_api_root)

    try:
        def fetch_flag():
            try: return get_country_flag(requests.get("https://api.ipify.org", timeout=2).text)
            except: return "🏳️"
        AGENT_FLAG = await asyncio.to_thread(fetch_flag)
    except: pass

    asyncio.create_task(agent_monitor())
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    try:
        await site.start()
        logging.info(f"Web Server started on {WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        return runner
    except Exception as e:
        logging.error(f"Failed to start Web Server: {e}")
        return None