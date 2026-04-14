from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
import time
from collections import deque
from typing import Any

import aiohttp
from aiohttp import web

from . import config as current_config
from . import shared_state
from .utils import get_country_flag
from .web.auth import (
    CSRF_TOKENS,
    LOGIN_ATTEMPTS,
    LOGIN_BLOCK_TIME,
    LOGIN_TOKEN_TTL,
    RESET_TOKEN_TTL,
    RESET_TOKENS,
    SERVER_SESSIONS,
)
from .shared_state import AGENT_HISTORY, AUTH_TOKENS

AGENT_PING_TIMEOUT = 5
BACKGROUND_TASKS_KEY = "background_tasks"


async def measure_agent_ping() -> str | None:
    """Measure agent connectivity using ICMP first and HTTPS as fallback."""
    try:
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", "2000", "8.8.8.8"]
            pattern = r"[=<](\d+)\s*ms"
        else:
            cmd = ["ping", "-c", "1", "-W", "2", "8.8.8.8"]
            pattern = r"time=([\d\.]+)\s*ms"

        proc = await asyncio.to_thread(
            lambda: subprocess.run(cmd, capture_output=True, timeout=5)
        )
        ping_match = re.search(pattern, proc.stdout.decode(errors="ignore"))
        if ping_match:
            return str(round(float(ping_match.group(1)), 1))
    except Exception:
        pass

    targets = [
        "https://www.google.com",
        "https://www.cloudflare.com",
        "https://1.1.1.1",
    ]
    timeout = aiohttp.ClientTimeout(total=AGENT_PING_TIMEOUT)

    for target in targets:
        try:
            started_at = time.time()
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(target, allow_redirects=False) as response:
                    await response.read()
                    if response.status in {200, 204, 301, 302, 403}:
                        return str(int((time.time() - started_at) * 1000))
        except Exception:
            continue

    return None


async def agent_monitor() -> None:
    """Update shared agent health caches for the web UI and SSE streams."""
    import psutil
    import requests

    try:
        shared_state.AGENT_IP_CACHE = await asyncio.to_thread(
            lambda: requests.get("https://api.ipify.org", timeout=3).text
        )
    except Exception:
        logging.debug("Unable to refresh public agent IP", exc_info=True)

    try:
        shared_state.AGENT_FLAG = await get_country_flag(shared_state.AGENT_IP_CACHE)
    except Exception:
        logging.debug("Unable to refresh agent country flag", exc_info=True)

    ping_result = await measure_agent_ping()
    shared_state.AGENT_PING_CACHE = ping_result if ping_result else "n/a"
    shared_state.AGENT_PING_LAST_UPDATE = time.time()

    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            ram_pct = round((mem.total - mem.available) / mem.total * 100, 1) if mem.total > 0 else 0
            net = psutil.net_io_counters()
            AGENT_HISTORY.append(
                {
                    "t": int(time.time()),
                    "c": cpu,
                    "r": ram_pct,
                    "rx": net.bytes_recv,
                    "tx": net.bytes_sent,
                }
            )

            ping_interval = getattr(current_config, "PING_INTERVAL", 30)
            if time.time() - shared_state.AGENT_PING_LAST_UPDATE > ping_interval:
                ping_result = await measure_agent_ping()
                shared_state.AGENT_PING_CACHE = ping_result if ping_result else "n/a"
                shared_state.AGENT_PING_LAST_UPDATE = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.debug("Agent monitor iteration failed", exc_info=True)

        await asyncio.sleep(2)


async def cleanup_monitor(app: web.Application) -> None:
    """Periodically clean expired sessions, tokens, login attempts and rate limits."""
    while True:
        try:
            now = time.time()

            expired_sessions = [
                token for token, session in list(SERVER_SESSIONS.items())
                if now > float(session.get("expires", 0))
            ]
            for token in expired_sessions:
                SERVER_SESSIONS.pop(token, None)

            expired_resets = [
                token for token, data in list(RESET_TOKENS.items())
                if now - float(data.get("ts", 0)) > RESET_TOKEN_TTL
            ]
            for token in expired_resets:
                RESET_TOKENS.pop(token, None)

            expired_auth = [
                token for token, data in list(AUTH_TOKENS.items())
                if now - float(data.get("created_at", 0)) > LOGIN_TOKEN_TTL
            ]
            for token in expired_auth:
                AUTH_TOKENS.pop(token, None)

            expired_csrf = [token for token, expires_at in list(CSRF_TOKENS.items()) if now > expires_at]
            for token in expired_csrf:
                CSRF_TOKENS.pop(token, None)

            if len(AUTH_TOKENS) > 1000:
                sorted_tokens = sorted(AUTH_TOKENS.items(), key=lambda item: item[1].get("created_at", 0))
                remove_count = len(AUTH_TOKENS) // 4
                for token, _ in sorted_tokens[:remove_count]:
                    AUTH_TOKENS.pop(token, None)

            for ip in list(LOGIN_ATTEMPTS.keys()):
                LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < LOGIN_BLOCK_TIME]
                if not LOGIN_ATTEMPTS[ip]:
                    LOGIN_ATTEMPTS.pop(ip, None)

            rate_limits = app.get("api_rate_limits", {})
            if isinstance(rate_limits, dict):
                stale_keys: list[str] = []
                for key, timestamps in rate_limits.items():
                    if isinstance(timestamps, deque):
                        while timestamps and now - timestamps[0] > 60:
                            timestamps.popleft()
                        if not timestamps:
                            stale_keys.append(key)
                for key in stale_keys:
                    rate_limits.pop(key, None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Cleanup task error")

        await asyncio.sleep(600)


async def start_background_tasks(app: web.Application) -> None:
    """Start long-running background coroutines for monitoring and maintenance."""
    existing = app.get(BACKGROUND_TASKS_KEY)
    if isinstance(existing, list) and any(not task.done() for task in existing):
        return

    tasks = [
        asyncio.create_task(agent_monitor(), name="agent-monitor"),
        asyncio.create_task(cleanup_monitor(app), name="cleanup-monitor"),
    ]
    app[BACKGROUND_TASKS_KEY] = tasks
    logging.info("Background tasks started: %s", ", ".join(task.get_name() for task in tasks))


async def cleanup_server(app: web.Application) -> None:
    """Cancel running background tasks during application shutdown."""
    tasks = app.get(BACKGROUND_TASKS_KEY, [])
    if not isinstance(tasks, list):
        return

    for task in tasks:
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    app[BACKGROUND_TASKS_KEY] = []


__all__ = [
    "agent_monitor",
    "measure_agent_ping",
    "cleanup_monitor",
    "cleanup_server",
    "start_background_tasks",
]
