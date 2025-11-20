import logging
import time
import os
import json
import secrets
import hashlib
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR
from .shared_state import NODES, NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES, AUTH_TOKENS
from .i18n import STRINGS
from .config import DEFAULT_LANGUAGE

# --- КОНФИГУРАЦИЯ ---
COOKIE_NAME = "vps_agent_session"
LOGIN_TOKEN_TTL = 300 
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin") # Пароль для входа
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")

def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Template not found</h1>"

def get_current_user(request):
    """Возвращает данные пользователя из куки или None."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    try:
        user_data = json.loads(cookie)
        
        # 1. Если это вход по паролю (Админ)
        if user_data.get('type') == 'password':
            return user_data
            
        # 2. Если это вход через Telegram (Magic Link) - проверяем права
        uid = int(user_data.get('id'))
        if uid not in ALLOWED_USERS:
            return None
            
        user_data['role'] = ALLOWED_USERS[uid]
        return user_data
    except Exception:
        return None

# --- ROUTES ---

async def handle_login_page(request):
    """Отображает страницу входа."""
    if get_current_user(request):
        raise web.HTTPFound('/')

    html = load_template("login.html")
    html = html.replace("{error_block}", "")
    return web.Response(text=html, content_type='text/html')

async def handle_login_request(request):
    """Обрабатывает запрос Magic Link (Telegram ID)."""
    data = await request.post()
    try:
        user_id = int(data.get("user_id", 0))
    except ValueError:
        user_id = 0

    # Проверяем права
    if user_id not in ALLOWED_USERS:
        html = load_template("login.html")
        error_msg = '<div class="p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-200 text-xs text-center mt-4">Ошибка: ID не найден в списке пользователей бота.</div>'
        html = html.replace("{error_block}", error_msg)
        html = html.replace('id="password-form" class="hidden"', 'id="password-form" class="hidden"') # Сохраняем состояние форм
        html = html.replace('id="magic-form"', 'id="magic-form"')
        return web.Response(text=html, content_type='text/html')

    # Генерируем токен
    token = secrets.token_urlsafe(32)
    AUTH_TOKENS[token] = {
        "user_id": user_id,
        "created_at": time.time()
    }

    # Формируем ссылку
    host = request.headers.get('Host', f'{WEB_SERVER_HOST}:{WEB_SERVER_PORT}')
    protocol = "https" if request.headers.get('X-Forwarded-Proto') == "https" else "http"
    magic_link = f"{protocol}://{host}/api/login/magic?token={token}"

    # Отправляем в Telegram
    bot: Bot = request.app.get('bot')
    if bot:
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Войти в панель", url=magic_link)]
            ])
            await bot.send_message(
                chat_id=user_id,
                text="<b>🔐 Запрос на вход в Web-панель</b>\n\nНажмите кнопку ниже для авторизации. Ссылка активна 5 минут.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            logging.info(f"Magic link sent to user {user_id}")
            return web.HTTPFound('/login?sent=true')
        except Exception as e:
            logging.error(f"Failed to send magic link to {user_id}: {e}")
            html = load_template("login.html")
            error_msg = f'<div class="p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-200 text-xs text-center mt-4">Не удалось отправить сообщение. Запустите бота командой /start.</div>'
            html = html.replace("{error_block}", error_msg)
            return web.Response(text=html, content_type='text/html')
    else:
        return web.Response(text="Bot instance not found", status=500)

async def handle_login_password(request):
    """Обрабатывает вход по паролю."""
    data = await request.post()
    password = data.get("password")

    if password == WEB_PASSWORD:
        # Создаем сессию "Супер-Админа"
        session_data = {
            "id": 0,
            "first_name": "Administrator",
            "username": "admin",
            "photo_url": "https://cdn-icons-png.flaticon.com/512/2942/2942813.png",
            "role": "admins",
            "auth_date": time.time(),
            "type": "password"
        }
        response = web.HTTPFound('/')
        response.set_cookie(COOKIE_NAME, json.dumps(session_data), max_age=86400*7, httponly=True)
        return response
    else:
        html = load_template("login.html")
        error_msg = '<div class="p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-200 text-xs text-center mt-4">Неверный пароль</div>'
        html = html.replace("{error_block}", error_msg)
        # Хак: подменяем классы, чтобы при ошибке сразу показать форму пароля
        html = html.replace('id="password-form" class="hidden"', 'id="password-form"')
        html = html.replace('id="magic-form"', 'id="magic-form" class="hidden"')
        return web.Response(text=html, content_type='text/html')

async def handle_magic_login(request):
    """Обрабатывает переход по ссылке из Telegram."""
    token = request.query.get("token")
    if not token or token not in AUTH_TOKENS:
        return web.Response(text="Invalid or expired login link", status=403)
    
    token_data = AUTH_TOKENS.pop(token)
    if time.time() - token_data["created_at"] > LOGIN_TOKEN_TTL:
        return web.Response(text="Login link expired", status=403)
        
    user_id = token_data["user_id"]
    if user_id not in ALLOWED_USERS:
        return web.Response(text="Access denied", status=403)

    user_name = USER_NAMES.get(str(user_id), f"ID: {user_id}")
    role = ALLOWED_USERS[user_id]
    
    session_data = {
        "id": user_id,
        "first_name": user_name,
        "photo_url": "https://cdn-icons-png.flaticon.com/512/149/149071.png",
        "role": role,
        "auth_date": time.time(),
        "type": "telegram"
    }
    
    response = web.HTTPFound('/')
    response.set_cookie(COOKIE_NAME, json.dumps(session_data), max_age=86400*30, httponly=True)
    return response

async def handle_logout(request):
    response = web.HTTPFound('/login')
    response.del_cookie(COOKIE_NAME)
    return response

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user:
        raise web.HTTPFound('/login')

    is_admin = user['role'] == 'admins'
    s = STRINGS.get(DEFAULT_LANGUAGE, {})
    now = time.time()
    active_count = 0
    
    nodes_html = ""
    if not NODES:
        nodes_html = '<div class="col-span-full text-center text-gray-500 py-10">Нет подключенных нод</div>'
    
    for token, node in NODES.items():
        last_seen = node.get("last_seen", 0)
        is_online = (now - last_seen < NODE_OFFLINE_TIMEOUT)
        if is_online: active_count += 1
        
        status_color = "text-green-400" if is_online else "text-red-400"
        status_text = "ONLINE" if is_online else "OFFLINE"
        bg_class = "bg-green-500/10 border-green-500/30" if is_online else "bg-red-500/10 border-red-500/30"
        
        details_block = ""
        if is_admin:
            stats = node.get("stats", {})
            ip = node.get("ip", "N/A")
            cpu = stats.get("cpu", 0)
            ram = stats.get("ram", 0)
            details_block = f"""
            <div class="mt-3 pt-3 border-t border-white/5 grid grid-cols-3 gap-2 text-xs text-gray-400">
                <div class="text-center"><span class="block text-white font-bold">{cpu}%</span>CPU</div>
                <div class="text-center"><span class="block text-white font-bold">{ram}%</span>RAM</div>
                <div class="text-center"><span class="block text-white font-bold truncate">{ip}</span>IP</div>
            </div>
            """
        else:
            details_block = '<div class="mt-3 pt-3 border-t border-white/5 text-xs text-gray-500 text-center">Детали скрыты</div>'

        nodes_html += f"""
        <div class="bg-black/20 hover:bg-black/30 transition rounded-xl p-4 border border-white/5">
            <div class="flex justify-between items-start">
                <div>
                    <div class="font-bold text-gray-200">{node.get('name', 'Unknown')}</div>
                    <div class="text-[10px] font-mono text-gray-500 mt-1">{token[:8]}...</div>
                </div>
                <div class="px-2 py-1 rounded text-[10px] font-bold {status_color} {bg_class}">
                    {status_text}
                </div>
            </div>
            {details_block}
        </div>
        """

    if is_admin:
        role_badge = '<span class="bg-purple-500/20 text-purple-300 text-[10px] px-2 py-0.5 rounded border border-purple-500/30">ADMIN</span>'
        user_group_display = "Администратор"
        admin_controls_html = """
        <div class="mt-8 p-6 rounded-2xl bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-white/5">
            <h3 class="text-lg font-bold text-white mb-2">Панель администратора</h3>
            <p class="text-sm text-gray-400 mb-4">Доступны расширенные функции управления сетью.</p>
            <div class="flex gap-3">
                <button class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition text-gray-400 cursor-not-allowed" disabled>Логи</button>
                <button class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition text-gray-400 cursor-not-allowed" disabled>Настройки</button>
            </div>
        </div>
        """
    else:
        role_badge = '<span class="bg-gray-500/20 text-gray-300 text-[10px] px-2 py-0.5 rounded border border-gray-500/30">USER</span>'
        user_group_display = "Пользователь"
        admin_controls_html = ""

    data = s.copy()
    data.update({
        'nodes_count': len(NODES),
        'active_nodes': active_count,
        'nodes_list_html': nodes_html,
        'user_photo': user.get('photo_url'),
        'user_name': user.get('first_name'),
        'role_badge': role_badge,
        'user_group_display': user_group_display,
        'admin_controls_html': admin_controls_html,
        'web_title': s.get('web_title', 'VPS Bot'),
        'web_agent_running': s.get('web_agent_running', 'Agent'),
        'web_agent_active': s.get('web_agent_active', 'Active'),
        'web_footer_endpoint': s.get('web_footer_endpoint', 'Endpoint'),
        'web_footer_powered': s.get('web_footer_powered', 'Powered'),
        'web_stats_total': s.get('web_stats_total', 'Total'),
        'web_stats_active': s.get('web_stats_active', 'Active')
    })
    
    html_template = load_template("dashboard.html")
    try:
        html = html_template.format(**data)
    except KeyError as e:
        logging.error(f"Template key missing: {e}")
        html = html_template.replace("{", "{{").replace("}", "}}")

    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    token = data.get("token")
    stats = data.get("stats", {})
    results = data.get("results", [])

    if not token:
        return web.json_response({"error": "Token required"}, status=401)

    node = get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Invalid token"}, status=403)

    has_reboot_confirmation = False
    for r in results:
        if r.get("command") == "reboot":
            has_reboot_confirmation = True
            break
            
    if node.get("is_restarting") and not has_reboot_confirmation:
        node["is_restarting"] = False

    peername = request.transport.get_extra_info('peername')
    ip = peername[0] if peername else "Unknown"

    update_node_heartbeat(token, ip, stats)
    
    bot: Bot = request.app.get('bot') 
    if bot and results:
        for res in results:
            user_id = res.get("user_id")
            text = res.get("result")
            cmd = res.get("command")
            
            if user_id and text:
                try:
                    lang = "ru"
                    if cmd == "traffic" and user_id in NODE_TRAFFIC_MONITORS:
                        monitor = NODE_TRAFFIC_MONITORS[user_id]
                        if monitor.get("token") == token:
                            msg_id = monitor.get("message_id")
                            stop_kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="⏹ Stop", callback_data=f"node_stop_traffic_{token}")]
                            ])
                            try:
                                await bot.edit_message_text(text=text, chat_id=user_id, message_id=msg_id, reply_markup=stop_kb, parse_mode="HTML")
                            except TelegramBadRequest: pass
                            continue

                    node_name = node.get("name", "Node")
                    full_text = f"🖥 <b>Ответ от {node_name}:</b>\n\n{text}"
                    await bot.send_message(chat_id=user_id, text=full_text, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Error sending msg: {e}")

    tasks = node.get("tasks", [])
    response_data = {"status": "ok", "tasks": tasks}
    if tasks: node["tasks"] = []

    return web.json_response(response_data)

async def start_web_server(bot_instance: Bot):
    app = web.Application()
    app['bot'] = bot_instance
    
    # Маршруты
    app.router.add_get('/', handle_dashboard)
    app.router.add_get('/login', handle_login_page)
    app.router.add_post('/api/login/request', handle_login_request)
    app.router.add_get('/api/login/magic', handle_magic_login)
    app.router.add_post('/api/login/password', handle_login_password) # NEW
    app.router.add_post('/logout', handle_logout)
    app.router.add_post('/api/heartbeat', handle_heartbeat)

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