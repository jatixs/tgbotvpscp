from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Final

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config as current_config
from .. import nodes_db
from ..config import ADMIN_USER_ID, BASE_DIR, NODE_OFFLINE_TIMEOUT, TG_BOT_NAME, WEB_SERVER_HOST, WEB_SERVER_PORT
from ..i18n import get_text as _, get_user_lang
from ..utils import decrypt_for_web, encrypt_for_web, get_app_version, get_web_key
from .auth import get_current_user
from modules.services import (
    add_managed_service,
    get_all_services_status,
    get_user_role_level,
    perform_service_action,
    remove_managed_service,
)

routes = web.RouteTableDef()

TEMPLATE_DIR: Final[Path] = Path(BASE_DIR) / "core" / "templates"
JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
APP_VERSION: Final[str] = get_app_version()
CACHE_VER: Final[str] = str(int(time.time()))
ALLOWED_NODE_COMMANDS: Final[set[str]] = {
    "selftest",
    "uptime",
    "traffic",
    "top",
    "speedtest",
    "update",
    "reboot",
    "services_list",
}
ALLOWED_SERVICE_ACTIONS: Final[set[str]] = {"start", "stop", "restart"}


def _get_avatar_html(user: dict[str, Any]) -> str:
    raw = str(user.get("photo_url", ""))
    if raw.startswith("http"):
        return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'


def _is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") == "admins" or int(user.get("id", 0)) == ADMIN_USER_ID


async def _require_user(request: web.Request) -> dict[str, Any] | None:
    user = get_current_user(request)
    if not user:
        return None
    return user


