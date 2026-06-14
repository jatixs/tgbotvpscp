from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import time
from collections import deque
from typing import Any, Final

import aiohttp
from aiohttp import web

from .. import config as current_config
from .. import nodes_db, shared_state
from ..config import BASE_DIR, DEFAULT_LANGUAGE, DEPLOY_MODE
from ..i18n import get_user_lang
from ..utils import decrypt_for_web, encrypt_for_web, get_host_path, get_node_uptime_snapshot
from .auth import COOKIE_NAME, SERVER_SESSIONS, get_current_user
from ..rbac import is_admin as _is_admin
# Lazy imports: traffic_module and services are loaded on-demand
# from modules import traffic as traffic_module
# from modules.services import get_all_services_status

routes = web.RouteTableDef()

KEEPALIVE_INTERVAL: Final[int] = 25
SSE_ACCEPT_HEADER: Final[str] = "text/event-stream"


def _build_plain_api_notice(path: str, stream_kind: str = "SSE") -> web.Response:
    message = (
        f"Это обычный HTTP/HTTPS-запрос.\n"
        f"Маршрут {path} является внутренним {stream_kind}-endpoint и не предназначен для прямого открытия в браузере.\n"
        f"Используйте WebUI или специализированный клиент ({SSE_ACCEPT_HEADER})."
    )
    return web.Response(text=message, content_type="text/plain", status=406)


def _is_sse_request(request: web.Request) -> bool:
    accept_header = request.headers.get("Accept", "")
    return SSE_ACCEPT_HEADER in accept_header.lower()


def _build_websocket_notice(path: str) -> web.Response:
    message = (
        f"Это обычный HTTP/HTTPS-запрос.\n"
        f"Маршрут {path} является внутренним WebSocket-endpoint и не предназначен для прямого открытия в браузере.\n"
        "Используйте WebUI или WebSocket-клиент с Upgrade: websocket."
    )
    return web.Response(text=message, content_type="text/plain", status=426)


def _session_expired(current_token: str | None) -> bool:
    return bool(current_token and current_token not in SERVER_SESSIONS)


def _encrypt_node_stats_for_web(stats: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(stats or {})
    ping = payload.get("ping")
    payload["ping"] = encrypt_for_web(ping) if ping is not None else ""
    return payload


def _encrypt_node_services_for_web(services: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "name": encrypt_for_web(service.get("name", "")),
            "type": encrypt_for_web(service.get("type", "systemd")),
            "status": encrypt_for_web(service.get("status", "")),
        }
        for service in (services or [])
    ]


def _safe_agent_ip() -> str:
    return getattr(shared_state, "AGENT_IP_CACHE", "Loading...")


def _safe_agent_ping() -> str:
    return getattr(shared_state, "AGENT_PING_CACHE", "n/a")


def _normalize_host(host: str) -> str:
    raw_host = host.strip().strip("[]")
    try:
        return str(ipaddress.ip_address(raw_host))
    except ValueError:
        return raw_host


def _is_local_terminal_stats_target(host: str, agent_ip: str) -> bool:
    normalized_host = _normalize_host(host)
    if normalized_host in {_normalize_host(agent_ip), "127.0.0.1", "localhost"}:
        return True

    try:
        return ipaddress.ip_address(normalized_host).is_unspecified
    except ValueError:
        return False


async def _is_allowed_terminal_host(host: str) -> bool:
    normalized_host = _normalize_host(host)
    if normalized_host == "127.0.0.1":
        return True

    agent_ip = _safe_agent_ip()
    if agent_ip not in {"", "Loading...", "Unknown"} and normalized_host == _normalize_host(agent_ip):
        return True

    all_nodes = await nodes_db.get_all_nodes()
    allowed_node_ips = {
        _normalize_host(str(node.get("ip", "")).strip())
        for node in all_nodes.values()
        if str(node.get("ip", "")).strip() and str(node.get("ip", "")).strip() != "Unknown"
    }
    return normalized_host in allowed_node_ips


