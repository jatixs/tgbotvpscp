import logging
import time
import os
import json
import secrets
import hashlib
import asyncio
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR
from .shared_state import NODES, NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES, AUTH_TOKENS
from .i18n import STRINGS
from .config import DEFAULT_LANGUAGE

# --- КОНФИГУРАЦИЯ ---
COOKIE_NAME = "vps_agent_session"
LOGIN_TOKEN_TTL = 300 
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "core", "static")

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

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ОТПРАВКИ (Async Fire-and-Forget) ---
async def process_node_result_background(bot, user_id, cmd, text, token, node_name):
    """Отправляет сообщение пользователю в фоне, чтобы не задерживать ответ ноде."""
    if not user_id or not text: return
    try:
        # Логика для Трафика (обновление сообщения)
        if cmd == "traffic" and user_id in NODE_TRAFFIC_MONITORS:
            monitor = NODE_TRAFFIC_MONITORS[user_id]
            if monitor.get("token") == token:
                msg_id = monitor.get("message_id")
                stop_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏹ Stop", callback_data=f"node_stop_traffic_{token}")]
                ])
                try:
                    await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=stop_kb, parse_mode="HTML")
                except Exception: pass # Игнорируем ошибки редактирования (не изменилось и т.д.)
                return

        # Логика для остальных команд (новое сообщение)
        full_text = f"🖥 <b>Ответ от {node_name}:</b>\n\n{text}"
        await bot.send_message(chat_id=user_id, text=full_text, parse_mode="HTML")
    
    except Exception as e:
        logging.error(f"Background message send error (User: {user_id}): {e}")

# --- ROUTES ---

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
        html = load_template("login.html")
        html = html.replace("{error_block}", '<div class="p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-200 text-xs text-center mt-4">Ошибка: ID не найден</div>')
        html = html.replace('id="password-form" class="hidden"', 'id="password-form" class="hidden"')
        html = html.replace('id="magic-form"', 'id="magic-form"')
        return web.Response(text=html, content_type='text/html')
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
        session = {"id": 0, "first_name": "Admin", "role": "admins", "type": "password"}
        resp = web.HTTPFound('/')
        resp.set_cookie(COOKIE_NAME, json.dumps(session), max_age=604800)
        return resp
    html = load_template("login.html")
    html = html.replace("{error_block}", '<div class="p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-200 text-xs text-center mt-4">Неверный пароль</div>')
    html = html.replace('id="password-form" class="hidden"', 'id="password-form"')
    html = html.replace('id="magic-form"', 'id="magic-form" class="hidden"')
    return web.Response(text=html, content_type='text/html')