@routes.get("/api/nodes/list")
async def handle_nodes_list_json(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    all_nodes = await nodes_db.get_all_nodes()
    nodes_data: list[dict[str, Any]] = []
    now = time.time()

    for token, node in all_nodes.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        status = "restarting" if is_restarting else "online" if now - last_seen < NODE_OFFLINE_TIMEOUT else "offline"
        stats = node.get("stats", {})

        nodes_data.append(
            {
                "token": encrypt_for_web(token),
                "name": node.get("name", "Unknown"),
                "ip": encrypt_for_web(node.get("ip", "Unknown")),
                "status": status,
                "cpu": stats.get("cpu", 0),
                "ram": stats.get("ram", 0),
                "disk": stats.get("disk", 0),
            }
        )

    return web.json_response({"nodes": nodes_data})


@routes.post("/api/nodes/add")
async def handle_node_add(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        name = str(data.get("name", "")).strip()
        if not name:
            return web.json_response({"error": "Name required"}, status=400)

        token = await nodes_db.create_node(name)
        host = request.headers.get("Host", f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        if not re.match(r"^[a-zA-Z0-9\-\.:]+$", host):
            host = f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}"

        proto = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        lang = get_user_lang(int(user["id"]))
        script = "deploy_en.sh" if lang == "en" else "deploy.sh"
        command = (
            f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/{script}) "
            f"--agent={proto}://{host} --token={token}"
        )

        return web.json_response(
            {
                "status": "ok",
                "token": encrypt_for_web(token),
                "command": encrypt_for_web(command),
            }
        )
    except Exception:
        logging.exception("Failed to add node")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/nodes/delete")
async def handle_node_delete(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        token = decrypt_for_web(data.get("token"))
        if not token:
            return web.json_response({"error": "Token required"}, status=400)

        await nodes_db.delete_node(token)
        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Failed to delete node")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/nodes/rename")
async def handle_node_rename(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user or int(user["id"]) != ADMIN_USER_ID:
        return web.json_response({"error": "Only Main Admin required"}, status=403)

    try:
        data = await request.json()
        token = decrypt_for_web(data.get("token"))
        new_name = str(data.get("name", "")).strip()
        if not token or not new_name:
            return web.json_response({"error": "Token and name required"}, status=400)

        success = await nodes_db.update_node_name(token, new_name)
        if not success:
            return web.json_response({"error": "Node not found"}, status=404)

        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Failed to rename node")
        return web.json_response({"error": "Internal Server Error"}, status=500)


async def handle_nodes_monitor_page(request: web.Request) -> web.StreamResponse:
    """Render the nodes monitoring page."""
    user = await _require_user(request)
    if not user:
        raise web.HTTPFound("/login")

    user_id = int(user["id"])
    lang = get_user_lang(user_id)
    role = str(user.get("role", "users"))
    is_admin = _is_admin(user)

    if not is_admin:
        raise web.HTTPFound("/")

    web_meta = getattr(current_config, "WEB_METADATA", {})
    custom_title = web_meta.get("title", "")
    page_title = f"{_('web_nodes_monitor_title', lang)} - {TG_BOT_NAME}"
    if custom_title:
        page_title = f"{_('web_nodes_monitor_title', lang)} - {custom_title}"

    clean_version = APP_VERSION.lstrip("v")
    display_version = f"v{clean_version}"

    context = {
        "lang": lang,
        "web_title": page_title,
        "web_version": display_version,
        "pwa_version": current_config.INSTALLED_VERSION or display_version,
        "cache_ver": CACHE_VER,
        "user_avatar": _get_avatar_html(user),
        "user_name": user.get("first_name", "User"),
        "user_role_js": f"const USER_ROLE = '{role}'; const IS_MAIN_ADMIN = {str(user_id == ADMIN_USER_ID).lower()}; const WEB_KEY = '{get_web_key()}';",
        "web_monitor_title": _("web_nodes_monitor_title", lang),
        "web_mass_actions": _("web_nodes_monitor_mass_actions", lang),
        "web_select_all": _("web_nodes_monitor_select_all", lang),
        "web_mass_selftest": _("web_nodes_monitor_mass_selftest", lang),
        "web_mass_reboot": _("web_nodes_monitor_mass_reboot", lang),
        "web_refresh": _("web_refresh", lang),
        "web_search_placeholder": _("web_nodes_monitor_search", lang),
        "web_filter_all": _("web_nodes_monitor_filter_all", lang),
        "web_filter_online": _("web_nodes_monitor_filter_online", lang),
        "web_filter_offline": _("web_nodes_monitor_filter_offline", lang),
        "web_filter_restarting": _("web_nodes_monitor_filter_restarting", lang),
        "web_filter_btn": _("web_nodes_monitor_filter_btn", lang),
        "web_filter_title": _("web_nodes_monitor_filter_title", lang),
        "web_filter_status": _("web_nodes_monitor_filter_status", lang),
        "web_filter_cpu_load": _("web_nodes_monitor_filter_cpu_load", lang),
        "web_filter_high": _("web_nodes_monitor_filter_high", lang),
        "web_filter_medium": _("web_nodes_monitor_filter_medium", lang),
        "web_filter_low": _("web_nodes_monitor_filter_low", lang),
        "web_filter_sort_by": _("web_nodes_monitor_filter_sort_by", lang),
        "web_filter_sort_name": _("web_nodes_monitor_filter_sort_name", lang),
        "web_filter_sort_cpu": _("web_nodes_monitor_filter_sort_cpu", lang),
        "web_filter_sort_ram": _("web_nodes_monitor_filter_sort_ram", lang),
        "web_filter_sort_ping": _("web_nodes_monitor_filter_sort_ping", lang),
        "web_filter_reset": _("web_nodes_monitor_filter_reset", lang),
        "web_filter_apply": _("web_nodes_monitor_filter_apply", lang),
        "web_loading": _("web_loading", lang),
        "web_stats_total": _("web_stats_total", lang),
        "web_uptime": _("web_nodes_monitor_uptime", lang),
        "web_resources_chart": _("web_nodes_monitor_resources_chart", lang),
        "web_network_chart": _("web_nodes_monitor_network_chart", lang),
        "web_services_title": _("web_nodes_monitor_tab_services", lang),
        "web_live": _("web_live", lang),
        "web_cpu": _("web_nodes_monitor_cpu", lang),
        "web_ram": _("web_nodes_monitor_ram", lang),
        "web_disk": _("web_nodes_monitor_disk", lang),
        "web_show_more": _("web_show_more", lang),
        "web_show_less": _("web_show_less", lang),
        "web_node_details": _("web_nodes_monitor_details", lang),
        "btn_selftest": _("web_nodes_monitor_btn_selftest", lang),
        "btn_speedtest": _("web_nodes_monitor_btn_speedtest", lang),
        "btn_reboot": _("web_nodes_monitor_btn_reboot", lang),
        "modal_btn_cancel": _("modal_btn_cancel", lang),
        "modal_btn_ok": _("modal_btn_ok", lang),
        "i18n_json": json.dumps(
            {
                "web_no_nodes": _("web_nodes_monitor_no_nodes", lang),
                "web_no_nodes_desc": _("web_nodes_monitor_no_nodes_desc", lang),
                "web_loading": _("web_loading", lang),
                "web_error": _("web_nodes_monitor_error", lang),
                "web_services_empty": _("web_nodes_monitor_no_services", lang),
                "web_services_loading": _("web_nodes_monitor_services_loading", lang),
                "modal_title_alert": _("modal_title_alert", lang),
                "modal_title_confirm": _("modal_title_confirm", lang),
                "modal_title_error": _("modal_title_error", lang),
                "modal_title_info": _("web_nodes_monitor_detail_title", lang),
                "web_time_d": _("unit_day_short", lang),
                "web_time_h": _("unit_hour_short", lang),
                "web_time_m": _("unit_minute_short", lang),
                "web_node_status_online": _("web_nodes_monitor_online", lang),
                "web_node_status_offline": _("web_nodes_monitor_offline", lang),
                "web_node_status_restarting": _("web_node_restarting", lang),
                "web_nodes_monitor_select_nodes": _("web_nodes_monitor_select_nodes", lang),
                "web_nodes_monitor_confirm_mass_reboot": _("web_nodes_monitor_confirm_mass_reboot", lang),
                "web_nodes_monitor_confirm_mass_command": _("web_nodes_monitor_confirm_mass_command", lang),
                "web_reboot_node_confirm": _("web_nodes_monitor_confirm_reboot", lang),
                "web_command_sent": _("web_nodes_monitor_command_sent", lang),
                "web_service_start": _("web_nodes_monitor_service_start", lang),
                "web_service_stop": _("web_nodes_monitor_service_stop", lang),
                "web_service_restart": _("web_nodes_monitor_service_restart", lang),
                "web_service_confirm": _("web_nodes_monitor_confirm_service", lang),
                "web_details": _("web_nodes_monitor_details", lang),
                "web_node_details": _("web_nodes_monitor_details", lang),
                "web_cpu": _("web_nodes_monitor_cpu", lang),
                "web_ram": _("web_nodes_monitor_ram", lang),
                "web_disk": _("web_nodes_monitor_disk", lang),
                "web_traffic_in": _("web_nodes_monitor_traffic_in", lang),
                "web_traffic_out": _("web_nodes_monitor_traffic_out", lang),
                "web_show_more": _("web_show_more", lang),
                "web_show_less": _("web_show_less", lang),
                "web_nodes_monitor_btn_reboot": _("web_nodes_monitor_btn_reboot", lang),
                "web_nodes_monitor_btn_selftest": _("web_nodes_monitor_btn_selftest", lang),
                "web_nodes_monitor_btn_speedtest": _("web_nodes_monitor_btn_speedtest", lang),
                "web_nodes_monitor_btn_traffic": _("web_nodes_monitor_btn_traffic", lang),
                "web_commands_sent": _("web_commands_sent", lang),
                "web_reboot_sent": _("web_reboot_sent", lang),
                "web_node_modal_loading": _("web_node_modal_loading", lang),
                "unit_bytes": _("unit_bytes", lang),
                "unit_kb": _("unit_kb", lang),
                "unit_mb": _("unit_mb", lang),
                "unit_gb": _("unit_gb", lang),
                "unit_tb": _("unit_tb", lang),
                "unit_pb": _("unit_pb", lang),
            }
        ),
    }

    template = JINJA_ENV.get_template("nodes_monitor.html")
    html = template.render(**context)
    return web.Response(text=html, content_type="text/html")


@routes.get("/api/nodes/monitor/list")
async def handle_nodes_monitor_list(request: web.Request) -> web.StreamResponse:
    """Return extended node data for the monitoring page."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        all_nodes = await nodes_db.get_all_nodes()
        nodes_data: list[dict[str, Any]] = []
        now = time.time()

        for token, node in all_nodes.items():
            last_seen = node.get("last_seen", 0)
            is_restarting = node.get("is_restarting", False)
            status = "restarting" if is_restarting else "online" if now - last_seen < NODE_OFFLINE_TIMEOUT else "offline"
            stats = node.get("stats", {})

            nodes_data.append(
                {
                    "token": encrypt_for_web(token),
                    "name": node.get("name", "Unknown"),
                    "ip": node.get("ip", "Unknown"),
                    "status": status,
                    "cpu": stats.get("cpu", 0),
                    "ram": stats.get("ram", 0),
                    "disk": stats.get("disk", 0),
                    "uptime": stats.get("uptime", 0),
                    "ping": stats.get("ping"),
                    "traffic": {
                        "rx": stats.get("net_rx", 0),
                        "tx": stats.get("net_tx", 0),
                    },
                    "last_seen": last_seen,
                }
            )

        return web.json_response({"nodes": nodes_data})
    except Exception as exc:
        logging.error("Error in handle_nodes_monitor_list: %s", exc)
        return web.json_response({"error": str(exc), "nodes": []}, status=500)


@routes.get("/api/nodes/monitor/detail")
async def handle_nodes_monitor_detail(request: web.Request) -> web.StreamResponse:
    """Return detailed information about one node."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    token = decrypt_for_web(request.query.get("token"))
    if not token:
        return web.json_response({"error": "Token required"}, status=400)

    node = await nodes_db.get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Node not found"}, status=404)

    now = time.time()
    last_seen = node.get("last_seen", 0)
    is_restarting = node.get("is_restarting", False)
    status = "restarting" if is_restarting else "online" if now - last_seen < NODE_OFFLINE_TIMEOUT else "offline"

    return web.json_response(
        {
            "name": node.get("name"),
            "ip": node.get("ip"),
            "status": status,
            "stats": node.get("stats", {}),
            "history": node.get("history", []),
            "token": encrypt_for_web(token),
            "last_seen": last_seen,
            "services": node.get("services", []),
        }
    )


@routes.get("/api/nodes/monitor/services")
async def handle_nodes_monitor_services(request: web.Request) -> web.StreamResponse:
    """Return the latest services snapshot for one node."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    token = decrypt_for_web(request.query.get("token"))
    if not token:
        return web.json_response({"error": "Token required"}, status=400)

    node = await nodes_db.get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Node not found"}, status=404)

    return web.json_response({"services": node.get("services", [])})


@routes.post("/api/nodes/monitor/command")
async def handle_nodes_monitor_command(request: web.Request) -> web.StreamResponse:
    """Queue a command for a node agent."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        token = decrypt_for_web(data.get("token"))
        command = str(data.get("command", "")).strip()

        if not token or not command:
            return web.json_response({"error": "Token and command required"}, status=400)
        if command not in ALLOWED_NODE_COMMANDS:
            return web.json_response({"error": "Invalid command"}, status=400)

        node = await nodes_db.get_node_by_token(token)
        if not node:
            return web.json_response({"error": "Node not found"}, status=404)

        if command == "reboot":
            await nodes_db.update_node_extra(token, "is_restarting", True)

        await nodes_db.update_node_task(token, {"command": command, "user_id": int(user["id"])})
        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Failed to queue node command")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/nodes/monitor/service_action")
async def handle_nodes_monitor_service_action(request: web.Request) -> web.StreamResponse:
    """Queue a service action for a remote node."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    try:
        data = await request.json()
        token = decrypt_for_web(data.get("token"))
        service = str(data.get("service", "")).strip()
        action = str(data.get("action", "")).strip()
        service_type = str(data.get("type", "systemd")).strip()

        if not token or not service or not action:
            return web.json_response({"error": "Token, service and action required"}, status=400)
        if action not in ALLOWED_SERVICE_ACTIONS:
            return web.json_response({"error": "Invalid action"}, status=400)

        node = await nodes_db.get_node_by_token(token)
        if not node:
            return web.json_response({"error": "Node not found"}, status=404)

        await nodes_db.update_node_task(
            token,
            {
                "command": "service_action",
                "service": service,
                "action": action,
                "type": service_type,
                "user_id": int(user["id"]),
            },
        )
        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Failed to queue node service action")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/services")
async def handle_services_list(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        services = await asyncio.to_thread(get_all_services_status)
        return web.json_response(services)
    except Exception:
        logging.exception("Failed to fetch services list")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/services/{action}")
async def api_control_service(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        user_id = int(user["id"])
        level = get_user_role_level(user_id)
        action = request.match_info["action"]

        if level == 0:
            return web.json_response({"error": "Access Denied (View Only)"}, status=403)
        if action == "stop" and level < 2:
            return web.json_response({"error": "Access Denied (Stop not allowed)"}, status=403)

        data = await request.json()
        name = str(data.get("name", "")).strip()
        service_type = str(data.get("type", "systemd")).strip()
        if not name:
            return web.json_response({"error": "Name required"}, status=400)

        found = any(service.get("name") == name for service in current_config.MANAGED_SERVICES)
        if not found:
            return web.json_response({"error": "Service not managed"}, status=403)

        success, message = await perform_service_action(name, service_type, action)
        if success:
            return web.json_response({"status": "ok", "message": message})
        return web.json_response({"error": message}, status=500)
    except Exception:
        logging.exception("Failed to control service")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/services/manage")
async def api_services_manage(request: web.Request) -> web.StreamResponse:
    """Add or remove a service from the managed list."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        user_id = int(user["id"])
        level = get_user_role_level(user_id)
        if level < 2:
            return web.json_response({"error": "Access Denied"}, status=403)

        data = await request.json()
        action = str(data.get("action", "")).strip()
        name = str(data.get("name", "")).strip()
        service_type = str(data.get("type", "systemd")).strip()

        if not name:
            return web.json_response({"error": "Name required"}, status=400)

        if action == "add":
            success, message = await asyncio.to_thread(add_managed_service, name, service_type)
        elif action == "remove":
            success, message = await asyncio.to_thread(remove_managed_service, name)
        else:
            return web.json_response({"error": "Invalid action"}, status=400)

        if success:
            return web.json_response({"status": "ok", "message": message})
        return web.json_response({"error": message}, status=400)
    except Exception:
        logging.exception("Failed to manage services list")
        return web.json_response({"error": "Internal Server Error"}, status=500)


__all__ = [
    "routes",
    "handle_nodes_list_json",
    "handle_node_add",
    "handle_node_delete",
    "handle_node_rename",
    "handle_nodes_monitor_page",
    "handle_nodes_monitor_list",
    "handle_nodes_monitor_detail",
    "handle_nodes_monitor_services",
    "handle_nodes_monitor_command",
    "handle_nodes_monitor_service_action",
    "handle_services_list",
    "api_control_service",
    "api_services_manage",
]
