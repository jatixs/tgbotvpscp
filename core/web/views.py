from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import time
from pathlib import Path
from typing import Any, Final

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config as current_config
from .. import nodes_db, shared_state
from ..config import ADMIN_USER_ID, BASE_DIR, DEFAULT_LANGUAGE, TG_BOT_NAME
from ..i18n import get_text as _, get_user_lang
from ..keyboards import BTN_CONFIG_MAP
from ..rbac import ROLE_USER, build_user_role_js, get_role_level, is_admin as _is_admin, is_root as _is_root
from ..utils import encrypt_for_web, generate_favicons, get_app_version, get_web_key
from modules import traffic as traffic_module
from . import auth as web_auth

routes = web.RouteTableDef()

TEMPLATE_DIR: Final[Path] = Path(BASE_DIR) / "core" / "templates"
JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
APP_VERSION: Final[str] = get_app_version()
CACHE_VER: Final[str] = str(int(time.time()))


def _get_avatar_html(user: dict[str, Any]) -> str:
    raw = str(user.get("photo_url", ""))
    if raw.startswith("http"):
        return f'<img src="{raw}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    return f'<span class="text-lg leading-none select-none">{raw}</span>'


def _agent_ip() -> str:
    return str(getattr(shared_state, "AGENT_IP_CACHE", "Loading..."))


def _collect_ipv4_addresses() -> list[str]:
    ips: list[str] = []

    try:
        import netifaces  # type: ignore

        for iface in netifaces.interfaces():
            try:
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        ip = str(addr_info.get("addr", "")).strip()
                        if ip and ip != "127.0.0.1" and not ip.startswith("169.254.") and not ip.startswith("172.17.0.1"):
                            ips.append(ip)
            except Exception:
                continue
    except Exception:
        try:
            hostname = socket.gethostname()
            for addr in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = str(addr[4][0]).strip()
                if ip and ip != "127.0.0.1" and not ip.startswith("169.254."):
                    ips.append(ip)
        except Exception:
            pass

    primary_ip = _agent_ip()
    if primary_ip not in {"", "Loading...", "Unknown", "-"}:
        ips.insert(0, primary_ip)

    return list(dict.fromkeys(ips))


async def _ensure_generated_favicons() -> None:
    fav_dir = Path(BASE_DIR) / "core" / "static" / "favicons"
    required_files = [
        fav_dir / "site.webmanifest",
        fav_dir / "favicon.ico",
        fav_dir / "favicon-16x16.png",
        fav_dir / "favicon-32x32.png",
    ]
    if all(path.exists() for path in required_files):
        return

    web_meta = getattr(current_config, "WEB_METADATA", {})
    favicon_source = str(web_meta.get("favicon", "")).strip()
    source: str | None = None

    if favicon_source.startswith(("http://", "https://", "data:image")):
        source = favicon_source
    else:
        fallback_candidates = [
            Path(BASE_DIR) / "assets" / "web_1.png",
            Path(BASE_DIR) / "assets" / "bot_1.png",
        ]
        for candidate in fallback_candidates:
            if candidate.exists():
                source = str(candidate)
                break

    if source:
        await asyncio.to_thread(generate_favicons, source, str(fav_dir))


def _render_html_response(template_name: str, context: dict[str, Any], request: web.Request) -> web.Response:
    template = JINJA_ENV.get_template(template_name)
    response = web.Response(text=template.render(**context), content_type="text/html")
    if hasattr(web_auth, "_set_csrf_cookie"):
        web_auth._set_csrf_cookie(response, request)
    return response


def _build_api_root_notice() -> web.Response:
    return web.json_response(
        {
            "status": "info",
            "message": "Это обычный HTTP/HTTPS-запрос. Базовый путь /api не отдает метрики или потоковые данные напрямую.",
            "usage": "Используйте документированные endpoints из README.md и ARCHITECTURE.md.",
            "routes": {
                "auth": "/api/login/*, /api/auth/*, /api/sessions/*",
                "nodes": "/api/heartbeat, /api/nodes/*",
                "system": "/api/logs/*, /api/settings/*, /api/update/*, /api/notifications/*",
                "services": "/api/services*",
                "streaming": "/api/events*",
                "terminal": "/api/terminal/*",
            },
            "note": "SSE endpoints require Accept: text/event-stream. WebSocket endpoint requires Upgrade: websocket.",
        }
    )


@routes.get("/api")
async def handle_api_root_no_slash(request: web.Request) -> web.StreamResponse:
    return _build_api_root_notice()


@routes.get("/api/")
async def handle_api_root(request: web.Request) -> web.StreamResponse:
    return _build_api_root_notice()


@routes.get("/site.webmanifest")
async def handle_manifest(request: web.Request) -> web.StreamResponse:
    await _ensure_generated_favicons()

    manifest_path = Path(BASE_DIR) / "core" / "static" / "favicons" / "site.webmanifest"
    if manifest_path.exists():
        return web.FileResponse(manifest_path)

    manifest = {
        "name": TG_BOT_NAME,
        "short_name": TG_BOT_NAME,
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "icons": [],
    }
    return web.json_response(manifest, content_type="application/manifest+json")


@routes.get("/api/agent/ipv4")
async def handle_agent_ipv4(request: web.Request) -> web.StreamResponse:
    user = web_auth.get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    ips = _collect_ipv4_addresses()
    primary = _agent_ip()
    if primary in {"", "Loading...", "Unknown", "-"}:
        primary = ips[0] if ips else "-"

    return web.json_response({
        "primary": primary,
        "source_ip": primary,
        "agent_ip": primary,
        "ips": ips,
        "count": len(ips),
    })


