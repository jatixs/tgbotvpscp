from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Final

from aiohttp import web
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config as current_config
from .. import nodes_db, shared_state
from ..config import ADMIN_USER_ID, BASE_DIR, NODE_OFFLINE_TIMEOUT, TG_BOT_NAME, WEB_SERVER_HOST, WEB_SERVER_PORT, DEFAULT_LANGUAGE
from ..i18n import STRINGS, get_text as _, get_user_lang
from ..messaging import send_alert
from ..utils import decrypt_for_web, encrypt_for_web, get_app_version, get_country_flag, get_server_timezone_label, get_web_key
from .auth import COOKIE_NAME, SERVER_SESSIONS, get_current_user
from ..rbac import build_user_role_js, get_role_level as get_user_role_level, is_admin as _is_admin
from modules.services import (
    add_managed_service,
    get_all_available_services,
    get_all_services_status,
    get_service_info,
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
SSE_ACCEPT_HEADER: Final[str] = "text/event-stream"
NODES_MONITOR_STREAM_INTERVAL: Final[float] = 10.0


def _mask_ip(ip: str) -> str:
    if not isinstance(ip, str) or len(ip) < 4:
        return "***"
    return ip[:4] + "*" * max(0, len(ip) - 4)


def _is_sse_request(request: web.Request) -> bool:
    accept_header = request.headers.get("Accept", "")
    return SSE_ACCEPT_HEADER in accept_header.lower()


def _build_plain_api_notice(path: str) -> web.Response:
    message = (
        f"Это обычный HTTP/HTTPS-запрос.\n"
        f"Маршрут {path} является внутренним SSE-endpoint и не предназначен для прямого открытия в браузере.\n"
        f"Используйте WebUI или специализированный клиент ({SSE_ACCEPT_HEADER})."
    )
    return web.Response(text=message, content_type="text/plain", status=406)


async def _write_sse(response: web.StreamResponse, event: str, data: Any) -> None:
    payload = json.dumps(data)
    await response.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))


def _session_expired(current_token: str | None) -> bool:
    return bool(current_token and current_token not in SERVER_SESSIONS)


def _get_alert_reporter_hash(all_nodes: dict[str, dict[str, Any]], *, now: float) -> str:
    online_tokens: list[str] = []
    fallback_tokens: list[str] = []

    for token, node in all_nodes.items():
        fallback_tokens.append(token)
        last_seen = float(node.get("last_seen", 0) or 0)
        if now - last_seen < NODE_OFFLINE_TIMEOUT:
            online_tokens.append(token)

    selected_tokens = sorted(online_tokens or fallback_tokens)
    if not selected_tokens:
        return ""

    return hashlib.sha256(selected_tokens[0].encode()).hexdigest()


def _build_nodes_monitor_payload(all_nodes: dict[str, dict[str, Any]], *, now: float) -> dict[str, list[dict[str, Any]]]:
    nodes_data: list[dict[str, Any]] = []

    for token, node in all_nodes.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        status = "restarting" if is_restarting else "online" if now - last_seen < NODE_OFFLINE_TIMEOUT else "offline"
        stats = node.get("stats", {})
        ping = stats.get("ping")

        nodes_data.append(
            {
                "token": encrypt_for_web(token),
                "name": encrypt_for_web(node.get("name", "Unknown")),
                "ip": encrypt_for_web(node.get("ip", "Unknown")),
                "status": status,
                "cpu": stats.get("cpu", 0),
                "ram": stats.get("ram", 0),
                "disk": stats.get("disk", 0),
                "uptime": stats.get("uptime", 0),
                "ping": encrypt_for_web(ping) if ping is not None else "",
                "traffic": {
                    "rx": stats.get("net_rx", 0),
                    "tx": stats.get("net_tx", 0),
                },
                "last_seen": last_seen,
            }
        )

    return {"nodes": nodes_data}


