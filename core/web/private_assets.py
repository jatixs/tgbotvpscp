"""Session-gated bundles for operation history and its panel navigation."""
from pathlib import Path
import posixpath

from aiohttp import web

from ..config import BASE_DIR
from ..rbac import is_admin
from .auth import get_current_user

ASSETS = {
    "/static/css/operations.css": True,
    "/static/js/operations.js": True,
    "/static/js/panel_bootstrap.js": False,
    "/static/js/panel_navigation.js": False,
    "/static/js/node_vnc.js": False,
}


@web.middleware
async def protect_private_assets(request, handler):
    # The public static resource can also resolve dot-segments and duplicate slashes.
    # Apply authorization to their canonical path, not only to the exact routes below.
    path = posixpath.normpath(request.path.replace("\\", "/")).lower()
    if path in ASSETS:
        user = get_current_user(request)
        if not user:
            raise web.HTTPUnauthorized()
        if ASSETS[path] and not is_admin(user):
            raise web.HTTPForbidden()
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    return await handler(request)


def _make_private_asset_handler(asset_path: Path, admin_only: bool):
    """Bind a trusted filesystem path at route-registration time.

    No request-supplied path components are ever used for file selection.
    """
    async def serve_private_asset(request):
        user = get_current_user(request)
        if not user:
            raise web.HTTPUnauthorized()
        if admin_only and not is_admin(user):
            raise web.HTTPForbidden()
        return web.FileResponse(
            asset_path,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return serve_private_asset


def register_private_assets(app):
    # Only predeclared files are served, with each handler bound to its own path.
    static_dir = Path(BASE_DIR) / "core" / "static"
    for route, admin_only in ASSETS.items():
        filename = route.removeprefix("/static/")
        # filename comes solely from the module-level ASSETS allowlist.
        asset_path = static_dir / filename
        app.router.add_get(route, _make_private_asset_handler(asset_path, admin_only))
