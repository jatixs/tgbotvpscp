import logging
import time
import os
import json
import secrets
import asyncio
import requests
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Импорты
from .nodes_db import get_node_by_token, update_node_heartbeat, create_node, delete_node
# --- ИЗМЕНЕНО: Добавлен ADMIN_USER_ID в импорт ---
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR, ADMIN_USER_ID
# -------------------------------------------------
from .shared_state import NODES, NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES, AUTH_TOKENS, ALERTS_CONFIG
from .i18n import STRINGS, get_user_lang, set_user_lang
from .config import DEFAULT_LANGUAGE
from .utils import get_country_flag, save_alerts_config
from .auth import save_users, get_user_name

# --- КОНФИГУРАЦИЯ ---
COOKIE_NAME = "vps_agent_session"
LOGIN_TOKEN_TTL = 300 
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "core", "static")

AGENT_FLAG = "🏳️"

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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
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

# --- API ROUTES ---

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

# --- НОВЫЕ ROUTE ДЛЯ НАСТРОЕК ---

async def handle_settings_page(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    
    # Загружаем шаблон
    html = load_template("settings.html")
    
    # Данные пользователя
    user_id = user['id']
    is_admin = user['role'] == 'admins'
    
    # Настройки уведомлений
    user_alerts = ALERTS_CONFIG.get(user_id, {})
    
    # Список пользователей (только для админа)
    users_json = "null" # Инициализируем как null, чтобы JS знал, что это не админ
    if is_admin:
        users_list = []
        for uid, role in ALLOWED_USERS.items():
            # --- ИЗМЕНЕНО: Скрываем Главного Админа (Создателя) ---
            if uid == ADMIN_USER_ID:
                continue
            # ------------------------------------------------------
            name = USER_NAMES.get(str(uid), f"ID: {uid}")
            users_list.append({"id": uid, "name": name, "role": role})
        users_json = json.dumps(users_list)

    # Заменяем плейсхолдеры
    html = html.replace("{web_title}", "Настройки - VPS Bot")
    html = html.replace("{user_name}", user.get('first_name', 'User'))
    html = html.replace("{user_avatar}", _get_avatar_html(user))
    html = html.replace("{users_data_json}", users_json)
    
    # Чекбоксы уведомлений
    for alert in ['resources', 'logins', 'bans', 'downtime']:
        checked = "checked" if user_alerts.get(alert, False) else ""
        html = html.replace(f"{{check_{alert}}}", checked)

    return web.Response(text=html, content_type='text/html')

async def handle_save_notifications(request):
    user = get_current_user(request)
    if not user: return web.json_response({"error": "Auth required"}, status=401)
    
    try:
        data = await request.json()
        user_id = user['id']
        
        if user_id not in ALERTS_CONFIG: ALERTS_CONFIG[user_id] = {}
        
        # Обновляем настройки
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
        
        # --- ДОП. ЗАЩИТА: Нельзя удалить главного админа через API ---
        if target_id == ADMIN_USER_ID:
            return web.json_response({"error": "Cannot affect Main Admin"}, status=400)
        # -------------------------------------------------------------

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
            # Пытаемся получить имя через бота
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
        # Генерируем команду для установки
        host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
        proto = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
        cmd = f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh) # Select 8, Url: {proto}://{host}, Token: {token}"
        
        return web.json_response({"status": "ok", "token": token, "command": cmd})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# --- СТАНДАРТНЫЕ ROUTE (Login, Dashboard) ---

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

