"""
REST API контроллеры для системных настроек.
Обрабатывают изменение конфигурации панели, управление сессиями и аутентификацией.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any

from aiohttp import web

from .. import config as current_config
from ..auth import get_user_name, save_users_async
from ..config import (
    ADMIN_USER_ID,
    BOT_LOG_DIR,
    DEPLOY_MODE,
    NODE_LOG_DIR,
    WATCHDOG_LOG_DIR,
    save_keyboard_config,
    save_keyboard_config_async,
    save_system_config,
    save_system_config_async,
)
from ..i18n import get_text as _, get_user_lang, set_user_lang_async
from ..shared_state import ALERTS_CONFIG, ALLOWED_USERS, USER_NAMES
from ..utils import generate_favicons, save_alerts_config_async, reset_agent_availability_async
from .auth import get_current_user
from ..rbac import is_admin as _is_admin, is_root as _is_main_admin
# Lazy imports for modules
from .. import shared_state

routes = web.RouteTableDef()


def _read_log_tail_sync(log_path: str, limit: int = 300) -> list[str]:
    with open(log_path, "r", encoding="utf-8", errors="ignore") as file_obj:
        return list(deque(file_obj, limit))


def _clear_logs_sync(target: str) -> None:
    if target == "bot":
        dirs_to_clear = [BOT_LOG_DIR, WATCHDOG_LOG_DIR]
    elif target == "node":
        dirs_to_clear = [NODE_LOG_DIR]
    else:
        dirs_to_clear = [BOT_LOG_DIR, WATCHDOG_LOG_DIR, NODE_LOG_DIR]

    for directory in dirs_to_clear:
        if not os.path.exists(directory):
            continue
        for file_name in os.listdir(directory):
            if not file_name.endswith(".log"):
                continue
            file_path = os.path.join(directory, file_name)
            if os.path.islink(file_path):
                continue
            if os.path.isfile(file_path):
                with open(file_path, "w", encoding="utf-8") as file_obj:
                    file_obj.truncate(0)


@routes.get("/api/logs")
async def handle_get_logs(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Unauthorized"}, status=403)

    lang = get_user_lang(int(user["id"]))
    log_path = os.path.join(current_config.BASE_DIR, "logs", "bot", "bot.log")

    if not os.path.exists(log_path):
        return web.json_response(
            {
                "logs": [
                    _("web_logs_empty_title", lang),
                    _("web_logs_empty_desc", lang),
                ]
            }
        )

    try:
        lines = await asyncio.to_thread(_read_log_tail_sync, log_path, 300)
        return web.json_response({"logs": lines})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/logs/system")
async def handle_get_sys_logs(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Unauthorized"}, status=403)

    try:
        cmd = ["journalctl", "-n", "100", "--no-pager"]
        if DEPLOY_MODE == "docker" and current_config.INSTALL_MODE == "root":
            if os.path.exists("/host/usr/bin/journalctl"):
                cmd = ["chroot", "/host", "/usr/bin/journalctl", "-n", "100", "--no-pager"]

        # nosemgrep: python.lang.security.audit.dangerous-asyncio-create-exec-audit.dangerous-asyncio-create-exec-audit
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            logs = stdout.decode("utf-8", errors="ignore").strip().split("\n")
            return web.json_response({"logs": logs})
        return web.json_response({"error": f"Error reading logs: {stderr.decode()}"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/logs/clear")
async def handle_clear_logs(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data: dict[str, Any] = {}
        try:
            data = await request.json()
        except Exception:
            data = {}

        target = str(data.get("type", "all"))
        await asyncio.to_thread(_clear_logs_sync, target)
        return web.json_response({"status": "ok", "target": target})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/settings/save")
async def handle_save_notifications(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Auth required"}, status=401)

    try:
        data = await request.json()
        uid = int(user["id"])
        if uid not in ALERTS_CONFIG:
            ALERTS_CONFIG[uid] = {}

        for key, value in data.items():
            if key == "master_billing":
                from core.config import get_bot_config, set_bot_config
                mb = await get_bot_config("master_billing") or {}
                mb["reminder_enabled"] = bool(value)
                await set_bot_config("master_billing", mb)
            elif key.startswith("node_") and key.endswith("_billing"):
                token = key.replace("node_", "").replace("_billing", "")
                from core.nodes_db import Node, _get_token_hash
                t_hash = _get_token_hash(token)
                node_obj = await Node.get_or_none(token_hash=t_hash)
                if node_obj:
                    node_obj.reminder_enabled = bool(value)
                    await node_obj.save(update_fields=["reminder_enabled"])
            else:
                ALERTS_CONFIG[uid][key] = bool(value)

        await save_alerts_config_async()
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/settings/system")
async def handle_save_system_config(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        await save_system_config_async(data)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/settings/keyboard")
async def handle_save_keyboard_config(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        await save_keyboard_config_async(data)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/settings/metadata")
async def handle_save_metadata(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        current_meta = getattr(current_config, "WEB_METADATA", {})
        if current_meta.get("locked", False):
            return web.json_response({"error": "Metadata is permanently locked"}, status=403)

        new_favicon_url = str(data.get("favicon", "")).strip()
        if new_favicon_url and not new_favicon_url.startswith(("http://", "https://", "/", "data:image")):
            return web.json_response({"error": "Favicon URL must start with http://, https://, / or data:image"}, status=400)

        new_meta = {
            "favicon": new_favicon_url,
            "title": str(data.get("title", "")).strip(),
            "description": str(data.get("description", "")).strip(),
            "keywords": str(data.get("keywords", "")).strip(),
            "locked": bool(data.get("locked", False)),
        }

        if new_favicon_url.startswith(("http://", "https://", "data:image")):
            static_fav_dir = os.path.join(current_config.BASE_DIR, "core", "static", "favicons")
            await asyncio.to_thread(generate_favicons, new_favicon_url, static_fav_dir)

        current_config.WEB_METADATA = new_meta
        await save_system_config_async({"WEB_METADATA": new_meta})
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/settings/language")
async def handle_set_language(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        lang = data.get("lang")
        if lang in ["ru", "en"]:
            await set_user_lang_async(int(user["id"]), lang)
            return web.json_response({"status": "ok"})
        return web.json_response({"error": "Invalid language"}, status=400)
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/users/action")
async def handle_user_action(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        action = data.get("action")
        target_id = int(data.get("id", 0))
        if not target_id or target_id == ADMIN_USER_ID:
            return web.json_response({"error": "Invalid ID"}, status=400)

        if action == "delete":
            if target_id in ALLOWED_USERS:
                del ALLOWED_USERS[target_id]
                USER_NAMES.pop(str(target_id), None)
                ALERTS_CONFIG.pop(target_id, None)
                await save_users_async()
                await save_alerts_config_async()
                return web.json_response({"status": "ok"})
            return web.json_response({"error": "Not found"}, status=404)

        if action == "add":
            if target_id in ALLOWED_USERS:
                return web.json_response({"error": "Exists"}, status=400)

            ALLOWED_USERS[target_id] = {
                "group": data.get("role", "users"),
                "password_hash": None,
            }
            bot = request.app.get("bot")
            if bot:
                await get_user_name(bot, target_id)
            else:
                USER_NAMES[str(target_id)] = f"User {target_id}"

            await save_users_async()
            return web.json_response({"status": "ok", "name": USER_NAMES.get(str(target_id))})

        return web.json_response({"error": "Unknown"}, status=400)
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/update/check")
async def api_check_update(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        from modules import update as update_module
        info = await update_module.get_update_info()
        if len(info) == 4:
            local_ver, remote_ver, target_branch, update_available = info
        elif len(info) == 3:
            local_ver, remote_ver, target_branch = info
            update_available = target_branch is not None
        else:
            return web.json_response({"error": "Invalid update module response"}, status=500)

        return web.json_response(
            {
                "local_version": local_ver,
                "remote_version": remote_ver,
                "target_branch": target_branch,
                "update_available": update_available,
            }
        )
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/update/run")
async def api_run_update(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        branch = str(data.get("branch", "")).strip()
        if not branch:
            return web.json_response({"error": "No branch specified"}, status=400)

        from modules import update as update_module
        await update_module.execute_bot_update(branch.replace("origin/", ""), restart_source="web:admin")
        return web.json_response({"status": "Update started, server restarting..."})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/notifications/list")
async def api_get_notifications(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    uid = int(user["id"])
    lang = get_user_lang(uid)
    user_alerts = ALERTS_CONFIG.get(uid, {})

    filtered: list[dict[str, Any]] = []
    for notification in list(shared_state.WEB_NOTIFICATIONS):
        if user_alerts.get(notification["type"], False):
            notif_copy = notification.copy()
            if "text_map" in notif_copy and isinstance(notif_copy["text_map"], dict):
                text_map = notif_copy["text_map"]
                localized_text = text_map.get(lang) or text_map.get(current_config.DEFAULT_LANGUAGE)
                if localized_text:
                    notif_copy["text"] = localized_text
                del notif_copy["text_map"]
            filtered.append(notif_copy)

    last_read = shared_state.WEB_USER_LAST_READ.get(uid, 0)
    unread_count = sum(1 for item in filtered if item["time"] > last_read)
    return web.json_response({"notifications": filtered, "unread_count": unread_count})


@routes.post("/api/notifications/read")
async def api_read_notifications(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    uid = int(user["id"])
    shared_state.WEB_USER_LAST_READ[uid] = time.time()
    return web.json_response({"status": "ok"})


@routes.post("/api/notifications/clear")
async def api_clear_notifications(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    shared_state.WEB_NOTIFICATIONS.clear()
    shared_state.WEB_USER_LAST_READ.clear()
    return web.json_response({"status": "ok"})


@routes.post("/api/traffic/reset")
async def handle_reset_traffic(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        from modules import traffic as traffic_module
        traffic_module.TRAFFIC_OFFSET["rx"] = 0
        traffic_module.TRAFFIC_OFFSET["tx"] = 0

        try:
            import glob

            files = glob.glob(os.path.join(traffic_module.config.TRAFFIC_BACKUP_DIR, "traffic_backup_*.json"))
            for file_path in files:
                os.remove(file_path)
        except Exception:
            logging.exception("Failed to remove traffic backup files")

        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/system/reset-uptime")
async def api_reset_agent_uptime(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        await reset_agent_availability_async()
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Internal API error: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


__all__ = [
    "routes",
    "handle_get_logs",
    "handle_get_sys_logs",
    "handle_clear_logs",
    "handle_save_system_config",
    "handle_save_keyboard_config",
    "handle_save_notifications",
    "handle_save_metadata",
    "handle_set_language",
    "handle_user_action",
    "api_check_update",
    "api_run_update",
    "api_get_notifications",
    "api_read_notifications",
    "api_clear_notifications",
]