@routes.get("/terminal")
async def handle_terminal_page(request: web.Request) -> web.StreamResponse:
    user = web_auth.get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")
    if not _is_admin(user):
        raise web.HTTPFound("/")

    lang = get_user_lang(int(user["id"]))
    prefill_ip = request.query.get("ip", "")
    custom_title = getattr(current_config, "WEB_METADATA", {}).get("title", "")
    page_title = custom_title if custom_title else f"{_('web_terminal_title', lang)} - {TG_BOT_NAME}"

    context = {
        "web_title": page_title,
        "web_brand_name": TG_BOT_NAME,
        "web_version": APP_VERSION,
        "web_terminal_title": _("web_terminal_title", lang),
        "web_terminal_ip": _("web_terminal_ip", lang),
        "web_terminal_user": _("web_terminal_user", lang),
        "web_terminal_pass": _("web_terminal_pass", lang),
        "web_terminal_connect": _("web_terminal_connect", lang),
        "web_terminal_disconnect": _("web_terminal_disconnect", lang),
        "web_terminal_port": _("web_terminal_port", lang),
        "web_terminal_auth_method": _("web_terminal_auth_method", lang),
        "web_terminal_password_auth": _("web_terminal_password_auth", lang),
        "web_terminal_key_auth": _("web_terminal_key_auth", lang),
        "web_terminal_key": _("web_terminal_key", lang),
        "web_terminal_key_select": _("web_terminal_key_select", lang),
        "web_terminal_remember": _("web_terminal_remember", lang),
        "web_terminal_status_disconnected": _("web_terminal_status_disconnected", lang),
        "web_terminal_status_connecting": _("web_terminal_status_connecting", lang),
        "web_terminal_status_connected": _("web_terminal_status_connected", lang),
        "web_terminal_error": _("web_terminal_error", lang),
        "prefill_ip": prefill_ip,
    }

    return _render_html_response("terminal.html", context, request)


