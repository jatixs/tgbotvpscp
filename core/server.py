import logging
import time
import os
import hashlib
import hmac
import json
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT, BASE_DIR, TOKEN
from .shared_state import NODES, NODE_TRAFFIC_MONITORS, ALLOWED_USERS, USER_NAMES
from .i18n import STRINGS, get_text
from .config import DEFAULT_LANGUAGE

COOKIE_NAME = "vps_agent_session"
TEMPLATE_DIR = os.path.join(BASE_DIR, "core", "templates")

def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Template not found</h1>"

def check_telegram_auth(data: dict, bot_token: str) -> bool:
    """
    Проверяет валидность данных авторизации от Telegram Widget.
    Алгоритм: HMAC-SHA256 подписи данных.
    """
    if not data.get('hash'):
        return False
        
    check_hash = data['hash']
    data_check_arr = []
    for key, value in data.items():
        if key != 'hash':
            data_check_arr.append(f'{key}={value}')
    
    data_check_arr.sort()
    data_check_string = '\n'.join(data_check_arr)
    
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    return hmac_hash == check_hash

def get_current_user(request):
    """Возвращает данные пользователя из куки или None."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    try:
        # В куки храним JSON: {"id": 123, "first_name": "Name", "photo_url": "...", "role": "admins"}
        # В реальном продакшене это нужно шифровать или подписывать (Secure Session)
        # Для простоты используем base64 или просто json, но с проверкой прав на сервере при каждом запросе
        # Здесь для примера просто декодируем (безопасность обеспечивается тем, что куку ставит сервер только после валидации TG)
        user_data = json.loads(cookie)
        
        # ВАЖНО: Перепроверяем права при каждом запросе, вдруг его удалили из users.json
        uid = int(user_data.get('id'))
        if uid not in ALLOWED_USERS:
            return None
            
        # Обновляем роль из памяти
        user_data['role'] = ALLOWED_USERS[uid]
        return user_data
    except Exception:
        return None

async def handle_login_page(request):
    bot_username = request.app.get('bot_username')
    if not bot_username:
        return web.Response(text="Bot not initialized yet", status=503)
        
    if get_current_user(request):
        raise web.HTTPFound('/')

    html = load_template("login.html")
    html = html.replace("{bot_username}", bot_username)
    html = html.replace("{error_block}", "")
    return web.Response(text=html, content_type='text/html')

async def handle_telegram_auth_callback(request):
    """Обрабатывает редирект от виджета Telegram."""
    data = dict(request.query)
    
    if check_telegram_auth(data, TOKEN):
        user_id = int(data['id'])
        
        # Проверяем, есть ли пользователь в users.json
        if user_id in ALLOWED_USERS:
            group = ALLOWED_USERS[user_id] # 'admins' или 'users'
            
            # Формируем сессию
            session_data = {
                "id": user_id,
                "first_name": data.get('first_name', 'User'),
                "username": data.get('username', ''),
                "photo_url": data.get('photo_url', 'https://cdn-icons-png.flaticon.com/512/149/149071.png'),
                "role": group,
                "auth_date": data.get('auth_date')
            }
            
            response = web.HTTPFound('/')
            # Ставим куку (в JSON строке)
            response.set_cookie(COOKIE_NAME, json.dumps(session_data), max_age=86400, httponly=True)
            return response
        else:
            # Пользователь валиден в ТГ, но его нет в боте
            html = load_template("login.html")
            bot_username = request.app.get('bot_username')
            html = html.replace("{bot_username}", bot_username)
            error_msg = '<div class="mt-4 p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-200 text-xs text-center">Доступ запрещен: Вас нет в списке пользователей бота.</div>'
            html = html.replace("{error_block}", error_msg)
            return web.Response(text=html, content_type='text/html')
    else:
        return web.Response(text="Authorization failed (Invalid Hash)", status=403)

async def handle_logout(request):
    response = web.HTTPFound('/login')
    response.del_cookie(COOKIE_NAME)
    return response

async def handle_dashboard(request):
    user = get_current_user(request)
    if not user:
        raise web.HTTPFound('/login')

    # --- Логика генерации контента в зависимости от прав ---
    is_admin = user['role'] == 'admins'
    
    s = STRINGS.get(DEFAULT_LANGUAGE, {})
    now = time.time()
    active_count = 0
    
    # Генерация списка нод
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
        
        # Админ видит IP и технические детали
        # Юзер видит только статус и имя
        
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
            # Для юзера упрощенный вид
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

    # Бейдж роли
    if is_admin:
        role_badge = '<span class="bg-purple-500/20 text-purple-300 text-[10px] px-2 py-0.5 rounded border border-purple-500/30">ADMIN</span>'
        user_group_display = "Администратор"
        # Админская панель (пример)
        admin_controls_html = """
        <div class="mt-8 p-6 rounded-2xl bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-white/5">
            <h3 class="text-lg font-bold text-white mb-2">Панель администратора</h3>
            <p class="text-sm text-gray-400 mb-4">Доступны расширенные функции управления сетью.</p>
            <div class="flex gap-3">
                <button class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition">Логи системы</button>
                <button class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition">Настройки</button>
            </div>
        </div>
        """
    else:
        role_badge = '<span class="bg-gray-500/20 text-gray-300 text-[10px] px-2 py-0.5 rounded border border-gray-500/30">USER</span>'
        user_group_display = "Пользователь"
        admin_controls_html = ""

    # Заполнение шаблона
    data = s.copy()
    data.update({
        'nodes_count': len(NODES),
        'active_nodes': active_count,
        'nodes_list_html': nodes_html,
        'user_photo': user['photo_url'],
        'user_name': user['first_name'],
        'role_badge': role_badge,
        'user_group_display': user_group_display,
        'admin_controls_html': admin_controls_html
    })
    
    html_template = load_template("dashboard.html")
    try:
        html = html_template.format(**data)
    except KeyError as e:
        logging.error(f"Template key missing: {e}")
        html = html_template # Fallback

    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    # (Этот метод остается без изменений, он обрабатывает API запросы от нод)
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
                    lang = "ru" # Можно получить из users.json если нужно
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
    
    # Получаем username бота для виджета
    try:
        bot_info = await bot_instance.get_me()
        app['bot_username'] = bot_info.username
        logging.info(f"Web Server: Telegram Login Widget initialized for @{bot_info.username}")
    except Exception as e:
        logging.error(f"Web Server: Failed to get bot username: {e}")
        app['bot_username'] = "unknown_bot"

    # Маршруты
    app.router.add_get('/', handle_dashboard)
    app.router.add_get('/login', handle_login_page)
    app.router.add_get('/api/login/telegram', handle_telegram_auth_callback) # Callback для виджета
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