def _get_top_processes(metric: str) -> list[str]:
    import psutil

    def sizeof_fmt(num: float) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f} {unit}"
            num /= 1024.0
        return f"{num:.1f} PB"

    try:
        attrs = ["pid", "name", "cpu_percent", "memory_percent"]
        if metric == "disk":
            attrs.append("io_counters")

        processes: list[dict[str, Any]] = []
        for proc in psutil.process_iter(attrs):
            try:
                info = proc.info
                info["name"] = str(info.get("name", ""))[:15]
                processes.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if metric == "cpu":
            sorted_processes = sorted(processes, key=lambda p: p.get("cpu_percent", 0), reverse=True)[:5]
            return [f"{p['name']} ({p.get('cpu_percent', 0)}%)" for p in sorted_processes]

        if metric == "ram":
            sorted_processes = sorted(processes, key=lambda p: p.get("memory_percent", 0), reverse=True)[:5]
            return [f"{p['name']} ({p.get('memory_percent', 0):.1f}%)" for p in sorted_processes]

        if metric == "disk":
            def get_io(proc: dict[str, Any]) -> int:
                io = proc.get("io_counters")
                return int(io.read_bytes + io.write_bytes) if io else 0

            sorted_processes = sorted(processes, key=get_io, reverse=True)[:5]
            return [f"{p['name']} ({sizeof_fmt(get_io(p))})" for p in sorted_processes]

        return []
    except Exception:
        logging.exception("Failed to gather top processes")
        return []


async def _write_sse(response: web.StreamResponse, event: str, data: Any) -> None:
    payload = json.dumps(data)
    await response.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))


@routes.get("/api/events")
async def handle_sse_stream(request: web.Request) -> web.StreamResponse:
    if not _is_sse_request(request):
        return _build_plain_api_notice(request.path)

    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.Response(status=403)

    current_token = request.cookies.get(COOKIE_NAME)
    response = web.StreamResponse(status=200, reason="OK")
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    await response.prepare(request)

    shutdown_event = request.app.get("shutdown_event")
    user_id = int(user["id"])

    import psutil

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

            current_stats: dict[str, Any] = {
                "cpu": 0,
                "ram": 0,
                "disk": 0,
                "ip": encrypt_for_web(_safe_agent_ip()),
                "ping": encrypt_for_web(_safe_agent_ping()),
                "net_sent": 0,
                "net_recv": 0,
                "boot_time": 0,
                "bot_start_time": shared_state.AGENT_BOT_START_TIME,
                "agent_availability": {
                    "current_uptime_since": shared_state.AGENT_AVAILABILITY.get("status_since", shared_state.AGENT_BOT_START_TIME),
                    "last_downtime_at": shared_state.AGENT_AVAILABILITY.get("last_downtime_at", 0),
                    "last_reboot_at": shared_state.AGENT_AVAILABILITY.get("last_reboot_at", 0),
                    "total_online_secs": shared_state.AGENT_AVAILABILITY.get("total_online_seconds", 0),
                    "total_downtime_secs": shared_state.AGENT_AVAILABILITY.get("total_downtime_seconds", 0),
                    "internet_downtime_secs": shared_state.AGENT_AVAILABILITY.get("total_internet_downtime_seconds", 0),
                    "physical_downtime_secs": max(0.0, float(shared_state.AGENT_AVAILABILITY.get("total_downtime_seconds", 0)) - float(shared_state.AGENT_AVAILABILITY.get("total_internet_downtime_seconds", 0))),
                },
            }

            try:
                from modules import traffic as traffic_module
                rx_total, tx_total = traffic_module.get_current_traffic_total()
                net_if = psutil.net_io_counters(pernic=True)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage(get_host_path("/"))
                freq = psutil.cpu_freq()
                proc_cpu = await asyncio.to_thread(_get_top_processes, "cpu")
                proc_ram = await asyncio.to_thread(_get_top_processes, "ram")
                proc_disk = await asyncio.to_thread(_get_top_processes, "disk")
                current_stats.update(
                    {
                        "net_sent": tx_total,
                        "net_recv": rx_total,
                        "boot_time": psutil.boot_time(),
                        "ram_total": mem.total,
                        "ram_used": mem.total - mem.available,
                        "disk_total": disk.total,
                        "disk_free": disk.free,
                        "cpu_freq": freq.current if freq else 0,
                        "process_cpu": proc_cpu,
                        "process_ram": proc_ram,
                        "process_disk": proc_disk,
                        "interfaces": {key: value._asdict() for key, value in net_if.items()},
                    }
                )
            except Exception:
                logging.debug("Agent stats collection skipped", exc_info=True)

            if shared_state.AGENT_HISTORY:
                latest = shared_state.AGENT_HISTORY[-1]
                current_stats.update({"cpu": latest["c"], "ram": latest["r"]})
                try:
                    current_stats["disk"] = psutil.disk_usage(get_host_path("/")).percent
                except Exception:
                    pass

            await _write_sse(
                response,
                "agent_stats",
                {"stats": current_stats, "history": list(shared_state.AGENT_HISTORY)},
            )

            all_nodes = await nodes_db.get_all_nodes()
            nodes_data: list[dict[str, Any]] = []
            now = time.time()
            for token, node in all_nodes.items():
                last_seen = node.get("last_seen", 0)
                is_restarting = node.get("is_restarting", False)
                status = "restarting" if is_restarting else "online" if now - last_seen < current_config.NODE_OFFLINE_TIMEOUT else "offline"
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
                        "net_rx_speed": stats.get("net_rx_speed", 0),
                        "net_tx_speed": stats.get("net_tx_speed", 0),
                    }
                )
            await _write_sse(response, "nodes_list", {"nodes": nodes_data})

            user_alerts = shared_state.ALERTS_CONFIG.get(user_id, {})
            user_lang = get_user_lang(user_id)
            filtered_notifications: list[dict[str, Any]] = []
            for notification in list(shared_state.WEB_NOTIFICATIONS):
                if user_alerts.get(notification["type"], False):
                    notif_copy = notification.copy()
                    text_map = notif_copy.get("text_map")
                    if isinstance(text_map, dict):
                        localized_text = text_map.get(user_lang) or text_map.get(DEFAULT_LANGUAGE)
                        if localized_text:
                            notif_copy["text"] = localized_text
                        del notif_copy["text_map"]
                    filtered_notifications.append(notif_copy)

            last_read = shared_state.WEB_USER_LAST_READ.get(user_id, 0)
            unread_count = sum(1 for item in filtered_notifications if item["time"] > last_read)
            await _write_sse(
                response,
                "notifications",
                {"notifications": filtered_notifications, "unread_count": unread_count},
            )

            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=3.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        if "closing transport" not in str(exc) and "'NoneType' object" not in str(exc):
            logging.error("SSE stream error: %s", exc)

    return response