@routes.get("/")
async def handle_dashboard(request: web.Request) -> web.StreamResponse:
    user = web_auth.get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")

    if web_auth.is_default_password_active(int(user["id"])):
        token = secrets.token_urlsafe(32)
        web_auth.RESET_TOKENS[token] = {"ts": time.time(), "user_id": int(user["id"])}
        raise web.HTTPFound(f"/reset_password?token={token}")

    user_id = int(user["id"])
    lang = get_user_lang(user_id)
    web_meta = getattr(current_config, "WEB_METADATA", {})
    meta_locked = web_meta.get("locked", False)
    custom_title = web_meta.get("title", "")
    page_title = custom_title if custom_title else f"{_('web_dashboard_title', lang)} - {TG_BOT_NAME}"

    all_nodes = await nodes_db.get_all_nodes()
    nodes_count = len(all_nodes)
    active_nodes = sum(
        1 for node in all_nodes.values() if time.time() - node.get("last_seen", 0) < current_config.NODE_OFFLINE_TIMEOUT
    )

    role = str(user.get("role", ROLE_USER))
    is_main_admin = _is_root(user)
    is_admin = _is_admin(user)

    if is_main_admin:
        role_text = _("web_role_owner", lang)
        role_badge_html = f'<span class="role-badge-owner hidden sm:inline-flex px-2 py-0.5 rounded text-[10px] border uppercase font-bold">{role_text}</span>'
    elif role == "admins":
        role_text = _("web_role_admins", lang)
        role_badge_html = f'<span class="role-badge-admin hidden sm:inline-flex px-2 py-0.5 rounded text-[10px] border uppercase font-bold">{role_text}</span>'
    else:
        role_text = _("web_role_users", lang)
        role_badge_html = f'<span class="role-badge-user hidden sm:inline-flex px-2 py-0.5 rounded text-[10px] border uppercase font-bold">{role_text}</span>'

    node_action_btn = ""
    settings_btn = ""
    if is_main_admin:
        node_action_btn = f"""<button onclick="openAddNodeModal()" class="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition shadow-lg shadow-blue-500/20"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>{_('web_add_node_section', lang)}</button>"""
        settings_btn = f'<a href="/settings" class="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400" title="{_("web_settings_button", lang)}"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg></a>'

    clean_version = APP_VERSION.lstrip("v")
    display_version = f"v{clean_version}"
    users_json = "null"
    nodes_json = "null"
    if is_admin:
        ulist = [
            {
                "id": uid,
                "name": shared_state.USER_NAMES.get(str(uid), f"ID: {uid}"),
                "role": (
                    shared_state.ALLOWED_USERS[uid].get("group", "users")
                    if isinstance(shared_state.ALLOWED_USERS[uid], dict)
                    else shared_state.ALLOWED_USERS[uid]
                ),
            }
            for uid in shared_state.ALLOWED_USERS
            if uid != ADMIN_USER_ID
        ]
        users_json = json.dumps(ulist)
        nlist = [
            {
                "token": encrypt_for_web(token),
                "name": node.get("name", "Unknown"),
                "ip": encrypt_for_web(node.get("ip", "Unknown")),
            }
            for token, node in all_nodes.items()
        ]
        nodes_json = json.dumps(nlist)

    vnc_nodes = [{"name": _("web_notif_global_group_agent", lang), "ip": _agent_ip()}]
    for node_token, node in all_nodes.items():
        ip = node.get("ip", "")
        if ip:
            vnc_nodes.append({"name": node.get("name", "Unknown"), "ip": ip})

    can_reset = traffic_module.can_reset_traffic()

    context = {
        "web_title": page_title,
        "web_favicon": web_meta.get("favicon", "/static/favicon.ico"),
        "web_meta_desc": web_meta.get("description", ""),
        "web_meta_keywords": web_meta.get("keywords", ""),
        "meta_locked": meta_locked,
        "web_brand_name": TG_BOT_NAME,
        "web_version": display_version,
        "pwa_version": getattr(current_config, "INSTALLED_VERSION", display_version) or display_version,
        "role_badge": role_badge_html,
        "vnc_nodes": vnc_nodes,
        "web_vnc_select_server": _("web_vnc_select_server", lang),
        "cache_ver": CACHE_VER,
        "web_dashboard_title": _("web_dashboard_title", lang),
        "user_avatar": _get_avatar_html(user),
        "user_name": user.get("first_name", "User"),
        "nodes_count": str(nodes_count),
        "active_nodes": str(active_nodes),
        "web_agent_stats_title": _("web_agent_stats_title", lang),
        "agent_ip": encrypt_for_web(_agent_ip()),
        "web_traffic_total": _("web_traffic_total", lang),
        "web_ips_title": _("web_ips_title", lang),
        "web_source_ip": _("web_source_ip", lang),
        "web_additional_ips": _("web_additional_ips", lang),
        "web_no_additional_ips": _("web_no_additional_ips", lang),
        "web_failed_to_load": _("web_failed_to_load", lang),
        "web_uptime": _("web_uptime", lang),
        "web_cpu": _("web_cpu", lang),
        "web_ram": _("web_ram", lang),
        "web_services_title": _("web_services_title", lang),
        "web_services_empty": _("web_services_empty", lang),
        "web_services_btn_start": _("web_services_btn_start", lang),
        "web_services_btn_stop": _("web_services_btn_stop", lang),
        "web_services_btn_restart": _("web_services_btn_restart", lang),
        "web_services_edit_title": _("web_services_edit_title", lang),
        "web_services_search": _("web_services_search", lang),
        "web_services_info_title": _("web_services_info_title", lang),
        "web_services_info_loading": _("web_services_info_loading", lang),
        "user_role_level": get_role_level(user_id),
        "web_disk": _("web_disk", lang),
        "web_rx": _("web_rx", lang),
        "web_tx": _("web_tx", lang),
        "web_download": _("web_download", lang),
        "web_upload": _("web_upload", lang),
        "web_node_mgmt_title": _("web_node_mgmt_title", lang),
        "web_logs_title": _("web_logs_title", lang),
        "web_logs_footer": _("web_logs_footer", lang),
        "web_loading": _("web_loading", lang),
        "web_nodes_loading": _("web_nodes_loading", lang),
        "web_logs_btn_bot": _("web_logs_btn_bot", lang),
        "web_logs_btn_sys": _("web_logs_btn_sys", lang),
        "node_action_btn": node_action_btn,
        "settings_btn": settings_btn,
        "web_footer_powered": _("web_footer_powered", lang),
        "web_hint_cpu_usage": _("web_hint_cpu_usage", lang),
        "web_hint_ram_usage": _("web_hint_ram_usage", lang),
        "web_hint_disk_usage": _("web_hint_disk_usage", lang),
        "web_hint_traffic_in": _("web_hint_traffic_in", lang),
        "web_hint_traffic_out": _("web_hint_traffic_out", lang),
        "web_add_node_section": _("web_add_node_section", lang),
        "web_node_name_placeholder": _("web_node_name_placeholder", lang),
        "web_create_btn": _("web_create_btn", lang),
        "web_node_token": _("web_node_token", lang),
        "web_node_cmd": _("web_node_cmd", lang),
        "web_copied": _("web_copied", lang),
        "web_resources_chart": _("web_resources_chart", lang),
        "web_network_chart": _("web_network_chart", lang),
        "web_token_label": _("web_token_label", lang),
        "web_stats_total": _("web_stats_total", lang),
        "web_stats_active": _("web_stats_active", lang),
        "web_notifications_title": _("web_notifications_title", lang),
        "web_clear_notifications": _("web_clear_notifications", lang),
        "web_node_details_title": _("web_node_details_title", lang),
        "web_clear_logs_btn": _("web_clear_logs_btn", lang),
        "web_logout": _("web_logout", lang),
        "web_access_denied": _("web_access_denied", lang),
        "web_logs_protected_desc": _("web_logs_protected_desc", lang),
        "web_node_last_seen_label": _("web_node_last_seen", lang),
        "web_node_traffic": _("web_node_traffic", lang),
        "web_reset_traffic_btn": _("web_reset_traffic_btn", lang),
        "web_reset_uptime": _("web_reset_uptime", lang),
        "user_role_js": build_user_role_js(role, user_id),
        "is_main_admin": is_main_admin,
        "reset_allowed": can_reset,
        "web_search_placeholder": _("web_search_placeholder", lang),
        "i18n_json": json.dumps({
            "web_cpu": _("web_cpu", lang),
            "web_ram": _("web_ram", lang),
            "web_no_nodes": _("web_no_nodes", lang),
            "web_loading": _("web_loading", lang),
            "web_error": _("web_error", lang, error=""),
            "web_conn_error": _("web_conn_error", lang, error=""),
            "web_log_empty": _("web_log_empty", lang),
            "web_access_denied": _("web_access_denied", lang),
            "web_copied": _("web_copied", lang),
            "web_no_notifications": _("web_no_notifications", lang),
            "web_notif_source_agent": _("web_notif_source_agent", lang),
            "web_notif_source_node": _("web_notif_source_node", lang),
            "web_clear_notifications": _("web_clear_notifications", lang),
            "web_notifications_cleared": _("web_notifications_cleared", lang),
            "modal_title_alert": _("modal_title_alert", lang),
            "modal_title_confirm": _("modal_title_confirm", lang),
            "web_clear_notif_confirm": _("web_clear_notifications", lang) + "?",
            "modal_btn_ok": _("modal_btn_ok", lang),
            "modal_btn_cancel": _("modal_btn_cancel", lang),
            "web_time_d": _("unit_day_short", lang),
            "web_time_h": _("unit_hour_short", lang),
            "web_time_m": _("unit_minute_short", lang),
            "unit_bytes": _("unit_bytes", lang),
            "unit_kb": _("unit_kb", lang),
            "unit_mb": _("unit_mb", lang),
            "unit_gb": _("unit_gb", lang),
            "unit_tb": _("unit_tb", lang),
            "unit_pb": _("unit_pb", lang),
            "unit_kbps": _("unit_kbps", lang),
            "unit_mbps": _("unit_mbps", lang),
            "unit_gbps": _("unit_gbps", lang),
            "web_haptics_on": _("web_haptics_on", lang),
            "web_haptics_off": _("web_haptics_off", lang),
            "web_search_nothing_found": _("web_search_nothing_found", lang),
            "web_node_modal_loading": _("web_node_modal_loading", lang),
            "web_node_status_online": _("web_node_status_online", lang),
            "web_node_last_seen": _("web_node_last_seen", lang),
            "web_node_traffic": _("web_node_traffic", lang),
            "web_nodes_monitor_current_uptime": _("web_nodes_monitor_current_uptime", lang),
            "web_nodes_monitor_last_outage": _("web_nodes_monitor_last_outage", lang),
            "web_nodes_monitor_last_reboot": _("web_nodes_monitor_last_reboot", lang),
            "web_nodes_monitor_total_uptime": _("web_nodes_monitor_total_uptime", lang),
            "web_nodes_monitor_total_downtime": _("web_nodes_monitor_total_downtime", lang),
            "web_nodes_monitor_internet_downtime": _("web_nodes_monitor_internet_downtime", lang),
            "web_nodes_monitor_physical_downtime": _("web_nodes_monitor_physical_downtime", lang),
            "web_nodes_monitor_outage_pending": _("web_nodes_monitor_outage_pending", lang),
            "web_nodes_monitor_outage_rebooting": _("web_nodes_monitor_outage_rebooting", lang),
            "web_avail_header": _("web_avail_header", lang),
            "web_avail_status": _("web_avail_status", lang),
            "web_avail_online": _("web_avail_online", lang),
            "web_avail_offline": _("web_avail_offline", lang),
            "web_agent_uptime_os": _("web_agent_uptime_os", lang),
            "web_agent_downtime": _("web_agent_downtime", lang),
            "web_label_cpu": _("web_label_cpu", lang),
            "web_label_ram": _("web_label_ram", lang),
            "web_label_disk": _("web_label_disk", lang),
            "web_label_status": _("web_label_status", lang),
            "web_label_rx": _("web_label_rx", lang),
            "web_label_tx": _("web_label_tx", lang),
            "modal_title_info": _("web_node_details_title", lang),
            "web_click_copy": _("web_click_copy", lang),
            "web_top_cpu": _("web_top_cpu", lang),
            "web_top_ram": _("web_top_ram", lang),
            "web_top_disk": _("web_top_disk", lang),
            "web_hint_traffic_in": _("web_hint_traffic_in", lang),
            "web_hint_traffic_out": _("web_hint_traffic_out", lang),
            "web_hint_uptime_bot_uptime": _("web_hint_uptime_bot_uptime", lang),
            "web_hint_uptime_bot_started": _("web_hint_uptime_bot_started", lang),
            "web_log_connecting": _("web_log_connecting", lang),
            "web_status_restart": _("web_status_restart", lang),
            "web_session_expired": _("web_session_expired", lang),
            "web_please_relogin": _("web_please_relogin", lang),
            "web_login_btn": _("web_login_btn", lang),
            "web_weak_conn": _("web_weak_conn", lang),
            "web_conn_problem": _("web_conn_problem", lang),
            "web_refresh_stream": _("web_refresh_stream", lang),
            "web_fatal_conn": _("web_fatal_conn", lang),
            "web_server_rebooting": _("web_server_rebooting", lang),
            "web_reloading_page": _("web_reloading_page", lang),
            "web_node_rename_success": _("web_node_rename_success", lang),
            "web_node_rename_error": _("web_node_rename_error", lang),
            "web_traffic_reset_confirm": _("web_traffic_reset_confirm", lang),
            "traffic_reset_done": _("web_traffic_reset_no_emoji", lang),
            "web_logs_empty_title": _("web_logs_empty_title", lang),
            "web_logs_empty_desc": _("web_logs_empty_desc", lang),
            "web_services_confirm_start": _("web_services_confirm_start", lang),
            "web_services_confirm_stop": _("web_services_confirm_stop", lang),
            "web_services_confirm_restart": _("web_services_confirm_restart", lang),
            "web_services_error": _("web_services_error", lang),
            "web_services_request_failed": _("web_services_request_failed", lang),
            "web_services_btn_add": _("web_services_btn_add", lang),
            "web_services_btn_remove": _("web_services_btn_remove", lang),
            "web_services_none_found": _("web_services_none_found", lang),
            "web_did_you_mean": _("web_did_you_mean", lang),
            "web_results": _("web_results", lang),
            "web_services_global_results": _("web_services_global_results", lang),
            "web_services_info_title": _("web_services_info_title", lang),
            "web_services_info_name": _("web_services_info_name", lang),
            "web_services_info_type": _("web_services_info_type", lang),
            "web_services_info_status": _("web_services_info_status", lang),
            "web_services_info_desc": _("web_services_info_desc", lang),
            "web_services_info_loading": _("web_services_info_loading", lang),
            "web_services_info_no_desc": _("web_services_info_no_desc", lang),
            "web_services_status_running": _("web_services_status_running", lang),
            "web_services_status_stopped": _("web_services_status_stopped", lang),
            "web_services_status_unknown": _("web_services_status_unknown", lang),
            "modal_title_error": _("modal_title_error", lang),
            "web_reset_uptime": _("web_reset_uptime", lang),
            "web_reset_uptime_confirm": _("web_reset_uptime_confirm", lang),
            "uptime_reset_success": _("uptime_reset_success", lang),
            "web_error_short": _("web_error_short", lang),
        }),
    }

    return _render_html_response("dashboard.html", context, request)


