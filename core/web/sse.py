"""Shared setup for server-sent event responses."""
from __future__ import annotations

from aiohttp import web


async def prepare_event_stream(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(status=200, reason="OK", headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    })
    await response.prepare(request)
    return response