async def handle_magic_login(request):
    token = request.query.get("token")
    if not token or token not in AUTH_TOKENS: return web.Response(text="Link expired", status=403)
    td = AUTH_TOKENS.pop(token)
    if time.time() - td["created_at"] > LOGIN_TOKEN_TTL: return web.Response(text="Expired", status=403)
    uid = td["user_id"]
    if uid not in ALLOWED_USERS: return web.Response(text="Denied", status=403)
    session = {"id": uid, "first_name": USER_NAMES.get(str(uid), f"ID:{uid}"), "role": ALLOWED_USERS[uid], "type": "telegram"}
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
    return web.json_response({"name": node.get("name"), "ip": node.get("ip"), "stats": node.get("stats"), "history": node.get("history", [])})

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user: raise web.HTTPFound('/login')
    is_admin = user['role'] == 'admins'
    s = STRINGS.get(DEFAULT_LANGUAGE, {})
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
        cursor = "cursor-pointer hover:scale-[1.01]"
        details_block = ""
        if is_admin:
            stats = node.get("stats", {})
            details_block = f"""<div class="mt-3 pt-3 border-t border-white/5 grid grid-cols-3 gap-2 text-xs text-gray-400"><div class="text-center"><span class="block text-white font-bold">{stats.get('cpu',0)}%</span>CPU</div><div class="text-center"><span class="block text-white font-bold">{stats.get('ram',0)}%</span>RAM</div><div class="text-center"><span class="block text-white font-bold truncate">{node.get('ip','N/A')}</span>IP</div></div>"""
        else: details_block = '<div class="mt-3 pt-3 border-t border-white/5 text-xs text-gray-500 text-center">Детали скрыты</div>'
        nodes_html += f"""<div class="bg-black/20 hover:bg-black/30 transition rounded-xl p-4 border border-white/5 {cursor}" onclick="openNodeDetails('{token}')"><div class="flex justify-between items-start"><div><div class="font-bold text-gray-200">{node.get('name','Unknown')}</div><div class="text-[10px] font-mono text-gray-500 mt-1">{token[:8]}...</div></div><div class="px-2 py-1 rounded text-[10px] font-bold {status_color} {bg_class}">{status_text}</div></div>{details_block}</div>"""
    
    admin_controls = ""
    if is_admin:
        admin_controls = """<div class="mt-8 p-6 rounded-2xl bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-white/5"><h3 class="text-lg font-bold text-white mb-2">Панель администратора</h3><p class="text-sm text-gray-400 mb-4">Доступны расширенные функции.</p><div class="flex gap-3"><button class="px-4 py-2 bg-white/10 rounded-lg text-sm text-gray-400 cursor-not-allowed" disabled>Логи</button></div></div>"""
    
    # --- ИСПРАВЛЕНИЕ: Используем .replace вместо .format ---
    data = s.copy()
    data.update({'nodes_count': len(NODES), 'active_nodes': active_count, 'nodes_list_html': nodes_html, 'user_photo': user.get('photo_url'), 'user_name': user.get('first_name'), 'role_badge': '<span class="bg-green-500/20 text-green-400 text-[10px] px-2 py-0.5 rounded border border-green-500/30">ADMIN</span>' if is_admin else '<span class="bg-gray-500/20 text-gray-300 text-[10px] px-2 py-0.5 rounded border border-gray-500/30">USER</span>', 'user_group_display': 'Администратор' if is_admin else 'Пользователь', 'admin_controls_html': admin_controls})
    
    html = load_template("dashboard.html")
    for k, v in data.items(): 
        html = html.replace(f"{{{k}}}", str(v))
    
    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    try: data = await request.json()
    except: return web.json_response({"error": "Invalid JSON"}, status=400)
    token = data.get("token")
    if not token or not get_node_by_token(token): return web.json_response({"error": "Auth fail"}, status=401)
    node = get_node_by_token(token)
    
    stats = data.get("stats", {})
    results = data.get("results", [])
    bot = request.app.get('bot')

    # Обработка результатов (в фоне!)
    if bot and results:
        for res in results:
            user_id = res.get("user_id")
            text = res.get("result")
            cmd = res.get("command")
            # Запускаем отправку в фоне, чтобы не блочить ответ ноде
            asyncio.create_task(process_node_result_background(bot, user_id, cmd, text, token, node.get("name", "Node")))

    node["is_restarting"] = False 
    update_node_heartbeat(token, request.transport.get_extra_info('peername')[0], stats)
    return web.json_response({"status": "ok", "tasks": node.get("tasks", [])})

async def start_web_server(bot_instance: Bot):
    app = web.Application()
    app['bot'] = bot_instance
    
    if os.path.exists(STATIC_DIR):
        app.router.add_static('/static', STATIC_DIR)
    else:
        logging.warning(f"Static dir not found: {STATIC_DIR}")

    app.router.add_get('/', handle_dashboard)
    app.router.add_get('/login', handle_login_page)
    app.router.add_post('/api/login/request', handle_login_request)
    app.router.add_get('/api/login/magic', handle_magic_login)
    app.router.add_post('/api/login/password', handle_login_password)
    app.router.add_post('/logout', handle_logout)
    app.router.add_post('/api/heartbeat', handle_heartbeat)
    app.router.add_get('/api/node/details', handle_node_details)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    try:
        await site.start()
        logging.info(f"Agent Web Server started on {WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        return runner
    except Exception as e:
        logging.error(f"Failed to start Web Server: {e}")
        return None