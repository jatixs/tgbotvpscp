"""Cache policy scenarios run in a clean interpreter, apart from legacy mocks."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web


def load_middleware():
    source = Path(__file__).resolve().parents[1] / "core/web/middlewares.py"
    spec = importlib.util.spec_from_file_location("core.web._cache_policy_tests", source)
    module = importlib.util.module_from_spec(spec)
    # Import the real middleware with isolated configuration and authentication.
    # Do not initialize the bot, database, or environment-specific configuration.
    with patch.dict(sys.modules, {
        "core.config": SimpleNamespace(LEGACY_NODE_BRIDGE=False, WEB_PUBLIC_URL="https://panel.example"),
        "core.web.auth": SimpleNamespace(verify_csrf_token=AsyncMock()),
    }):
        spec.loader.exec_module(module)
    return module.security_headers_middleware


class CachePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def apply_policy(self, path, response, request_headers=None, raised=False):
        request = SimpleNamespace(path=path, scheme="https", headers=request_headers or {})
        handler = AsyncMock(side_effect=response) if raised else AsyncMock(return_value=response)
        if raised:
            with self.assertRaises(web.HTTPException) as caught:
                await load_middleware()(request, handler)
            result = caught.exception
        else:
            result = await load_middleware()(request, handler)
        self.assertIs(result, response)
        return response.headers

    async def test_all_pages_discard_speculation_cache_without_clearing_sessions(self):
        for path in ("/", "/nodes", "/settings", "/operations", "/terminal", "/login", "/reset_password"):
            with self.subTest(path=path):
                response = SimpleNamespace(status=200, content_type="text/html", headers={"Cache-Control": "public, max-age=3600", "Set-Cookie": "session=kept"})
                headers = await self.apply_policy(path, response)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["Clear-Site-Data"], '"prefetchCache", "prerenderCache"')
                self.assertEqual(headers["Set-Cookie"], "session=kept")
                self.assertEqual(headers["Vary"], "Sec-Purpose, Purpose")

    async def test_returned_and_raised_503_are_not_cached(self):
        for raised in (False, True):
            response = web.HTTPServiceUnavailable(content_type="text/plain", headers={"Cache-Control": "public, max-age=60", "Retry-After": "30"})
            headers = await self.apply_policy("/nodes", response, {"Sec-Fetch-Dest": "document"}, raised=raised)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn("prefetchCache", headers["Clear-Site-Data"])
            self.assertEqual(headers["Retry-After"], "30")

    async def test_redirects_keep_location_and_receive_page_cache_policy(self):
        response = web.HTTPFound(location="/login")
        headers = await self.apply_policy("/settings", response, {"Sec-Fetch-Dest": "document"}, raised=True)
        self.assertEqual(headers["Location"], "/login")
        self.assertEqual(headers["Cache-Control"], "no-store")

    async def test_existing_vary_is_preserved_without_duplicates(self):
        for existing, expected in (("Accept-Encoding, sec-purpose", "Accept-Encoding, sec-purpose, Purpose"), ("*", "*")):
            response = web.Response(content_type="text/html", headers={"Vary": existing})
            headers = await self.apply_policy("/", response)
            self.assertEqual(headers["Vary"], expected)

    async def test_public_asset_and_stream_policies_are_preserved(self):
        for path, content_type, policy in (("/static/main.css", "text/css", "public, max-age=3600"), ("/api/events", "text/event-stream", "no-cache")):
            response = web.Response(content_type=content_type, headers={"Cache-Control": policy})
            headers = await self.apply_policy(path, response)
            self.assertEqual(headers["Cache-Control"], policy)
            self.assertNotIn("Clear-Site-Data", headers)

    async def test_non_document_errors_are_not_cached(self):
        response = web.Response(status=503, content_type="text/plain")
        headers = await self.apply_policy("/api/status", response)
        self.assertEqual(headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
