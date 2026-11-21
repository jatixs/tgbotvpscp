"""Authenticated, encrypted address snapshots shared by both IP-family routes."""
from aiohttp import web

from ..network_addresses import normalize_address
from ..utils import encrypted_json_response
from . import auth


async def agent_address_response(request, version, collector, primary_getter=None):
    if not auth.get_current_user(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    ips = list(dict.fromkeys(ip for value in collector() if (ip := normalize_address(value, version))))
    primary = normalize_address(primary_getter(), version) if primary_getter else ""
    primary = primary or (ips[0] if ips else "")
    if primary and primary not in ips:
        ips.insert(0, primary)
    return encrypted_json_response({
        "primary": primary, "source_ip": primary, "agent_ip": primary,
        "ips": ips, "count": len(ips),
    })