async def handle_node_details(request):
    if not get_current_user(request): return web.json_response({"error": "Unauthorized"}, status=401)
    token = request.query.get("token")
    if not token or token not in NODES: return web.json_response({"error": "Node not found"}, status=404)
    node = NODES[token]
    return web.json_response({"name": node.get("name"), "ip": node.get("ip"), "stats": node.get("stats"), "history": node.get("history", []), "token": token})

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    is_admin = user['role'] == 'admins'
    
    now = time.time()
    active_count = 0
    nodes_html = ""
    if not NODES: nodes_html = '<div class="col-span-full text-center text-gray-500 py-10">Нет подключенных нод</div>'
    
    for token, node in NODES.items():
        last_seen = node.get("last_seen", 0)
        is_online = (now - last_seen < NODE_OFFLINE_TIMEOUT)
        if is_online: active_count += 1
        status_color = "text-green-400" if is_online else "text-red-400"
        status_text = "ONLINE" if is_online else "OFFLINE"
        bg_class = "bg-green-500/10 border-green-500/30" if is_online else "bg-red-500/10 border-red-500/30"
        
        stats = node.get("stats", {})
        details_block = ""
        if is_admin:
            details_block = f"""
            <div class="mt-4 pt-4 border-t border-white/5 grid grid-cols-3 gap-2">
                <div class="bg-white/5 rounded-lg p-2 text-center border border-white/5">
                    <div class="text-[10px] text-gray-400 uppercase font-bold">CPU</div>
                    <div class="text-sm font-bold text-white">{stats.get('cpu', 0)}%</div>
                </div>
                <div class="bg-white/5 rounded-lg p-2 text-center border border-white/5">
                    <div class="text-[10px] text-gray-400 uppercase font-bold">RAM</div>
                    <div class="text-sm font-bold text-white">{stats.get('ram', 0)}%</div>
                </div>
                <div class="bg-white/5 rounded-lg p-2 text-center border border-white/5">
                    <div class="text-[10px] text-gray-400 uppercase font-bold">IP</div>
                    <div class="text-xs font-bold text-white truncate" title="{node.get('ip', 'N/A')}">{node.get('ip', 'N/A')}</div>
                </div>
            </div>"""
        else:
            details_block = '<div class="mt-3 pt-3 border-t border-white/5 text-xs text-gray-500 text-center">Детали скрыты</div>'
            
        nodes_html += f"""<div class="bg-black/20 hover:bg-black/30 transition rounded-xl p-4 border border-white/5 cursor-pointer hover:scale-[1.01]" onclick="openNodeDetails('{token}')"><div class="flex justify-between items-start"><div><div class="font-bold text-gray-200">{node.get('name','Unknown')}</div><div class="text-[10px] font-mono text-gray-500 mt-1">{token[:8]}...</div></div><div class="px-2 py-1 rounded text-[10px] font-bold {status_color} {bg_class}">{status_text}</div></div>{details_block}</div>"""

    role_badge = '<span class="bg-green-500/20 text-green-400 text-[10px] px-2 py-0.5 rounded border border-green-500/30">ADMIN</span>' if is_admin else '<span class="bg-gray-500/20 text-gray-300 text-[10px] px-2 py-0.5 rounded border border-gray-500/30">USER</span>'
    
    admin_controls = ""
    if is_admin:
        admin_controls = """
        <div class="mt-8 p-6 rounded-2xl bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-white/5">
            <h3 class="text-lg font-bold text-white mb-2">Панель администратора</h3>
            <p class="text-sm text-gray-400 mb-4">Доступны расширенные функции управления сетью.</p>
            <div class="flex gap-3">
                <button onclick="openLogsModal()" class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-white transition flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                    Логи системы
                </button>
                <a href="/settings" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm text-white transition flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                    Настройки
                </a>
            </div>
        </div>
        """

    html = load_template("dashboard.html")
    html = html.replace("{web_title}", "VPS Bot Dashboard")
    html = html.replace("{web_agent_running}", "Agent Active")
    html = html.replace("{user_avatar}", _get_avatar_html(user))
    html = html.replace("{user_name}", user.get('first_name', 'User'))
    html = html.replace("{role_badge}", role_badge)
    html = html.replace("{nodes_count}", str(len(NODES)))
    html = html.replace("{active_nodes}", str(active_count))
    html = html.replace("{user_group_display}", "Администратор" if is_admin else "Пользователь")
    html = html.replace("{nodes_list_html}", nodes_html)
    html = html.replace("{admin_controls_html}", admin_controls)
    
    return web.Response(text=html, content_type='text/html')

def _get_avatar_html(user):
    raw = user.get('photo_url', '')
    if raw.startswith('http'): return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'

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

async def start_web_server(bot_instance: Bot):
    global AGENT_FLAG
    app = web.Application()
    app['bot'] = bot_instance
    if os.path.exists(STATIC_DIR): app.router.add_static('/static', STATIC_DIR)
    
    app.router.add_get('/', handle_dashboard)
    app.router.add_get('/settings', handle_settings_page) # New page
    app.router.add_get('/login', handle_login_page)
    app.router.add_post('/api/login/request', handle_login_request)
    app.router.add_get('/api/login/magic', handle_magic_login)
    app.router.add_post('/api/login/password', handle_login_password)
    app.router.add_post('/logout', handle_logout)
    
    # API
    app.router.add_post('/api/heartbeat', handle_heartbeat)
    app.router.add_get('/api/node/details', handle_node_details)
    app.router.add_get('/api/logs', handle_get_logs)
    app.router.add_post('/api/settings/save', handle_save_notifications)
    app.router.add_post('/api/users/action', handle_user_action)
    app.router.add_post('/api/nodes/add', handle_node_add)

    try:
        def fetch_flag():
            try:
                ip = requests.get("https://api.ipify.org", timeout=2).text
                return get_country_flag(ip)
            except: return "🏳️"
        AGENT_FLAG = await asyncio.to_thread(fetch_flag)
    except: pass

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    try:
        await site.start()
        logging.info(f"Web Server started on {WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        return runner
    except Exception as e:
        logging.error(f"Failed to start Web Server: {e}")
        return None