@routes.get("/nodes")
async def handle_nodes_monitor_page(request: web.Request) -> web.StreamResponse:
    user = web_auth.get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")

    user_id = int(user["id"])
    lang = get_user_lang(user_id)
    role = str(user.get("role", ROLE_USER))
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
        "pwa_version": getattr(current_config, "INSTALLED_VERSION", display_version) or display_version,
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
        "i18n_json": json.dumps({
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
            "web_nodes_monitor_current_uptime": _("web_nodes_monitor_current_uptime", lang),
            "web_nodes_monitor_last_outage": _("web_nodes_monitor_last_outage", lang),
            "web_nodes_monitor_last_reboot": _("web_nodes_monitor_last_reboot", lang),
            "web_nodes_monitor_total_uptime": _("web_nodes_monitor_total_uptime", lang),
            "web_nodes_monitor_total_downtime": _("web_nodes_monitor_total_downtime", lang),
            "web_nodes_monitor_internet_downtime": _("web_nodes_monitor_internet_downtime", lang),
            "web_nodes_monitor_physical_downtime": _("web_nodes_monitor_physical_downtime", lang),
            "web_nodes_monitor_outage_pending": _("web_nodes_monitor_outage_pending", lang),
            "web_nodes_monitor_outage_rebooting": _("web_nodes_monitor_outage_rebooting", lang),
            "web_avail_header": _("web_avail_header", lang),
            "web_avail_status": _("web_avail_status", lang),
            "web_avail_online": _("web_avail_online", lang),
            "web_avail_offline": _("web_avail_offline", lang),
        }),
    }

    return _render_html_response("nodes_monitor.html", context, request)