@routes.get("/api/events/logs")
async def handle_sse_logs(request: web.Request) -> web.StreamResponse:
    if not _is_sse_request(request):
        return _build_plain_api_notice(request.path)

    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.Response(status=403)

    log_type = request.query.get("type", "bot")
    response = web.StreamResponse(status=200, reason="OK")
    response.headers["Content-Type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    response.enable_compression(False)
    await response.prepare(request)

    shutdown_event = request.app.get("shutdown_event")
    journal_bin = ["journalctl"]
    if DEPLOY_MODE == "docker" and current_config.INSTALL_MODE == "root":
        if os.path.exists("/host/usr/bin/journalctl"):
            journal_bin = ["chroot", "/host", "/usr/bin/journalctl"]
        elif os.path.exists("/host/bin/journalctl"):
            journal_bin = ["chroot", "/host", "/bin/journalctl"]

    async def fetch_sys_logs(cursor: str | None = None, lines: int | None = None) -> tuple[list[str], str | None]:
        cmd = journal_bin + ["--no-pager", "--show-cursor"]
        if cursor:
            cmd.extend(["--after-cursor", cursor])
        elif lines:
            cmd.extend(["-n", str(lines)])
        else:
            cmd.extend(["-n", "300"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logging.error("Journalctl error: %s", stderr.decode("utf-8", errors="ignore"))
                return (["Error: Failed to fetch system logs"], cursor)

            raw_output = stdout.decode("utf-8", errors="ignore").strip().split("\n")
            log_lines: list[str] = []
            new_cursor = cursor
            for line in raw_output:
                if line.startswith("__CURSOR="):
                    new_cursor = line.split("=", 1)[1]
                elif line.strip().startswith("-- cursor:"):
                    continue
                elif line:
                    log_lines.append(line)
            return (log_lines, new_cursor)
        except Exception as exc:
            logging.error("Exception in fetch_sys_logs: %s", exc)
            return (["Error: Failed to execute log retrieval"], cursor)

    bot_log_path = os.path.join(BASE_DIR, "logs", "bot", "bot.log")
    last_pos = 0
    sys_cursor: str | None = None
    last_sent_lines_hash: int | None = None
    last_activity = time.time()

    if log_type == "bot":
        clean_lines: list[str] = []
        if os.path.exists(bot_log_path):
            try:
                def read_history() -> tuple[list[str], int]:
                    with open(bot_log_path, "r", encoding="utf-8", errors="ignore") as handle:
                        lines = list(deque(handle, 300))
                        handle.seek(0, 2)
                        return (lines, handle.tell())

                history_lines, last_pos = await asyncio.to_thread(read_history)
                clean_lines = [line.rstrip() for line in history_lines] if history_lines else []
            except Exception as exc:
                logging.error("Error reading bot history: %s", exc)

        try:
            await _write_sse(response, "logs", {"logs": clean_lines})
            await response.drain()
            last_activity = time.time()
        except Exception as exc:
            if "closing transport" in str(exc):
                return response
            raise

    elif log_type == "sys":
        try:
            history_lines, sys_cursor = await fetch_sys_logs(lines=300)
        except Exception as exc:
            logging.error("Error fetching sys logs: %s", exc)
            history_lines = ["Error: System logs temporarily unavailable"]

        try:
            await _write_sse(response, "logs", {"logs": history_lines or []})
            await response.drain()
            last_activity = time.time()
        except Exception as exc:
            if "closing transport" in str(exc):
                return response
            raise

    try:
        while True:
            if shared_state.IS_RESTARTING:
                await response.write(b"event: shutdown\ndata: restarting\n\n")
                await response.drain()
                break

            if request.transport is None or request.transport.is_closing():
                break

            data_sent = False
            if log_type == "bot" and os.path.exists(bot_log_path):
                def read_updates(cursor: int) -> tuple[list[str], int]:
                    new_data: list[str] = []
                    new_cursor = cursor
                    try:
                        current_size = os.path.getsize(bot_log_path)
                        if current_size < cursor:
                            cursor = 0
                        if current_size > cursor:
                            with open(bot_log_path, "r", encoding="utf-8", errors="ignore") as handle:
                                handle.seek(cursor)
                                new_data = handle.readlines()
                                new_cursor = handle.tell()
                    except Exception:
                        pass
                    return (new_data, new_cursor)

                new_lines, last_pos = await asyncio.to_thread(read_updates, last_pos)
                if new_lines:
                    await _write_sse(response, "logs", {"logs": [line.rstrip() for line in new_lines]})
                    await response.drain()
                    data_sent = True

            elif log_type == "sys":
                try:
                    if sys_cursor:
                        new_lines, sys_cursor = await fetch_sys_logs(cursor=sys_cursor)
                    else:
                        new_lines, sys_cursor = await fetch_sys_logs(lines=10)
                except Exception as exc:
                    logging.error("Error streaming sys logs: %s", exc)
                    new_lines = ["Error: Connection to system logs lost"]

                if not sys_cursor and new_lines and "Error:" not in new_lines[0]:
                    current_hash = hash(tuple(new_lines))
                    if current_hash == last_sent_lines_hash:
                        new_lines = []
                    else:
                        last_sent_lines_hash = current_hash

                if new_lines:
                    await _write_sse(response, "logs", {"logs": new_lines})
                    await response.drain()
                    data_sent = True

            if data_sent:
                last_activity = time.time()
            elif time.time() - last_activity > KEEPALIVE_INTERVAL:
                try:
                    await response.write(b": keepalive\n\n")
                    await response.drain()
                    last_activity = time.time()
                except Exception:
                    break

            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        if "closing transport" not in str(exc) and "'NoneType' object" not in str(exc):
            logging.error("SSE logs error: %s", exc)
            try:
                await _write_sse(response, "error", {"error": "Internal Server Error"})
            except Exception:
                pass

    return response


@routes.get("/api/events/node")
async def handle_sse_node_details(request: web.Request) -> web.StreamResponse:
    if not _is_sse_request(request):
        return _build_plain_api_notice(request.path)

    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.Response(status=403)

    token = decrypt_for_web(request.query.get("token"))
    if not token:
        return web.Response(status=400)

    current_token = request.cookies.get(COOKIE_NAME)
    lang = get_user_lang(int(user["id"]))

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

            node = await nodes_db.get_node_by_token(token)
            if node:
                last_seen = node.get("last_seen", 0)
                is_restarting = node.get("is_restarting", False)
                status = "restarting" if is_restarting else "online" if time.time() - last_seen < current_config.NODE_OFFLINE_TIMEOUT else "offline"
                payload = {
                    "name": encrypt_for_web(node.get("name")),
                    "ip": encrypt_for_web(node.get("ip")),
                    "stats": _encrypt_node_stats_for_web(node.get("stats")),
                    "history": node.get("history", []),
                    "token": encrypt_for_web(token),
                    "last_seen": last_seen,
                    "is_restarting": is_restarting,
                    "status": status,
                    "availability": get_node_uptime_snapshot(node, lang, current_config.NODE_OFFLINE_TIMEOUT, time.time()),
                }
                try:
                    await _write_sse(response, "node_details", payload)
                except (ConnectionResetError, BrokenPipeError, ConnectionError):
                    break
            else:
                try:
                    await _write_sse(response, "error", {"error": "Node not found"})
                except (ConnectionResetError, BrokenPipeError, ConnectionError):
                    pass
                break

            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=3.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        if "closing transport" not in str(exc) and "'NoneType' object" not in str(exc):
            logging.error("SSE node details error: %s", exc)

    return response


@routes.get("/api/events/node/services")
async def handle_sse_node_services(request: web.Request) -> web.StreamResponse:
    if not _is_sse_request(request):
        return _build_plain_api_notice(request.path)

    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.Response(status=403)

    token = decrypt_for_web(request.query.get("token"))
    if not token:
        return web.Response(status=400)

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

            node = await nodes_db.get_node_by_token(token)
            if not node:
                try:
                    await _write_sse(response, "error", {"error": "Node not found"})
                except (ConnectionResetError, BrokenPipeError, ConnectionError):
                    pass
                break

            try:
                payload = {"services": _encrypt_node_services_for_web(node.get("services", []))}
                await _write_sse(response, "node_services", payload)
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                break
            except Exception as exc:
                logging.error("SSE node services fetch error: %s", exc)

            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=3.0)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        if "closing transport" not in str(exc) and "'NoneType' object" not in str(exc):
            logging.error("SSE node services error: %s", exc)

    return response


@routes.get("/api/events/services")
async def handle_sse_services(request: web.Request) -> web.StreamResponse:
    """SSE endpoint for services status updates."""
    if not _is_sse_request(request):
        return _build_plain_api_notice(request.path)

    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.Response(status=403)

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
                from modules.services import get_all_services_status
                services = await asyncio.to_thread(get_all_services_status)
                encrypted_services = [
                    {
                        "name": encrypt_for_web(svc.get("name", "")),
                        "type": encrypt_for_web(svc.get("type", "")),
                        "status": encrypt_for_web(svc.get("status", "")),
                    }
                    for svc in services
                ]
                await _write_sse(response, "services", {"services": encrypted_services})
            except (ConnectionResetError, BrokenPipeError, ConnectionError):
                break
            except Exception as exc:
                logging.error("SSE services fetch error: %s", exc)

            sleep_time = float(getattr(current_config, "SERVICES_INTERVAL", 5))
            if shutdown_event:
                try:
                    if not shared_state.IS_RESTARTING:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_time)
                        break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        if "closing transport" not in str(exc) and "'NoneType' object" not in str(exc):
            logging.error("SSE services error: %s", exc)

    return response


async def _forward_ws_stream(stream: Any, ws_client: web.WebSocketResponse) -> None:
    try:
        while True:
            data = await stream.read(4096)
            if not data:
                break
            if isinstance(data, bytes):
                await ws_client.send_str(data.decode("utf-8", errors="ignore"))
            else:
                await ws_client.send_str(str(data))
    except Exception:
        pass


@routes.get("/api/terminal/creds")
async def handle_get_terminal_creds(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"status": "error", "error": "Admin required"}, status=403)

    ip = str(request.query.get("ip", "")).strip()
    if not ip:
        return web.json_response({"status": "error", "error": "Missing IP"}, status=400)

    try:
        creds = await current_config.get_bot_config("terminal_creds", {})
        uid_str = str(user["id"])
        if isinstance(creds, dict) and uid_str in creds and ip in creds[uid_str]:
            saved = creds[uid_str][ip]
            return web.json_response(
                {
                    "status": "ok",
                    "saved": True,
                    "type": str(saved.get("type", "password")),
                    "user": str(saved.get("user", "root")),
                    "port": int(saved.get("port", 22)),
                }
            )
        return web.json_response({"status": "ok", "saved": False})
    except Exception as exc:
        logging.error("Terminal creds load failed: %s", exc)
        return web.json_response({"status": "error", "error": "Internal Server Error"}, status=500)


