import logging
import time
import os
import json
import secrets
import asyncio
import requests
import psutil
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .nodes_db import get_node_by_token, update_node_heartbeat, create_node, delete_node
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR, ADMIN_USER_ID, ENABLE_WEB_UI
from .shared_state import NODES, NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES, AUTH_TOKENS, ALERTS_CONFIG, AGENT_HISTORY
from .i18n import STRINGS, get_user_lang, set_user_lang, get_text as _
from .config import DEFAULT_LANGUAGE
from .utils import get_country_flag, save_alerts_config, get_host_path
from .auth import save_users, get_user_name

COOKIE_NAME = "vps_agent_session"
LOGIN_TOKEN_TTL = 300 
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "core", "static")

AGENT_FLAG = "🏳️"
AGENT_IP_CACHE = "Loading..."

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
        if user_data.get('type') == 'password': return user_data
        uid = int(user_data.get('id'))
        if uid not in ALLOWED_USERS: return None
        user_data['role'] = ALLOWED_USERS[uid]
        return user_data
    except: return None

# --- ФОНОВАЯ ЗАДАЧА МОНИТОРИНГА АГЕНТА ---
async def agent_monitor():
    """Собирает статистику локального сервера (Агента)."""
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
            try:
                disk = psutil.disk_usage(disk_path).percent
            except:
                disk = 0

            net = psutil.net_io_counters()
            
            point = {
                "t": int(time.time()),
                "c": cpu,
                "r": ram,
                "rx": net.bytes_recv,
                "tx": net.bytes_sent
            }
            
            AGENT_HISTORY.append(point)
            if len(AGENT_HISTORY) > 60:
                AGENT_HISTORY.pop(0)
                
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