@routes.get("/settings")
async def handle_settings_page(request: web.Request) -> web.StreamResponse:
    user = web_auth.get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")

    user_id = int(user["id"])
    role = str(user.get("role", ROLE_USER))
    is_main_admin = _is_root(user)
    is_admin = _is_admin(user)
    lang = get_user_lang(user_id)
    user_alerts = shared_state.ALERTS_CONFIG.get(user_id, {})
    web_meta = getattr(current_config, "WEB_METADATA", {})
    meta_locked = web_meta.get("locked", False)
    users_json = "null"
    nodes_json = "null"

    if is_admin:
        ulist = [
            {
                "id": uid,
                "name": shared_state.USER_NAMES.get(str(uid), f"ID: {uid}"),
                "role": (
                    shared_state.ALLOWED_USERS[uid].get("group", "users")
                    if isinstance(shared_state.ALLOWED_USERS[uid], dict)
                    else shared_state.ALLOWED_USERS[uid]
                ),
            }
            for uid in shared_state.ALLOWED_USERS
            if uid != ADMIN_USER_ID
        ]
        users_json = json.dumps(ulist)
        all_nodes = await nodes_db.get_all_nodes()
        nlist = [
            {
                "token": encrypt_for_web(token),
                "name": node.get("name", "Unknown"),
                "ip": encrypt_for_web(node.get("ip", "Unknown")),
            }
            for token, node in all_nodes.items()
        ]
        nodes_json = json.dumps(nlist)

    can_reset = True
    keyboard_config_json = json.dumps(current_config.KEYBOARD_CONFIG)

    i18n_data = {
        "web_saving_btn": _("web_saving_btn", lang),
        "web_saved_btn": _("web_saved_btn", lang),
        "web_haptics_on": _("web_haptics_on", lang),
        "web_haptics_off": _("web_haptics_off", lang),
        "web_save_btn": _("web_save_btn", lang),
        "web_change_btn": _("web_change_btn", lang),
        "notifications_alert_name_res": _("notifications_alert_name_res", lang),
        "notifications_alert_name_logins": _("notifications_alert_name_logins", lang),
        "notifications_alert_name_downtime": _("notifications_alert_name_downtime", lang),
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "web_confirm_delete_user": _("web_confirm_delete_user", lang),
        "web_no_users": _("web_no_users", lang),
        "web_clear_logs_confirm": _("web_clear_logs_confirm", lang),
        "web_logs_cleared": _("web_logs_cleared", lang),
        "error_traffic_interval_low": _("error_traffic_interval_low", lang),
        "error_traffic_interval_high": _("error_traffic_interval_high", lang),
        "web_logs_clearing": _("web_logs_clearing", lang),
        "web_logs_cleared_alert": _("web_logs_cleared_alert", lang),
        "web_pass_changed": _("web_pass_changed", lang),
        "web_pass_mismatch": _("web_pass_mismatch", lang),
        "web_telegram_only_enabled": _("web_telegram_only_enabled", lang),
        "web_telegram_only_disabled": _("web_telegram_only_disabled", lang),
        "web_clear_bot_confirm": _("web_clear_bot_confirm", lang),
        "web_clear_node_confirm": _("web_clear_node_confirm", lang),
        "web_clear_all_confirm": _("web_clear_all_confirm", lang),
        "web_logs_cleared_bot": _("web_logs_cleared_bot", lang),
        "web_logs_cleared_node": _("web_logs_cleared_node", lang),
        "web_logs_cleared_all": _("web_logs_cleared_all", lang),
        "modal_title_alert": _("modal_title_alert", lang),
        "modal_title_confirm": _("modal_title_confirm", lang),
        "modal_title_prompt": _("modal_title_prompt", lang),
        "modal_btn_ok": _("modal_btn_ok", lang),
        "modal_btn_cancel": _("modal_btn_cancel", lang),
        "web_kb_active": _("web_kb_active", lang),
        "web_kb_all_on_alert": _("web_kb_all_on_alert", lang),
        "web_kb_all_off_alert": _("web_kb_all_off_alert", lang),
        "web_no_nodes": _("web_no_nodes", lang),
        "web_copied": _("web_copied", lang),
        "web_kb_cat_monitoring": _("web_kb_cat_monitoring", lang),
        "web_kb_cat_security": _("web_kb_cat_security", lang),
        "web_kb_cat_management": _("web_kb_cat_management", lang),
        "web_kb_cat_system": _("web_kb_cat_system", lang),
        "web_kb_cat_tools": _("web_kb_cat_tools", lang),
        "web_update_checking": _("web_update_checking", lang),
        "web_update_available_title": _("web_update_available_title", lang),
        "web_update_info": _("web_update_info", lang),
        "web_update_uptodate": _("web_update_uptodate", lang),
        "web_update_started": _("web_update_started", lang),
        "web_update_error": _("web_update_error", lang),
        "web_no_notifications": _("web_no_notifications", lang),
        "web_notif_source_agent": _("web_notif_source_agent", lang),
        "web_notif_source_node": _("web_notif_source_node", lang),
        "web_clear_notifications": _("web_clear_notifications", lang),
        "web_clear_notif_confirm": _("web_clear_notifications", lang) + "?",
        "web_sessions_title": _("web_sessions_title", lang),
        "web_session_current": _("web_session_current", lang),
        "web_session_revoke": _("web_session_revoke", lang),
        "web_logout": _("web_logout", lang),
        "web_ip": _("web_ip", lang),
        "web_device": _("web_device", lang),
        "web_last_active": _("web_last_active", lang),
        "web_sessions_revoked_alert": _("web_sessions_revoked_alert", lang),
        "web_session_current_label": _("web_session_current_label", lang),
        "web_sessions_revoke_all": _("web_sessions_revoke_all", lang),
        "web_update_placeholder": _("web_update_placeholder", lang),
        "web_update_check_btn": _("web_update_check_btn", lang),
        "web_update_do_btn": _("web_update_do_btn", lang),
        "web_notifications_title": _("web_notifications_title", lang),
        "web_fill_field": _("web_fill_field", lang),
        "web_conn_error_short": _("web_conn_error_short", lang),
        "web_error_short": _("web_error_short", lang),
        "web_success": _("web_success", lang),
        "web_no_sessions": _("web_no_sessions", lang),
        "web_error_loading_sessions": _("web_error_loading_sessions", lang),
        "web_kb_enable_all": _("web_kb_enable_all", lang),
        "web_kb_disable_all": _("web_kb_disable_all", lang),
        "web_click_copy": _("web_click_copy", lang),
        "web_server_name_placeholder": _("web_server_name_placeholder", lang),
        "web_session_expired": _("web_session_expired", lang),
        "web_please_relogin": _("web_please_relogin", lang),
        "web_login_btn": _("web_login_btn", lang),
        "web_add_user_prompt": _("web_add_user_prompt", lang),
        "web_weak_conn": _("web_weak_conn", lang),
        "web_conn_problem": _("web_conn_problem", lang),
        "web_refresh_stream": _("web_refresh_stream", lang),
        "web_fatal_conn": _("web_fatal_conn", lang),
        "web_server_rebooting": _("web_server_rebooting", lang),
        "web_reloading_page": _("web_reloading_page", lang),
        "web_node_rename_success": _("web_node_rename_success", lang),
        "web_node_rename_error": _("web_node_rename_error", lang),
        "web_traffic_reset_confirm": _("web_traffic_reset_confirm", lang),
        "web_traffic_reset_no_emoji": _("web_traffic_reset_no_emoji", lang),
        "web_update_started_alert": _("web_update_started_alert", lang),
        "web_logs_cleared_alert": _("web_logs_cleared_alert", lang),
        "web_meta_lock_confirm": _("web_meta_lock_confirm", lang),
        "web_seo_btn_default": _("web_seo_btn_default", lang),
        "web_seo_paste_help": _("web_seo_paste_help", lang),
        "web_image_pasted": _("web_image_pasted", lang),
        "web_image_uploaded": _("web_image_uploaded", lang),
        "web_meta_success": _("web_meta_success", lang),
        "web_meta_locked_alert": _("web_meta_locked_alert", lang),
        "web_notifications_cleared": _("web_notifications_cleared", lang),
        "web_node_delete_confirm": _("web_node_delete_confirm", lang),
        "modal_title_info": _("modal_title_info", lang),
        "notif_node_settings_title": _("web_notif_node_settings_title", lang),
    }
    for btn_key, conf_key in BTN_CONFIG_MAP.items():
        i18n_data[f"lbl_{conf_key}"] = _(btn_key, lang)

    custom_title = web_meta.get("title", "")
    page_title = f"{_('web_settings_page_title', lang)} - {TG_BOT_NAME}"
    if custom_title:
        page_title = f"{_('web_settings_page_title', lang)} - {custom_title}"

    context = {
        "web_title": page_title,
        "web_favicon": web_meta.get("favicon", "/static/favicon.ico"),
        "web_custom_title": web_meta.get("title", ""),
        "web_meta_desc": web_meta.get("description", ""),
        "web_meta_keywords": web_meta.get("keywords", ""),
        "meta_locked": meta_locked,
        "web_seo_btn_short": _("web_seo_btn_short", lang),
        "web_seo_btn_long": _("web_seo_btn_long", lang),
        "web_seo_modal_title": _("web_seo_modal_title", lang),
        "web_seo_favicon_label": _("web_seo_favicon_label", lang),
        "web_seo_title_label": _("web_seo_title_label", lang),
        "web_seo_desc_label": _("web_seo_desc_label", lang),
        "web_seo_keywords_label": _("web_seo_keywords_label", lang),
        "web_seo_lock_label": _("web_seo_lock_label", lang),
        "web_seo_lock_desc": _("web_seo_lock_desc", lang),
        "txt_seo_default": _("web_seo_btn_default", lang),
        "txt_seo_paste": _("web_seo_paste_help", lang),
        "web_brand_name": TG_BOT_NAME,
        "user_name": user.get("first_name"),
        "user_avatar": _get_avatar_html(user),
        "users_data_json": users_json,
        "nodes_data_json": nodes_json,
        "keyboard_config_json": keyboard_config_json,
        "val_cpu": str(current_config.CPU_THRESHOLD),
        "val_ram": str(current_config.RAM_THRESHOLD),
        "val_disk": str(current_config.DISK_THRESHOLD),
        "val_traffic": str(current_config.TRAFFIC_INTERVAL),
        "val_services": str(getattr(current_config, "SERVICES_INTERVAL", 5)),
        "val_ping": str(getattr(current_config, "PING_INTERVAL", 30)),
        "val_timeout": str(current_config.NODE_OFFLINE_TIMEOUT),
        "web_settings_page_title": _("web_settings_page_title", lang),
        "web_back": _("web_back", lang),
        "web_notif_section": _("web_notif_section", lang),
        "notifications_alert_name_res": _("notifications_alert_name_res", lang),
        "notifications_alert_name_logins": _("notifications_alert_name_logins", lang),
        "notifications_alert_name_bans": _("notifications_alert_name_bans", lang),
        "notifications_alert_name_downtime": _("notifications_alert_name_downtime", lang),
        "web_notif_btn_global": _("web_notif_btn_global", lang),
        "web_notif_btn_global_subtitle": _("web_notif_btn_global_subtitle", lang),
        "web_notif_btn_nodes": _("web_notif_btn_nodes", lang),
        "web_notif_btn_nodes_subtitle": _("web_notif_btn_nodes_subtitle", lang),
        "web_notif_node_label": _("web_notif_node_label", lang),
        "web_notif_global_group_agent": _("web_notif_global_group_agent", lang),
        "web_notif_global_group_nodes": _("web_notif_global_group_nodes", lang),
        "web_notif_nodes_list_title": _("web_notif_nodes_list_title", lang),
        "web_notif_node_settings_title": _("web_notif_node_settings_title", lang),
        "web_notif_menu_desc": _("web_notif_menu_desc", lang),
        "web_save_btn": _("web_save_btn", lang),
        "web_users_section": _("web_users_section", lang),
        "web_add_user_btn": _("web_add_user_btn", lang),
        "web_user_id": _("web_user_id", lang),
        "web_user_name": _("web_user_name", lang),
        "web_user_role": _("web_user_role", lang),
        "web_user_action": _("web_user_action", lang),
        "web_add_node_section": _("web_add_node_section", lang),
        "web_node_name_placeholder": _("web_node_name_placeholder", lang),
        "web_no_users": _("web_no_users", lang),
        "web_create_btn": _("web_create_btn", lang),
        "web_node_token": _("web_node_token", lang),
        "web_node_cmd": _("web_node_cmd", lang),
        "web_sys_settings_section": _("web_sys_settings_section", lang),
        "web_thresholds_title": _("web_thresholds_title", lang),
        "web_intervals_title": _("web_intervals_title", lang),
        "web_logs_mgmt_title": _("web_logs_mgmt_title", lang),
        "web_cpu_threshold": _("web_cpu_threshold", lang),
        "web_ram_threshold": _("web_ram_threshold", lang),
        "web_disk_threshold": _("web_disk_threshold", lang),
        "web_traffic_interval": _("web_traffic_interval", lang),
        "web_services_interval": _("web_services_interval", lang),
        "web_ping_interval": _("web_ping_interval", lang),
        "web_node_timeout": _("web_node_timeout", lang),
        "web_clear_logs_btn": _("web_clear_logs_btn", lang),
        "web_reset_traffic_btn": _("web_reset_traffic_btn", lang),
        "web_security_section": _("web_security_section", lang),
        "web_telegram_only_tooltip": _("web_telegram_only_tooltip", lang),
        "web_telegram_only_notice": _("web_telegram_only_notice", lang),
        "web_change_password_title": _("web_change_password_title", lang),
        "web_current_password": _("web_current_password", lang),
        "web_new_password": _("web_new_password", lang),
        "web_confirm_password": _("web_confirm_password", lang),
        "web_change_btn": _("web_change_btn", lang),
        "web_hint_cpu_threshold": _("web_hint_cpu_threshold", lang),
        "web_hint_ram_threshold": _("web_hint_ram_threshold", lang),
        "web_hint_disk_threshold": _("web_hint_disk_threshold", lang),
        "web_hint_traffic_interval": _("web_hint_traffic_interval", lang),
        "web_hint_services_interval": _("web_hint_services_interval", lang),
        "web_hint_ping_interval": _("web_hint_ping_interval", lang),
        "web_hint_node_timeout": _("web_hint_node_timeout", lang),
        "web_keyboard_title": _("web_keyboard_title", lang),
        "web_node_mgmt_title": _("web_node_mgmt_title", lang),
        "web_kb_desc": _("web_kb_desc", lang),
        "web_kb_btn_config": _("web_kb_btn_config", lang),
        "web_kb_enable_all": _("web_kb_enable_all", lang),
        "web_kb_disable_all": _("web_kb_disable_all", lang),
        "web_kb_modal_title": _("web_kb_modal_title", lang),
        "web_kb_done": _("web_kb_done", lang),
        "web_version": APP_VERSION.lstrip("v"),
        "cache_ver": CACHE_VER,
        "web_update_section": _("web_update_section", lang),
        "web_update_placeholder": _("web_update_placeholder", lang),
        "web_update_check_btn": _("web_update_check_btn", lang),
        "web_update_do_btn": _("web_update_do_btn", lang),
        "web_notifications_title": _("web_notifications_title", lang),
        "web_clear_notifications": _("web_clear_notifications", lang),
        "web_notifications_cleared": _("web_notifications_cleared", lang),
        "web_logout": _("web_logout", lang),
        "web_sessions_title": _("web_sessions_title", lang),
        "web_sessions_view_all": _("web_sessions_view_all", lang),
        "web_sessions_revoke_all": _("web_sessions_revoke_all", lang),
        "web_sessions_modal_title": _("web_sessions_modal_title", lang),
        "user_role_js": build_user_role_js(role, user_id),
        "is_main_admin": is_main_admin,
        "reset_allowed": can_reset,
        "check_resources": "checked" if user_alerts.get("resources", False) else "",
        "check_logins": "checked" if user_alerts.get("logins", False) else "",
        "check_bans": "checked" if user_alerts.get("bans", False) else "",
        "check_downtime": "checked" if user_alerts.get("downtime", False) else "",
        "user_alerts": user_alerts,
        "user_alerts_json": json.dumps(user_alerts),
        "i18n_json": json.dumps(i18n_data),
    }

    return _render_html_response("settings.html", context, request)