@routes.post("/api/terminal/creds")
async def handle_save_terminal_creds(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"status": "error", "error": "Admin required"}, status=403)

    try:
        data = await request.json()
        ip = str(data.get("ip", "")).strip()
        if not ip:
            return web.json_response({"status": "error", "error": "Missing IP"}, status=400)

        creds = await current_config.get_bot_config("terminal_creds", {})
        if not isinstance(creds, dict):
            creds = {}

        uid_str = str(user["id"])
        if uid_str not in creds or not isinstance(creds.get(uid_str), dict):
            creds[uid_str] = {}

        creds[uid_str][ip] = {
            "type": str(data.get("type", "password")),
            "user": str(data.get("user", "root")),
            "port": int(data.get("port", 22)),
            "password": str(data.get("password", "")),
            "private_key": str(data.get("private_key", "")),
        }
        await current_config.set_bot_config("terminal_creds", creds)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logging.error("Terminal creds save failed: %s", exc)
        return web.json_response({"status": "error", "error": "Internal Server Error"}, status=500)


@routes.get("/api/terminal/stats")
async def handle_terminal_stats(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.json_response({"error": "Admin required"}, status=403)

    ip = str(request.query.get("ip", "")).strip()
    if not ip:
        return web.json_response({"error": "Missing IP"}, status=400)

    try:
        safe_agent_ip = _safe_agent_ip()
        if _is_local_terminal_stats_target(ip, safe_agent_ip):
            import psutil

            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(get_host_path("/"))
            uptime = int(time.time() - psutil.boot_time())
            ram_used = mem.total - mem.available
            ram_pct = round(ram_used / mem.total * 100, 1) if mem.total > 0 else 0
            ping_raw = _safe_agent_ping()
            try:
                ping_value = float(str(ping_raw).replace("ms", "").strip())
            except Exception:
                ping_value = 0.0

            return web.json_response(
                {
                    "cpu": float(cpu),
                    "ram": float(ram_pct),
                    "rom": float(disk.percent),
                    "uptime": uptime,
                    "ping": ping_value,
                }
            )

        all_nodes = await nodes_db.get_all_nodes()
        for node_data in all_nodes.values():
            if str(node_data.get("ip", "")).strip() == ip:
                stats = node_data.get("stats", {}) or {}
                ping_raw = stats.get("ping", 0)
                try:
                    ping_value = float(str(ping_raw).replace("ms", "").strip())
                except Exception:
                    ping_value = 0.0
                return web.json_response(
                    {
                        "cpu": float(stats.get("cpu", 0) or 0),
                        "ram": float(stats.get("ram", 0) or 0),
                        "rom": float(stats.get("disk", 0) or 0),
                        "uptime": int(stats.get("uptime", 0) or 0),
                        "ping": ping_value,
                    }
                )

        return web.json_response({"error": "No stats"}, status=404)
    except Exception as exc:
        logging.error("Terminal stats failed: %s", exc)
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/terminal/ws")
async def handle_terminal_ws(request: web.Request) -> web.StreamResponse:
    ws_probe = web.WebSocketResponse()
    ws_ready = ws_probe.can_prepare(request)
    if not ws_ready.ok:
        return _build_websocket_notice(request.path)

    user = get_current_user(request)
    if not user or not _is_admin(user):
        return web.Response(status=403)

    ws_client = web.WebSocketResponse(heartbeat=30.0, autoping=True, autoclose=True)
    await ws_client.prepare(request)

    conn: Any = None
    process: Any = None
    forward_tasks: list[asyncio.Task[Any]] = []

    try:
        try:
            message = await ws_client.receive_json()
        except Exception:
            await ws_client.close()
            return ws_client

        if message.get("type") != "auth":
            await ws_client.close()
            return ws_client

        host = str(message.get("host", "")).strip()
        username = str(message.get("user", "")).strip()
        port = int(message.get("port", 22))
        use_saved = bool(message.get("use_saved", False))
        auth_type = str(message.get("auth_type", "password")).strip()
        password = str(message.get("password", ""))
        private_key = str(message.get("private_key", ""))
        cols = int(message.get("cols", 80))
        rows = int(message.get("rows", 24))

        if use_saved and host:
            creds = await current_config.get_bot_config("terminal_creds", {})
            uid_str = str(user["id"])
            if isinstance(creds, dict) and uid_str in creds and host in creds[uid_str]:
                saved_cred = creds[uid_str][host]
                username = username or str(saved_cred.get("user", "root"))
                port = int(saved_cred.get("port", port))
                auth_type = str(saved_cred.get("type", auth_type))
                if auth_type == "password":
                    password = password or str(saved_cred.get("password", ""))
                else:
                    private_key = private_key or str(saved_cred.get("private_key", ""))

        if not host or not username:
            await ws_client.send_json({"type": "error", "message": "Missing host or username"})
            await ws_client.close()
            return ws_client

        if not await _is_allowed_terminal_host(host):
            await ws_client.send_json({"type": "error", "message": "Access denied: Unknown host"})
            await ws_client.close()
            return ws_client

        import asyncssh

        connect_kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "username": username,
            "known_hosts": None,
        }

        if auth_type == "key" and private_key:
            try:
                key = asyncssh.import_private_key(private_key)
                connect_kwargs["client_keys"] = [key]
            except Exception as exc:
                await ws_client.send_json({"type": "error", "message": f"Invalid SSH Key: {exc}"})
                await ws_client.close()
                return ws_client
        else:
            connect_kwargs["password"] = password

        conn = await asyncssh.connect(**connect_kwargs)
        process = await conn.create_process(term_type="xterm", term_size=(cols, rows))
        await ws_client.send_json({"type": "connected"})

        forward_tasks = [
            asyncio.create_task(_forward_ws_stream(process.stdout, ws_client)),
            asyncio.create_task(_forward_ws_stream(process.stderr, ws_client)),
        ]

        async for ws_msg in ws_client:
            if ws_msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(ws_msg.data)
                except Exception:
                    continue

                if payload.get("type") == "data":
                    process.stdin.write(str(payload.get("data", "")))
                elif payload.get("type") == "resize":
                    process.change_terminal_size(int(payload.get("cols", 80)), int(payload.get("rows", 24)))
            elif ws_msg.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
                break
    except Exception as exc:
        logging.error("Terminal websocket error: %s", exc)
        if not ws_client.closed:
            try:
                await ws_client.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
    finally:
        for task in forward_tasks:
            task.cancel()
        if process is not None:
            try:
                process.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if not ws_client.closed:
            await ws_client.close()

    return ws_client


__all__ = [
    "routes",
    "handle_sse_stream",
    "handle_sse_logs",
    "handle_sse_node_details",
    "handle_sse_node_services",
    "handle_sse_services",
    "handle_terminal_ws",
]
