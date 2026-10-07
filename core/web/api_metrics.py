"""
REST API истории метрик для графиков с выбором периода (3 минуты — 7 дней).
"""
from __future__ import annotations

from aiohttp import web

from .. import metrics_history, nodes_db
from .auth import get_current_user

routes = web.RouteTableDef()


@routes.get("/api/metrics/history")
async def handle_metrics_history(request: web.Request) -> web.StreamResponse:
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    range_key = request.query.get("range", metrics_history.DEFAULT_RANGE)
    if range_key not in metrics_history.RANGES:
        return web.json_response({"error": "Unknown range"}, status=400)

    source_kind = request.query.get("source", "agent")
    if source_kind == "agent":
        source = metrics_history.AGENT_SOURCE
    elif source_kind == "node":
        try:
            node_id = int(request.query.get("node_id", "0"))
        except ValueError:
            node_id = 0
        if node_id <= 0:
            return web.json_response({"error": "Node ID required"}, status=400)
        if not await nodes_db.get_node_by_id(node_id):
            return web.json_response({"error": "Node not found"}, status=404)
        source = metrics_history.node_source(node_id)
    else:
        return web.json_response({"error": "Unknown source"}, status=400)

    since: int | None = None
    raw_since = request.query.get("since")
    if raw_since:
        try:
            since = int(raw_since)
        except ValueError:
            return web.json_response({"error": "Invalid since"}, status=400)

    await metrics_history.flush_pending()
    payload = await metrics_history.query_series(source, range_key, since)
    payload["source"] = source_kind
    return web.json_response(payload)