@routes.get("/login")
async def handle_login_page(request: web.Request) -> web.StreamResponse:
    if web_auth.get_current_user(request):
        raise web.HTTPFound("/")

    if web_auth.BOT_USERNAME_CACHE is None:
        try:
            bot = request.app.get("bot")
            if bot:
                me = await bot.get_me()
                web_auth.BOT_USERNAME_CACHE = me.username or ""
        except Exception:
            web_auth.BOT_USERNAME_CACHE = ""

    lang_cookie = request.cookies.get("guest_lang", DEFAULT_LANGUAGE)
    lang = lang_cookie if lang_cookie in ["ru", "en"] else DEFAULT_LANGUAGE
    web_meta = getattr(current_config, "WEB_METADATA", {})
    custom_title = web_meta.get("title", "")
    page_title = custom_title if custom_title else TG_BOT_NAME
    keys = [
        "web_error",
        "web_conn_error",
        "modal_title_alert",
        "modal_title_confirm",
        "modal_title_prompt",
        "modal_btn_ok",
        "modal_btn_cancel",
        "login_cookie_title",
        "login_cookie_text",
        "login_cookie_btn",
        "login_support_title",
        "login_support_desc",
        "login_github_tooltip",
        "login_support_tooltip",
        "web_title",
        "web_current_password",
        "web_login_btn",
        "login_forgot_pass",
        "login_secure_gateway",
        "login_pass_btn",
        "login_back_magic",
        "login_or",
        "login_reset_title",
        "login_reset_desc",
        "login_btn_send_link",
        "login_btn_back",
        "btn_back",
        "login_support_btn_pay",
        "login_link_sent_title",
        "login_link_sent_desc",
        "reset_success_title",
        "reset_success_desc",
        "login_error_user_not_found",
        "web_default_pass_alert",
        "web_brand_name",
        "login_secure_gateway",
        "login_telegram_id_label",
        "login_via_telegram_btn",
    ]
    i18n_all: dict[str, dict[str, str]] = {}
    for locale in ["ru", "en"]:
        localized = {key: _(key, locale) for key in keys}
        localized["web_error"] = _("web_error", locale, error="")
        localized["web_conn_error"] = _("web_conn_error", locale, error="")
        i18n_all[locale] = localized

    current_data = i18n_all.get(lang, i18n_all["en"])
    injection = f"{json.dumps(current_data)};\n        const I18N_ALL = {json.dumps(i18n_all)}"
    alert = ""
    if web_auth.is_default_password_active(ADMIN_USER_ID):
        alert = f'<div class="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/50 rounded-xl flex items-start gap-3"><svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-yellow-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg><span class="text-xs text-yellow-200 font-medium" data-i18n="web_default_pass_alert">{_("web_default_pass_alert", lang)}</span></div>'

    context = {
        "web_title": page_title,
        "web_favicon": web_meta.get("favicon", "/static/favicon.ico"),
        "web_meta_desc": web_meta.get("description", ""),
        "web_meta_keywords": web_meta.get("keywords", ""),
        "default_pass_alert": alert,
        "error_block": "",
        "bot_username": web_auth.BOT_USERNAME_CACHE or "",
        "web_version": CACHE_VER,
        "current_lang": lang,
        "i18n_json": injection,
        "login_telegram_id_label": _("login_telegram_id_label", lang),
        "login_via_telegram_btn": _("login_via_telegram_btn", lang),
    }

    template = JINJA_ENV.get_template("login.html")
    response = web.Response(text=template.render(**context), content_type="text/html")
    if hasattr(web_auth, "_set_csrf_cookie"):
        web_auth._set_csrf_cookie(response, request)
    return response


