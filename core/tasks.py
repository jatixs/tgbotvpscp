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
    """Measure agent connectivity using the configured method (HTTP or ICMP) and target."""
    method = getattr(current_config, "PING_METHOD", "HTTP").upper()
    ping_target = os.environ.get("PING_TARGET", "google")
    target_ip = "1.1.1.1" if ping_target == "cloudflare" else "8.8.8.8"
    
    if method == "ICMP":
        try:
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "1", "-w", "2000", target_ip]
                pattern = r"[=<](\d+)\s*ms"
            else:
                cmd = ["ping", "-c", "1", "-W", "2", target_ip]
                pattern = r"time=([\d\.]+)\s*ms"

            proc = await asyncio.to_thread(
                lambda: subprocess.run(cmd, capture_output=True, timeout=5)
            )
            ping_match = re.search(pattern, proc.stdout.decode(errors="ignore"))
            if ping_match:
                return str(round(float(ping_match.group(1)), 1))
        except Exception:
            pass
        return None

    # HTTP Method
    if ping_target == "cloudflare":
        targets = ["https://www.cloudflare.com", "https://1.1.1.1"]
    else:
        targets = ["https://www.google.com", "https://8.8.8.8"]
        
    timeout = aiohttp.ClientTimeout(total=AGENT_PING_TIMEOUT)

    for target in targets:
        try:
            started_at = time.time()
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(target, allow_redirects=False) as response:
                    await response.read()
                    if response.status in {200, 204, 301, 302, 403, 405}:
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

    _db_save_interval = 60.0
    _last_db_save = time.time()
    _internet_down_since: float = 0.0

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

            # Accumulate online time
            shared_state.AGENT_AVAILABILITY["total_online_seconds"] = (
                float(shared_state.AGENT_AVAILABILITY.get("total_online_seconds", 0)) + 2
            )

            ping_interval = getattr(current_config, "PING_INTERVAL", 30)
            if time.time() - shared_state.AGENT_PING_LAST_UPDATE > ping_interval:
                ping_result = await measure_agent_ping()
                shared_state.AGENT_PING_CACHE = ping_result if ping_result else "n/a"
                shared_state.AGENT_PING_LAST_UPDATE = time.time()
                if ping_result is None:
                    if _internet_down_since == 0.0:
                        _internet_down_since = time.time()
                elif _internet_down_since > 0.0:
                    duration = time.time() - _internet_down_since
                    shared_state.AGENT_AVAILABILITY["total_internet_downtime_seconds"] = (
                        float(shared_state.AGENT_AVAILABILITY.get("total_internet_downtime_seconds", 0)) + duration
                    )
                    _internet_down_since = 0.0

            # Periodic DB save
            if time.time() - _last_db_save > _db_save_interval:
                try:
                    shared_state.AGENT_AVAILABILITY["session_end_time"] = time.time()
                    await current_config.set_bot_config("agent_availability", dict(shared_state.AGENT_AVAILABILITY))
                    _last_db_save = time.time()
                except Exception:
                    pass
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