async def process_node_result_background(
    bot: Any,
    user_id: int | None,
    cmd: str,
    text: Any,
    token: str,
    node_name: str,
) -> None:
    if not user_id:
        return

    if isinstance(text, dict) and text.get("type") == "services_list":
        services = text.get("services", [])
        if services:
            await nodes_db.update_node_extra(token, "services", services)
        return

    final_text = text
    if isinstance(text, dict) and text.get("type") == "i18n":
        try:
            lang = get_user_lang(user_id)
            key = text.get("key")
            params = text.get("params", {})
            resolved_params: dict[str, Any] = {}
            for param_key, param_value in params.items():
                if isinstance(param_value, dict) and "key" in param_value:
                    resolved_params[param_key] = _(param_value["key"], lang, **param_value.get("params", {}))
                else:
                    resolved_params[param_key] = param_value
            final_text = _(key, lang, **resolved_params)
        except Exception as exc:
            logging.error("Error processing i18n node result: %s", exc)
            final_text = str(text)
    elif isinstance(text, dict):
        final_text = str(text)

    if not final_text:
        return

    try:
        if cmd == "traffic":
            monitors = getattr(shared_state, "NODE_TRAFFIC_MONITORS", {})
            if user_id not in monitors:
                return
            monitor = monitors[user_id]
            if monitor.get("token") == token:
                msg_id = monitor.get("message_id")
                stop_kb = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="⏹ Stop", callback_data=f"node_stop_traffic_{token}")]]
                )
                try:
                    await bot.edit_message_text(
                        text=final_text,
                        chat_id=user_id,
                        message_id=msg_id,
                        reply_markup=stop_kb,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                return

        await bot.send_message(
            chat_id=user_id,
            text=_("node_response_template", user_id, name=node_name, text=final_text),
            parse_mode="HTML",
        )
    except Exception as exc:
        logging.error("Background send error: %s", exc)


def _get_avatar_html(user: dict[str, Any]) -> str:
    raw = str(user.get("photo_url", ""))
    if raw.startswith("http"):
        return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'


async def _require_user(request: web.Request) -> dict[str, Any] | None:
    user = get_current_user(request)
    if not user:
        return None
    return user


@routes.get("/api/heartbeat")
async def handle_heartbeat_probe(request: web.Request) -> web.StreamResponse:
    return web.json_response({"status": "ok"})


@routes.post("/api/heartbeat")
async def handle_heartbeat(request: web.Request) -> web.StreamResponse:
    signature = request.headers.get("X-Signature")
    if not signature:
        return web.json_response({"error": "Signature missing"}, status=401)

    try:
        body_bytes = await request.read()
        data = json.loads(body_bytes)
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    token = request.headers.get("X-Node-Token") or data.get("token")
    if not token:
        return web.json_response({"error": "Token missing"}, status=401)

    expected_signature = hmac.new(token.encode(), body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        safe_ip = str(request.remote or "unknown").replace("\n", "").replace("\r", "")
        logging.warning("Invalid signature from %s", _mask_ip(safe_ip))
        return web.json_response({"error": "Invalid signature"}, status=403)

    node = await nodes_db.get_node_by_token(token)
    if not node:
        return web.json_response({"error": "Auth fail"}, status=401)

    bot = request.app.get("bot")
    ssh_logins = data.get("ssh_logins", [])
    if ssh_logins and bot:
        server_tz = get_server_timezone_label()
        server_time = time.strftime("%H:%M")
        now = time.time()
        recent_ssh_logins = getattr(shared_state, "RECENT_SSH_LOGINS", {})

        for login in ssh_logins:
            user_ssh = login.get("user", "unknown")
            ip = login.get("ip", "unknown")
            method_raw = login.get("method", "unknown")
            node_time_str = login.get("node_time_str", "??:??")
            tz_label = login.get("tz_label", "")
            cache_key = f"{token}_{ip}"
            last_alert_time = recent_ssh_logins.get(cache_key, 0)
            if now - last_alert_time <= 10:
                continue

            recent_ssh_logins[cache_key] = now
            if len(recent_ssh_logins) > 1000:
                recent_ssh_logins.clear()

            method_key = "auth_method_unknown"
            if "publickey" in str(method_raw).lower():
                method_key = "auth_method_key"
            elif "password" in str(method_raw).lower():
                method_key = "auth_method_password"

            flag = await get_country_flag(ip)
            await send_alert(
                bot,
                lambda lang: _(
                    "alert_ssh_login_node",
                    lang,
                    node_name=node.get("name", "Node"),
                    user=user_ssh,
                    method=_(method_key, lang),
                    ip_flag=flag,
                    ip=ip,
                    node_time=node_time_str,
                    node_tz=tz_label,
                    server_time=server_time,
                    server_tz=server_tz,
                ),
                "node_logins",
                node_token=token,
            )

    stats = data.get("stats", {})
    results = data.get("results", [])
    if bot and results:
        for result in results:
            asyncio.create_task(
                process_node_result_background(
                    bot,
                    result.get("user_id"),
                    result.get("command", ""),
                    result.get("result"),
                    token,
                    node.get("name", "Node"),
                )
            )

    if node.get("is_restarting"):
        await nodes_db.update_node_extra(token, "is_restarting", False)

    peer_ip = "127.0.0.1"
    if request.transport is not None:
        peer = request.transport.get_extra_info("peername")
        if isinstance(peer, tuple) and peer:
            peer_ip = str(peer[0])

    ip = str(stats.get("external_ip") or peer_ip)
    await nodes_db.update_node_heartbeat(token, ip, stats)

    services = data.get("services", [])
    if services:
        await nodes_db.update_node_extra(token, "services", services)

    current_node = await nodes_db.get_node_by_token(token)
    tasks_to_send = current_node.get("tasks", []) if current_node else []
    if tasks_to_send:
        await nodes_db.clear_node_tasks(token)

    all_nodes = await nodes_db.get_all_nodes()
    alert_reporter_hash = _get_alert_reporter_hash(all_nodes, now=time.time())

    alert_lang = get_user_lang(ADMIN_USER_ID)
    if alert_lang not in STRINGS:
        alert_lang = DEFAULT_LANGUAGE

    return web.json_response(
        {
            "status": "ok",
            "tasks": tasks_to_send,
            "alert_lang": alert_lang,
            "agent_alert_reporter_hash": alert_reporter_hash,
        }
    )


@routes.get("/api/nodes/list")
async def handle_nodes_list_json(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

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
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

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
        "user_role_js": build_user_role_js(role, user_id),
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
    """Stream extended node data for the monitoring page via SSE."""
    if not _is_sse_request(request):
        return _build_plain_api_notice(request.path)

    user = get_current_user(request)
    if not user:
        return web.Response(status=401)

    current_token = request.cookies.get(COOKIE_NAME)
    response = web.StreamResponse(status=200, reason="OK")
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    await response.prepare(request)

    shutdown_event = request.app.get("shutdown_event")

    try:
        while True:
            if shared_state.IS_RESTARTING:
                try:
                    await response.write(b"event: shutdown\ndata: restarting\n\n")
                except Exception:
                    pass
                break

            try:
                if request.transport is None or request.transport.is_closing():
                    break
            except Exception:
                break

            if _session_expired(current_token):
                try:
                    await response.write(b"event: session_status\ndata: expired\n\n")
                except Exception:
                    pass
                break

            try:
                all_nodes = await nodes_db.get_all_nodes()
                payload = _build_nodes_monitor_payload(all_nodes, now=time.time())
                await _write_sse(response, "nodes_list", payload)
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                break
            except Exception as exc:
                logging.error("SSE nodes monitor list error: %s", exc)
                try:
                    await _write_sse(response, "error", {"error": "Internal Server Error"})
                except Exception:
                    pass

            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=NODES_MONITOR_STREAM_INTERVAL)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(NODES_MONITOR_STREAM_INTERVAL)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        if "closing transport" not in str(exc) and "'NoneType' object" not in str(exc):
            logging.error("SSE nodes monitor stream error: %s", exc)

    return response


@routes.get("/api/nodes/monitor/detail")
async def handle_nodes_monitor_detail(request: web.Request) -> web.StreamResponse:
    """Return detailed information about one node."""
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

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
    if not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

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


@routes.get("/api/services/available")
async def handle_available_services(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        services = await asyncio.to_thread(get_all_available_services)
        return web.json_response(services)
    except Exception:
        logging.exception("Failed to fetch available services")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get(r"/api/services/info/{name:.+}")
async def handle_service_info(request: web.Request) -> web.StreamResponse:
    user = await _require_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        name = request.match_info.get("name", "")
        service_type = str(request.query.get("type", "systemd")).strip()
        info = await get_service_info(name, service_type)
        return web.json_response(info)
    except Exception:
        logging.exception("Failed to fetch service info")
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
    "handle_available_services",
    "handle_service_info",
    "api_control_service",
    "api_services_manage",
]