@routes.get("/reset_password")
async def handle_reset_page_render(request: web.Request) -> web.StreamResponse:
    token = request.query.get("token")
    if not token or token not in web_auth.RESET_TOKENS:
        return web.Response(text="Expired", status=403)
    if time.time() - web_auth.RESET_TOKENS[token]["ts"] > web_auth.RESET_TOKEN_TTL:
        del web_auth.RESET_TOKENS[token]
        return web.Response(text="Expired", status=403)

    lang = DEFAULT_LANGUAGE
    web_meta = getattr(current_config, "WEB_METADATA", {})
    custom_title = web_meta.get("title", "")
    page_title = custom_title if custom_title else f"Reset Password - {TG_BOT_NAME}"
    i18n_data = {
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "modal_title_alert": _("modal_title_alert", lang),
        "modal_title_confirm": _("modal_title_confirm", lang),
        "modal_title_prompt": _("modal_title_prompt", lang),
        "modal_btn_ok": _("modal_btn_ok", lang),
        "modal_btn_cancel": _("modal_btn_cancel", lang),
        "web_brand_name": _("web_brand_name", lang),
        "reset_page_title": _("login_reset_title", lang),
        "web_new_password": _("web_new_password", lang),
        "web_confirm_password": _("web_confirm_password", lang),
        "web_save_btn": _("web_save_btn", lang),
        "pass_strength_weak": _("pass_strength_weak", lang),
        "pass_strength_fair": _("pass_strength_fair", lang),
        "pass_strength_good": _("pass_strength_good", lang),
        "pass_strength_strong": _("pass_strength_strong", lang),
        "pass_hint_title": _("pass_hint_title", lang),
        "pass_req_length": _("pass_req_length", lang),
        "pass_req_num": _("pass_req_num", lang),
        "pass_match_error": _("pass_match_error", lang),
        "pass_is_empty": _("pass_is_empty", lang),
        "web_redirecting": _("web_redirecting", lang),
        "web_logging_in": _("web_logging_in", lang),
    }
    context = {
        "web_title": page_title,
        "web_favicon": web_meta.get("favicon", "/static/favicon.ico"),
        "web_meta_desc": web_meta.get("description", ""),
        "web_meta_keywords": web_meta.get("keywords", ""),
        "web_version": CACHE_VER,
        "token": token,
        "i18n_json": json.dumps(i18n_data),
    }
    template = JINJA_ENV.get_template("reset_password.html")
    response = web.Response(text=template.render(**context), content_type="text/html")
    if hasattr(web_auth, "_set_csrf_cookie"):
        web_auth._set_csrf_cookie(response, request)
    return response


__all__ = [
    "routes",
    "JINJA_ENV",
    "TEMPLATE_DIR",
    "handle_dashboard",
    "handle_settings_page",
    "handle_login_page",
    "handle_nodes_monitor_page",
    "handle_terminal_page",
    "handle_reset_page_render",
]