async def handle_get_logs(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins':
        return web.json_response({"error": "Unauthorized"}, status=403)
    
    log_path = os.path.join(BASE_DIR, "logs", "bot", "bot.log")
    if not os.path.exists(log_path):
        return web.json_response({"logs": ["Файл логов не найден."]})
        
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            if len(lines) > 300: lines = lines[-300:]
        return web.json_response({"logs": lines})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

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
            if uid == ADMIN_USER_ID:
                continue
            name = USER_NAMES.get(str(uid), f"ID: {uid}")
            users_list.append({"id": uid, "name": name, "role": role})
        users_json = json.dumps(users_list)

    # ИЗМЕНЕНО: Заголовок страницы
    html = html.replace("{web_title}", f"{_('web_settings_page_title', lang)} - Web Bot")
    html = html.replace("{user_name}", user.get('first_name', 'User'))
    html = html.replace("{user_avatar}", _get_avatar_html(user))
    html = html.replace("{users_data_json}", users_json)
    
    # Замена переводов
    html = html.replace("{web_settings_page_title}", _("web_settings_page_title", lang))
    html = html.replace("{web_back}", _("web_back", lang))
    html = html.replace("{web_notif_section}", _("web_notif_section", lang))
    html = html.replace("{notifications_alert_name_res}", _("notifications_alert_name_res", lang))
    html = html.replace("{notifications_alert_name_logins}", _("notifications_alert_name_logins", lang))
    html = html.replace("{notifications_alert_name_bans}", _("notifications_alert_name_bans", lang))
    html = html.replace("{notifications_alert_name_downtime}", _("notifications_alert_name_downtime", lang))
    html = html.replace("{web_save_btn}", _("web_save_btn", lang))
    html = html.replace("{web_users_section}", _("web_users_section", lang))
    html = html.replace("{web_add_user_btn}", _("web_add_user_btn", lang))
    html = html.replace("{web_user_id}", _("web_user_id", lang))
    html = html.replace("{web_user_name}", _("web_user_name", lang))
    html = html.replace("{web_user_role}", _("web_user_role", lang))
    html = html.replace("{web_user_action}", _("web_user_action", lang))
    html = html.replace("{web_add_node_section}", _("web_add_node_section", lang))
    html = html.replace("{web_node_name_placeholder}", _("web_node_name_placeholder", lang))
    html = html.replace("{web_create_btn}", _("web_create_btn", lang))
    html = html.replace("{web_node_token}", _("web_node_token", lang))
    html = html.replace("{web_node_cmd}", _("web_node_cmd", lang))
    
    for alert in ['resources', 'logins', 'bans', 'downtime']:
        checked = "checked" if user_alerts.get(alert, False) else ""
        html = html.replace(f"{{check_{alert}}}", checked)
        
    i18n_data = {
        "web_saving_btn": _("web_saving_btn", lang),
        "web_saved_btn": _("web_saved_btn", lang),
        "web_save_btn": _("web_save_btn", lang),
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "web_confirm_delete_user": _("web_confirm_delete_user", lang),
        "web_no_users": _("web_no_users", lang)
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
            if key in data:
                ALERTS_CONFIG[user_id][key] = bool(data[key])
        
        save_alerts_config()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_user_action(request):
    user = get_current_user(request)
    if not user or user['role'] != 'admins': 
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        action = data.get('action')
        target_id = int(data.get('id', 0))
        
        if not target_id: return web.json_response({"error": "Invalid ID"}, status=400)
        
        if target_id == ADMIN_USER_ID:
            return web.json_response({"error": "Cannot affect Main Admin"}, status=400)

        if action == 'delete':
            if target_id in ALLOWED_USERS:
                del ALLOWED_USERS[target_id]
                if str(target_id) in USER_NAMES: del USER_NAMES[str(target_id)]
                if target_id in ALERTS_CONFIG: del ALERTS_CONFIG[target_id]
                save_users()
                save_alerts_config()
                return web.json_response({"status": "ok"})
            
        elif action == 'add':
            if target_id in ALLOWED_USERS:
                return web.json_response({"error": "User exists"}, status=400)
            ALLOWED_USERS[target_id] = data.get('role', 'users')
            bot = request.app.get('bot')
            if bot:
                await get_user_name(bot, target_id)
            else:
                USER_NAMES[str(target_id)] = f"User {target_id}"
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
        cmd = f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh) # Select 8, Url: {proto}://{host}, Token: {token}"
        
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
            "token": token,
            "name": node.get("name", "Unknown"),
            "ip": node.get("ip", "Unknown"),
            "status": status,
            "cpu": stats.get("cpu", 0),
            "ram": stats.get("ram", 0),
            "disk": stats.get("disk", 0)
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

async def handle_login_page(request):
    if get_current_user(request): raise web.HTTPFound('/')
    html = load_template("login.html")
    html = html.replace("{error_block}", "")
    return web.Response(text=html, content_type='text/html')

async def handle_login_request(request):
    data = await request.post()
    try: user_id = int(data.get("user_id", 0))
    except: user_id = 0
    if user_id not in ALLOWED_USERS:
        return web.Response(text="User not found", status=403)
    
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
    if data.get("password") == WEB_PASSWORD:
        session = {"id": 0, "first_name": "Administrator", "username": "admin", "photo_url": AGENT_FLAG, "role": "admins", "type": "password"}
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
    
    session = {"id": uid, "first_name": USER_NAMES.get(str(uid), f"ID:{uid}"), "photo_url": "https://cdn-icons-png.flaticon.com/512/149/149071.png", "role": ALLOWED_USERS[uid], "type": "telegram"}
    resp = web.HTTPFound('/')
    resp.set_cookie(COOKIE_NAME, json.dumps(session), max_age=2592000)
    return resp

async def handle_logout(request):
    resp = web.HTTPFound('/login')
    resp.del_cookie(COOKIE_NAME)
    return resp

async def handle_agent_stats(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    
    current_stats = {
        "cpu": 0, "ram": 0, "disk": 0, "ip": AGENT_IP_CACHE,
        "net_sent": 0, "net_recv": 0, "boot_time": 0
    }
    
    try:
        net_io = psutil.net_io_counters()
        current_stats["net_sent"] = net_io.bytes_sent
        current_stats["net_recv"] = net_io.bytes_recv
        current_stats["boot_time"] = psutil.boot_time()
    except: pass

    if AGENT_HISTORY:
        latest = AGENT_HISTORY[-1]
        current_stats["cpu"] = latest["c"]
        current_stats["ram"] = latest["r"]
        try:
            current_stats["disk"] = psutil.disk_usage(get_host_path('/')).percent
        except: pass

    return web.json_response({
        "stats": current_stats,
        "history": AGENT_HISTORY
    })

async def handle_node_details(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    token = request.query.get("token")
    if not token or token not in NODES: return web.json_response({"error": "Node not found"}, status=404)
    node = NODES[token]
    return web.json_response({
        "name": node.get("name"),
        "ip": node.get("ip"),
        "stats": node.get("stats"),
        "history": node.get("history", []),
        "token": token,
        "last_seen": node.get("last_seen", 0),
        "is_restarting": node.get("is_restarting", False)
    })

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

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    is_admin = user['role'] == 'admins'
    lang = get_user_lang(user['id'])

    now = time.time()
    active_count = 0
    
    nodes_count = len(NODES)
    for token, node in NODES.items():
        last_seen = node.get("last_seen", 0)
        if now - last_seen < NODE_OFFLINE_TIMEOUT: active_count += 1

    role_badge = '<span class="bg-green-500/20 text-green-400 text-[10px] px-2 py-0.5 rounded border border-green-500/30">ADMIN</span>' if is_admin else '<span class="bg-gray-500/20 text-gray-300 text-[10px] px-2 py-0.5 rounded border border-gray-500/30">USER</span>'
    
    admin_controls = f"""
    <div class="mt-8 p-6 rounded-2xl bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-gray-200 dark:border-white/5">
        <h3 class="text-lg font-bold text-gray-900 dark:text-white mb-2">{_("web_admin_panel", lang)}</h3>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">{_("web_admin_desc", lang)}</p>
        <div class="flex gap-3">
            <button onclick="openLogsModal()" class="px-4 py-2 bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20 rounded-lg text-sm text-gray-900 dark:text-white transition flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                {_("web_logs_button", lang)}
            </button>
            <a href="/settings" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white transition flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
                {_("web_settings_button", lang)}
            </a>
        </div>
    </div>
    """ if is_admin else ""

    html = load_template("dashboard.html")
    # ИЗМЕНЕНО: Заголовок страницы
    html = html.replace("{web_title}", f"{_('web_dashboard_title', lang)} - Web Bot")
    
    web_dashboard_title = _("web_dashboard_title", lang)
    web_agent_stats_title = _("web_agent_stats_title", lang)
    web_stats_total = _("web_stats_total", lang)
    web_stats_active = _("web_stats_active", lang)
    web_traffic_total = _("web_traffic_total", lang)
    web_uptime = _("web_uptime", lang)
    web_cpu = _("web_cpu", lang)
    web_ram = _("web_ram", lang)
    web_disk = _("web_disk", lang)
    web_rx = _("web_rx", lang)
    web_tx = _("web_tx", lang)
    
    html = html.replace("{web_dashboard_title}", web_dashboard_title)
    html = html.replace("{web_agent_stats_title}", web_agent_stats_title)
    html = html.replace("{web_stats_total}", web_stats_total)
    html = html.replace("{web_stats_active}", web_stats_active)
    html = html.replace("{web_traffic_total}", web_traffic_total)
    html = html.replace("{web_uptime}", web_uptime)
    html = html.replace("{web_cpu}", web_cpu)
    html = html.replace("{web_ram}", web_ram)
    html = html.replace("{web_disk}", web_disk)
    html = html.replace("{web_rx}", web_rx)
    html = html.replace("{web_tx}", web_tx)
    
    html = html.replace("{user_avatar}", _get_avatar_html(user))
    html = html.replace("{user_name}", user.get('first_name', 'User'))
    html = html.replace("{role_badge}", role_badge)
    html = html.replace("{nodes_count}", str(nodes_count))
    html = html.replace("{active_nodes}", str(active_count))
    html = html.replace("{user_group_display}", "") 
    html = html.replace("{admin_controls_html}", admin_controls)
    
    html = html.replace("{web_node_mgmt_title}", _("web_node_mgmt_title", lang))
    
    i18n_data = {
        "web_nodes_loading": _("web_nodes_loading", lang),
        "web_no_nodes": _("web_no_nodes", lang),
        "web_cpu": _("web_cpu", lang),
        "web_ram": _("web_ram", lang),
        "web_details_hidden": _("web_details_hidden", lang),
        "web_loading": _("web_loading", lang),
        "web_access_denied": _("web_access_denied", lang),
        "web_error": _("web_error", lang, error=""),
        "web_log_empty": _("web_log_empty", lang),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "web_copied": _("web_copied", lang)
    }
    html = html.replace("{i18n_json}", json.dumps(i18n_data))
    
    html = html.replace("{web_node_details_title}", _("web_node_details_title", lang))
    html = html.replace("{web_token_label}", _("web_token_label", lang))
    html = html.replace("{web_copied}", _("web_copied", lang))
    html = html.replace("{web_resources_chart}", _("web_resources_chart", lang))
    html = html.replace("{web_network_chart}", _("web_network_chart", lang))
    html = html.replace("{web_logs_title}", _("web_logs_title", lang))
    html = html.replace("{web_refresh}", _("web_refresh", lang))
    html = html.replace("{web_loading}", _("web_loading", lang))
    html = html.replace("{web_logs_footer}", _("web_logs_footer", lang))
    
    return web.Response(text=html, content_type='text/html')

def _get_avatar_html(user):
    raw = user.get('photo_url', '')
    if raw.startswith('http'): return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'

async def handle_api_root(request):
    return web.Response(text="VPS Bot API Server is running.")

async def start_web_server(bot_instance: Bot):
    global AGENT_FLAG
    app = web.Application()
    app['bot'] = bot_instance
    
    # Всегда активен для работы нод
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
        app.router.add_post('/logout', handle_logout)
        
        app.router.add_get('/api/node/details', handle_node_details)
        app.router.add_get('/api/agent/stats', handle_agent_stats)
        app.router.add_get('/api/nodes/list', handle_nodes_list_json)
        app.router.add_get('/api/logs', handle_get_logs)
        
        app.router.add_post('/api/settings/save', handle_save_notifications)
        app.router.add_post('/api/settings/language', handle_set_language)
        app.router.add_post('/api/users/action', handle_user_action)
        app.router.add_post('/api/nodes/add', handle_node_add)
    else:
        logging.info("Web UI is DISABLED. Only API is active.")
        app.router.add_get('/', handle_api_root)

    try:
        def fetch_flag():
            try:
                ip = requests.get("https://api.ipify.org", timeout=2).text
                return get_country_flag(ip)
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