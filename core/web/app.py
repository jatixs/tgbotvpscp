"""
Инициализация и запуск aiohttp веб-сервера (WebUI).
Настраивает маршрутизацию, CORS, шаблонизатор Jinja2 и статические файлы.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Final

from aiohttp import web
from aiogram import Bot

from ..config import BASE_DIR, ENABLE_WEB_UI, WEB_SERVER_HOST, WEB_SERVER_PORT
from ..tasks import cleanup_server, start_background_tasks
from .api_nodes import routes as node_routes
from .api_system import routes as system_routes
from .auth import routes as auth_routes
from .middlewares import csrf_middleware, rate_limit_middleware, security_headers_middleware, waf_middleware
from .streaming import routes as streaming_routes
from .views import routes as view_routes

STATIC_DIR: Final[Path] = Path(BASE_DIR) / "core" / "static"
MAX_CLIENT_UPLOAD_SIZE: Final[int] = 5 * 1024 * 1024

try:
    from .routes import routes as extra_routes
except ImportError:
    extra_routes = web.RouteTableDef()


async def on_shutdown(app: web.Application) -> None:
    """Signal background tasks and SSE clients that shutdown has started."""
    shutdown_event = app.get("shutdown_event")
    if isinstance(shutdown_event, asyncio.Event):
        shutdown_event.set()


def create_web_app(bot_instance: Bot) -> web.Application:
    """Create and configure the aiohttp application instance."""
    app = web.Application(
        middlewares=[security_headers_middleware, rate_limit_middleware, csrf_middleware, waf_middleware],
        client_max_size=MAX_CLIENT_UPLOAD_SIZE,
    )
    app["bot"] = bot_instance
    app["shutdown_event"] = asyncio.Event()
    app.on_startup.append(start_background_tasks)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(cleanup_server)

    if ENABLE_WEB_UI and STATIC_DIR.exists():
        app.router.add_static("/static", str(STATIC_DIR))

    _register_routes(app)
    return app


def _register_routes(app: web.Application) -> None:
    """Register route tables imported from the modular web layer."""
    try:
        app.add_routes(view_routes)
        app.add_routes(auth_routes)
        app.add_routes(node_routes)
        app.add_routes(system_routes)
        app.add_routes(streaming_routes)
        app.add_routes(extra_routes)
        logging.info("Web route tables registered successfully")
    except Exception:
        logging.exception("Failed to register web route tables")
        raise


async def start_web_server(bot_instance: Bot) -> web.AppRunner | None:
    """Initialize and start the production aiohttp web server."""
    app = create_web_app(bot_instance)
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)

    try:
        await runner.setup()
        site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
        await site.start()
    except Exception:
        logging.exception(
            "Failed to start web server on %s:%s",
            WEB_SERVER_HOST,
            WEB_SERVER_PORT,
        )
        await runner.cleanup()
        return None

    logging.info("Web server started on %s:%s", WEB_SERVER_HOST, WEB_SERVER_PORT)
    return runner


__all__ = ["create_web_app", "start_web_server", "on_shutdown"]
