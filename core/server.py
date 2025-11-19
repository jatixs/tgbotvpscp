import logging
import time
from aiohttp import web
from aiogram import Bot
from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT
from .shared_state import NODES
from .i18n import STRINGS
from .config import DEFAULT_LANGUAGE

# HTML-шаблон с экранированием CSS скобок и плейсхолдерами для локализации
# Используем Tailwind CDN для стилизации
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{web_title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes float {{
            0% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-20px); }}
            100% {{ transform: translateY(0px); }}
        }}
        .animate-float {{
            animation: float 6s ease-in-out infinite;
        }}
        .delay-2000 {{ animation-delay: 2s; }}
        .delay-4000 {{ animation-delay: 4s; }}
    </style>
</head>
<body class="bg-gray-900 flex items-center justify-center min-h-screen relative overflow-hidden text-gray-100 font-sans selection:bg-green-500/30">
    
    <div class="absolute top-[-10%] left-[-10%] w-96 h-96 bg-purple-600/20 rounded-full mix-blend-screen filter blur-3xl animate-float"></div>
    <div class="absolute bottom-[-10%] right-[-10%] w-96 h-96 bg-blue-600/20 rounded-full mix-blend-screen filter blur-3xl animate-float delay-2000"></div>
    <div class="absolute top-[20%] right-[30%] w-72 h-72 bg-green-600/10 rounded-full mix-blend-screen filter blur-3xl animate-float delay-4000"></div>

    <div class="relative z-10 backdrop-blur-xl bg-white/5 border border-white/10 rounded-2xl shadow-2xl ring-1 ring-white/10 p-8 max-w-lg w-full mx-4">
        
        <div class="flex flex-col items-center justify-center mb-8">
            <div class="flex items-center space-x-3 mb-2">
                <span class="relative flex h-3 w-3">
                  <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span class="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
                </span>
                <h1 class="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-green-400 to-emerald-500">
                    {web_agent_running}
                </h1>
            </div>
            <p class="text-gray-400 text-sm font-light tracking-wide text-center">{web_agent_active}</p>
        </div>
        
        <div class="grid grid-cols-2 gap-4 mb-8">
            <div class="group bg-black/20 hover:bg-black/30 transition-all duration-300 rounded-xl p-5 border border-white/5 hover:border-green-500/30">
                <div class="flex flex-col items-center">
                    <div class="text-4xl font-bold text-white mb-1 group-hover:scale-110 transition-transform duration-300 group-hover:text-green-400">{nodes_count}</div>
                    <div class="text-[10px] uppercase tracking-widest text-gray-500 font-semibold">{web_stats_total}</div>
                </div>
            </div>
            
            <div class="group bg-black/20 hover:bg-black/30 transition-all duration-300 rounded-xl p-5 border border-white/5 hover:border-blue-500/30">
                <div class="flex flex-col items-center">
                    <div class="text-4xl font-bold text-white mb-1 group-hover:scale-110 transition-transform duration-300 group-hover:text-blue-400">{active_nodes}</div>
                    <div class="text-[10px] uppercase tracking-widest text-gray-500 font-semibold">{web_stats_active}</div>
                </div>
            </div>
        </div>

        <div class="border-t border-white/5 pt-6">
            <div class="flex flex-col space-y-3 text-sm text-gray-500">
                <div class="flex justify-between items-center">
                    <span class="text-gray-400">{web_footer_endpoint}</span>
                    <code class="bg-black/30 px-2 py-1 rounded text-green-400/90 font-mono text-xs tracking-tight shadow-inner">POST /api/heartbeat</code>
                </div>
                <div class="flex justify-between items-center">
                    <span class="text-gray-400">{web_footer_powered}</span>
                    <a href="https://github.com/jatixs/tgbotvpscp" target="_blank" class="text-blue-400/80 hover:text-blue-300 transition-colors text-xs font-medium hover:underline decoration-blue-400/30 underline-offset-4">
                        VPS Manager Bot
                    </a>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

async def handle_index(request):
    """Отдает HTML страницу со статусом (локализованную)."""
    
    # 1. Определение языка из заголовка Accept-Language
    accept_header = request.headers.get('Accept-Language', '')
    lang = DEFAULT_LANGUAGE
    if 'ru' in accept_header.lower():
        lang = 'ru'
    elif 'en' in accept_header.lower():
        lang = 'en'
    
    # 2. Получение строк для выбранного языка
    s = STRINGS.get(lang, STRINGS.get('en', {})) 
    
    # 3. Расчет статистики
    now = time.time()
    active_count = 0
    for node in NODES.values():
        if now - node.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT:
            active_count += 1

    # 4. Подготовка данных для шаблона
    data = s.copy()
    data.update({
        'nodes_count': len(NODES),
        'active_nodes': active_count
    })
    
    # 5. Рендеринг
    try:
        html = HTML_TEMPLATE.format(**data)
    except KeyError as e:
        logging.error(f"Template rendering error (missing key): {e}")
        html = f"<h1>Agent Running</h1><p>Nodes: {len(NODES)}</p>"

    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    """Принимает данные от ноды и отправляет результаты команд пользователю."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    token = data.get("token")
    stats = data.get("stats", {})
    results = data.get("results", []) # Получаем ответы на команды

    if not token:
        return web.json_response({"error": "Token required"}, status=401)

    node = get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Invalid token"}, status=403)

    if node.get("is_restarting"):
        node["is_restarting"] = False

    peername = request.transport.get_extra_info('peername')
    ip = peername[0] if peername else "Unknown"

    update_node_heartbeat(token, ip, stats)
    
    # --- ОБРАБОТКА РЕЗУЛЬТАТОВ ОТ НОДЫ ---
    # Берем инстанс бота из app, куда мы его положили в start_web_server
    bot: Bot = request.app.get('bot') 
    if bot and results:
        for res in results:
            user_id = res.get("user_id")
            text = res.get("result")
            cmd = res.get("command")
            
            if user_id and text:
                try:
                    node_name = node.get("name", "Node")
                    # Формируем сообщение ответа для админа
                    full_text = f"🖥 <b>Ответ от {node_name}:</b>\n\n{text}"
                    await bot.send_message(chat_id=user_id, text=full_text, parse_mode="HTML")
                    logging.info(f"Отправлен ответ команды '{cmd}' пользователю {user_id}")
                except Exception as e:
                    logging.error(f"Не удалось отправить ответ пользователю {user_id}: {e}")
    # -------------------------------------

    tasks = node.get("tasks", [])
    response_data = {"status": "ok"}
    
    if tasks:
        response_data["tasks"] = tasks
        node["tasks"] = [] 

    return web.json_response(response_data)

async def start_web_server(bot_instance: Bot):
    """Запускает веб-сервер и сохраняет ссылку на бота для отправки уведомлений."""
    app = web.Application()
    app['bot'] = bot_instance # Сохраняем бота в контексте приложения
    
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