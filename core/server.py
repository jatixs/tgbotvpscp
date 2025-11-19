import logging
import time
from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT
from .shared_state import NODES
from .i18n import STRINGS
from .config import DEFAULT_LANGUAGE

# Словарь для маппинга: (token, user_id, command) -> message_id
# Чтобы редактировать старое сообщение, а не слать новое
COMMAND_MESSAGE_MAP = {}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{web_title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes float {{ 0% {{ transform: translateY(0px); }} 50% {{ transform: translateY(-20px); }} 100% {{ transform: translateY(0px); }} }}
        .animate-float {{ animation: float 6s ease-in-out infinite; }}
        .delay-2000 {{ animation-delay: 2s; }}
        .delay-4000 {{ animation-delay: 4s; }}
    </style>
</head>
<body class="bg-gray-900 flex items-center justify-center min-h-screen relative overflow-hidden text-gray-100 font-sans selection:bg-green-500/30">
    <div class="absolute top-[-10%] left-[-10%] w-96 h-96 bg-purple-600/20 rounded-full mix-blend-screen filter blur-3xl animate-float"></div>
    <div class="absolute bottom-[-10%] right-[-10%] w-96 h-96 bg-blue-600/20 rounded-full mix-blend-screen filter blur-3xl animate-float delay-2000"></div>
    <div class="relative z-10 backdrop-blur-xl bg-white/5 border border-white/10 rounded-2xl shadow-2xl ring-1 ring-white/10 p-8 max-w-lg w-full mx-4">
        <div class="flex flex-col items-center justify-center mb-8">
            <h1 class="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-green-400 to-emerald-500">{web_agent_running}</h1>
            <p class="text-gray-400 text-sm font-light tracking-wide text-center">{web_agent_active}</p>
        </div>
        <div class="grid grid-cols-2 gap-4 mb-8">
            <div class="group bg-black/20 hover:bg-black/30 transition-all duration-300 rounded-xl p-5 border border-white/5 hover:border-green-500/30">
                <div class="flex flex-col items-center">
                    <div class="text-4xl font-bold text-white mb-1">{nodes_count}</div>
                    <div class="text-[10px] uppercase tracking-widest text-gray-500 font-semibold">{web_stats_total}</div>
                </div>
            </div>
            <div class="group bg-black/20 hover:bg-black/30 transition-all duration-300 rounded-xl p-5 border border-white/5 hover:border-blue-500/30">
                <div class="flex flex-col items-center">
                    <div class="text-4xl font-bold text-white mb-1">{active_nodes}</div>
                    <div class="text-[10px] uppercase tracking-widest text-gray-500 font-semibold">{web_stats_active}</div>
                </div>
            </div>
        </div>
        <div class="border-t border-white/5 pt-6">
            <div class="flex justify-between items-center text-sm text-gray-500">
                <span class="text-gray-400">{web_footer_endpoint}</span>
                <code class="bg-black/30 px-2 py-1 rounded text-green-400/90 font-mono text-xs">POST /api/heartbeat</code>
            </div>
        </div>
    </div>
</body>
</html>
"""

async def handle_index(request):
    accept_header = request.headers.get('Accept-Language', '')
    lang = DEFAULT_LANGUAGE
    if 'ru' in accept_header.lower(): lang = 'ru'
    elif 'en' in accept_header.lower(): lang = 'en'
    
    s = STRINGS.get(lang, STRINGS.get('en', {})) 
    
    now = time.time()
    active_count = 0
    for node in NODES.values():
        if now - node.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT:
            active_count += 1

    data = s.copy()
    data.update({'nodes_count': len(NODES), 'active_nodes': active_count})
    
    try:
        html = HTML_TEMPLATE.format(**data)
    except KeyError:
        html = "<h1>Agent Running</h1>"
    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    token = data.get("token")
    stats = data.get("stats", {})
    results = data.get("results", [])

    if not token: return web.json_response({"error": "Token required"}, status=401)
    node = get_node_by_token(token)
    if not node: return web.json_response({"error": "Invalid token"}, status=403)

    has_reboot_confirmation = any(r.get("command") == "reboot" for r in results)
    if node.get("is_restarting") and not has_reboot_confirmation:
        node["is_restarting"] = False

    peername = request.transport.get_extra_info('peername')
    ip = peername[0] if peername else "Unknown"
    update_node_heartbeat(token, ip, stats)
    
    # --- Обработка результатов ---
    bot: Bot = request.app.get('bot') 
    if bot and results:
        for res in results:
            user_id = res.get("user_id")
            text = res.get("result")
            cmd = res.get("command")
            is_final = res.get("is_final", False)
            
            if user_id and text:
                node_name = node.get("name", "Node")
                full_text = f"🖥 <b>Ответ от {node_name}:</b>\n\n{text}"
                
                # Ключ для поиска предыдущего сообщения
                map_key = (token, user_id, cmd)
                prev_msg_id = COMMAND_MESSAGE_MAP.get(map_key)
                
                message_sent = False
                
                if prev_msg_id:
                    try:
                        await bot.edit_message_text(
                            text=full_text,
                            chat_id=user_id,
                            message_id=prev_msg_id,
                            parse_mode="HTML"
                        )
                        message_sent = True
                    except TelegramBadRequest as e:
                        if "message is not modified" in str(e):
                            message_sent = True # Считаем, что успех
                        elif "message to edit not found" in str(e):
                            # Сообщение удалено, надо слать новое
                            prev_msg_id = None
                        else:
                            logging.error(f"Edit error: {e}")
                
                if not message_sent:
                    try:
                        sent_msg = await bot.send_message(chat_id=user_id, text=full_text, parse_mode="HTML")
                        COMMAND_MESSAGE_MAP[map_key] = sent_msg.message_id
                    except Exception as e:
                        logging.error(f"Send error: {e}")
                
                # Если результат финальный, удаляем из мапы, чтобы следующая такая же команда слала новое сообщение
                if is_final:
                    COMMAND_MESSAGE_MAP.pop(map_key, None)

    tasks = node.get("tasks", [])
    response_data = {"status": "ok", "tasks": tasks}
    if tasks: node["tasks"] = []

    return web.json_response(response_data)

async def start_web_server(bot_instance: Bot):
    app = web.Application()
    app['bot'] = bot_instance
    app.router.add_get('/', handle_index)
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