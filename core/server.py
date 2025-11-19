import logging
from aiohttp import web
from .nodes_db import get_node_by_token, update_node_heartbeat
from .config import WEB_SERVER_HOST, WEB_SERVER_PORT
# Импортируем NODES для прямого изменения флагов (или через nodes_db)
from .shared_state import NODES

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