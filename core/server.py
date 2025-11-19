import logging
import time
from aiohttp import web
from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT, NODE_OFFLINE_TIMEOUT
from .shared_state import NODES
from .i18n import STRINGS
from .config import DEFAULT_LANGUAGE

# HTML-шаблон с экранированием CSS скобок и плейсхолдерами для локализации
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{web_title}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e1e; color: #e0e0e0; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .container {{ text-align: center; background-color: #2d2d2d; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); width: 80%; max-width: 600px; }}
        h1 {{ color: #4caf50; margin-bottom: 10px; }}
        p {{ font-size: 1.1em; color: #b0b0b0; }}
        .stats {{ margin-top: 30px; display: flex; justify-content: space-around; }}
        .stat-box {{ background-color: #3d3d3d; padding: 15px; border-radius: 8px; width: 45%; }}
        .stat-number {{ font-size: 2.5em; font-weight: bold; color: #ffffff; display: block; }}
        .stat-label {{ font-size: 0.9em; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
        .status-indicator {{ display: inline-block; width: 10px; height: 10px; background-color: #4caf50; border-radius: 50%; margin-right: 5px; box-shadow: 0 0 8px #4caf50; }}
        .footer {{ margin-top: 40px; font-size: 0.8em; color: #666; }}
        a {{ color: #4caf50; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <h1><span class="status-indicator"></span> {web_agent_running}</h1>
        <p>{web_agent_active}</p>
        
        <div class="stats">
            <div class="stat-box">
                <span class="stat-number">{nodes_count}</span>
                <span class="stat-label">{web_stats_total}</span>
            </div>
            <div class="stat-box">
                <span class="stat-number">{active_nodes}</span>
                <span class="stat-label">{web_stats_active}</span>
            </div>
        </div>

        <div class="footer">
            <p>{web_footer_endpoint}: <code>/api/heartbeat</code> (POST)</p>
            <p>{web_footer_powered} <a href="https://github.com/jatixs/tgbotvpscp" target="_blank">VPS Manager Bot</a></p>
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
    # Если языка нет в STRINGS, используем дефолтный
    s = STRINGS.get(lang, STRINGS.get('en', {})) 
    
    # 3. Расчет статистики
    now = time.time()
    active_count = 0
    for node in NODES.values():
        if now - node.get("last_seen", 0) < NODE_OFFLINE_TIMEOUT:
            active_count += 1

    # 4. Подготовка данных для шаблона (объединяем строки перевода и статистику)
    data = s.copy() # Копируем словарь переводов, чтобы не менять оригинал
    data.update({
        'nodes_count': len(NODES),
        'active_nodes': active_count
    })
    
    # 5. Рендеринг
    try:
        html = HTML_TEMPLATE.format(**data)
    except KeyError as e:
        # Фолбек на случай, если в переводах не хватает ключей
        logging.error(f"Template rendering error (missing key): {e}")
        html = f"<h1>Agent Running</h1><p>Nodes: {len(NODES)}</p>"

    return web.Response(text=html, content_type='text/html')

async def handle_heartbeat(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    token = data.get("token")
    stats = data.get("stats", {})

    if not token:
        return web.json_response({"error": "Token required"}, status=401)

    node = get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Invalid token"}, status=403)

    # Если нода прислала хартбит, она жива -> снимаем флаг перезагрузки
    if node.get("is_restarting"):
        node["is_restarting"] = False

    peername = request.transport.get_extra_info('peername')
    ip = peername[0] if peername else "Unknown"

    update_node_heartbeat(token, ip, stats)

    tasks = node.get("tasks", [])
    response_data = {"status": "ok"}
    
    if tasks:
        response_data["tasks"] = tasks
        node["tasks"] = [] 

    return web.json_response(response_data)

async def start_web_server():
    app = web.Application()
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