from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from typing import Final

from aiohttp import web
from aiohttp.typedefs import Handler

from .auth import verify_csrf_token

MAX_API_REQUESTS: Final[int] = 100
API_RATE_WINDOW: Final[int] = 60
MAX_REQUEST_BODY_BYTES: Final[int] = 10_000
RATE_LIMITED_METHODS: Final[set[str]] = {"POST", "PUT", "DELETE"}
WAF_INSPECT_METHODS: Final[set[str]] = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_PROTECTED_METHODS: Final[set[str]] = {"POST", "PUT", "DELETE"}
CSRF_EXCLUDED_PATHS: Final[set[str]] = {"/api/heartbeat"}
CSRF_EXCLUDED_PREFIXES: Final[tuple[str, ...]] = ("/api/login/",)
WAF_INSPECT_CONTENT_TYPES: Final[set[str]] = {
    "application/json",
    "application/x-www-form-urlencoded",
    "text/plain",
    "application/xml",
}

WAF_ATTACK_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    (r"(?i)(union|select|insert|update|delete|drop|create|alter|exec|execute)\\s+", "SQL_INJECTION"),
    (r"(?i)(%20|\\s)(or|and)(\\s|%20)+.*=", "SQL_INJECTION"),
    (r"(?i)<script[^>]*>.*?</script>", "XSS"),
    (r"(?i)javascript:", "XSS"),
    (r"(?i)on\w+\s*=", "XSS"),
    (r"(?i)<iframe[^>]*>", "XSS"),
    (r"(?i)<embed[^>]*>", "XSS"),
    (r"(?i)<object[^>]*>", "XSS"),
    (r"\.\./", "PATH_TRAVERSAL"),
    (r"\.\.\\", "PATH_TRAVERSAL"),
    (r"%2e%2e/", "PATH_TRAVERSAL"),
    (r"%2e%2e\\", "PATH_TRAVERSAL"),
    (r"(?i)[;|]\s*(?:ls|cat|id|whoami|wget|curl|bash|sh|cmd|python3?|perl|ruby|php|nc|netcat|chmod|chown|sudo|su|rm|mv|cp|echo|tee|awk|sed|find)\b", "COMMAND_INJECTION"),
    (r"(?i)\b(wget|curl)\s+https?://", "COMMAND_INJECTION"),
)


def get_client_ip(request: web.Request) -> str:
    """Return the best-effort client IP, honoring reverse proxy headers."""
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "").strip()

    if forwarded_for:
        return forwarded_for
    if real_ip:
        return real_ip

    if request.transport is None:
        return "127.0.0.1"

    peer = request.transport.get_extra_info("peername")
    if isinstance(peer, tuple) and peer:
        return str(peer[0])

    return "127.0.0.1"


def mask_sensitive_data(data: str, mask_length: int = 6) -> str:
    """Mask sensitive values before writing them to logs."""
    if not isinstance(data, str) or len(data) < mask_length:
        return "***"
    return data[:mask_length] + "*" * (len(data) - mask_length)


def check_waf_patterns(data: str) -> tuple[bool, str]:
    """Check incoming payload for basic attack signatures."""
    if not isinstance(data, str):
        return False, ""

    for pattern, attack_type in WAF_ATTACK_PATTERNS:
        if re.search(pattern, data, re.IGNORECASE):
            return True, attack_type

    return False, ""


def validate_input_length(data: str, max_length: int = MAX_REQUEST_BODY_BYTES) -> bool:
    """Ensure request body size stays within accepted bounds."""
    return len(data) <= max_length


def _requires_csrf(request: web.Request) -> bool:
    if request.method not in CSRF_PROTECTED_METHODS:
        return False
    if not request.path.startswith("/api/"):
        return False
    if request.path in CSRF_EXCLUDED_PATHS:
        return False
    return not any(request.path.startswith(prefix) for prefix in CSRF_EXCLUDED_PREFIXES)


async def _extract_csrf_token(request: web.Request) -> str | None:
    header_token = request.headers.get("X-CSRF-Token", "").strip()
    if header_token:
        return header_token

    if not request.can_read_body:
        return None

    content_type = request.content_type.lower() if request.content_type else ""

    try:
        if "application/json" in content_type:
            payload = await request.json()
            if isinstance(payload, dict):
                token = payload.get("csrf_token") or payload.get("_csrf")
                if isinstance(token, str) and token.strip():
                    return token.strip()
        elif content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
            payload = await request.post()
            token = payload.get("csrf_token") or payload.get("_csrf")
            if isinstance(token, str) and token.strip():
                return token.strip()
    except Exception:
        logging.debug("Failed to extract CSRF token for %s", request.path)

    return None


def _cleanup_rate_limit_store(store: dict[str, deque[float]], now: float) -> None:
    stale_keys: list[str] = []

    for key, timestamps in store.items():
        while timestamps and now - timestamps[0] > API_RATE_WINDOW:
            timestamps.popleft()
        if not timestamps:
            stale_keys.append(key)

    for key in stale_keys:
        store.pop(key, None)


@web.middleware
async def rate_limit_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    """Apply per-IP and per-endpoint API rate limiting."""
    if request.path.startswith("/api/") and request.method in RATE_LIMITED_METHODS:
        now = time.time()
        rate_limits = request.app.setdefault("api_rate_limits", defaultdict(deque))
        if not isinstance(rate_limits, dict):
            rate_limits = defaultdict(deque)
            request.app["api_rate_limits"] = rate_limits

        _cleanup_rate_limit_store(rate_limits, now)

        client_ip = get_client_ip(request)
        rate_key = f"{client_ip}:{request.path}"
        bucket = rate_limits.setdefault(rate_key, deque())

        if len(bucket) >= MAX_API_REQUESTS:
            logging.warning(
                "Rate limit exceeded for IP %s on %s",
                mask_sensitive_data(client_ip),
                request.path,
            )
            return web.json_response(
                {"error": "Rate limit exceeded. Max 100 requests/minute per IP"},
                status=429,
            )

        bucket.append(now)

        if len(rate_limits) > 5_000:
            _cleanup_rate_limit_store(rate_limits, now)

    return await handler(request)


@web.middleware
async def csrf_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    """Protect mutating API routes from CSRF attacks."""
    if not _requires_csrf(request):
        return await handler(request)

    token = await _extract_csrf_token(request)
    if verify_csrf_token(token):
        return await handler(request)

    logging.warning(
        "CSRF validation failed for %s %s from IP %s",
        request.method,
        request.path,
        mask_sensitive_data(get_client_ip(request)),
    )
    return web.json_response({"error": "Invalid CSRF token"}, status=403)


@web.middleware
async def waf_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    """Inspect API payloads and reject obviously malicious requests."""
    if request.method not in WAF_INSPECT_METHODS:
        return await handler(request)

    client_ip = get_client_ip(request)

    query_string = request.query_string or ""
    if query_string:
        is_attack, attack_type = check_waf_patterns(query_string)
        if is_attack:
            logging.critical(
                "WAF blocked %s in query from IP %s",
                attack_type,
                mask_sensitive_data(client_ip),
            )
            return web.json_response({"error": "Malicious request detected"}, status=403)

    content_length = request.content_length or 0
    if content_length > MAX_REQUEST_BODY_BYTES:
        logging.warning("WAF rejected oversized request from IP %s", mask_sensitive_data(client_ip))
        return web.json_response({"error": "Request too large"}, status=413)

    content_type = request.content_type.lower() if request.content_type else ""
    if request.can_read_body and content_type in WAF_INSPECT_CONTENT_TYPES:
        try:
            body = await request.text()
        except UnicodeDecodeError:
            logging.warning("WAF rejected undecodable payload from IP %s", mask_sensitive_data(client_ip))
            return web.json_response({"error": "Invalid request encoding"}, status=400)
        except Exception:
            logging.exception("WAF failed while reading request body")
            return web.json_response({"error": "Bad request"}, status=400)

        if body:
            is_attack, attack_type = check_waf_patterns(body)
            if is_attack:
                logging.critical(
                    "WAF blocked %s in body from IP %s",
                    attack_type,
                    mask_sensitive_data(client_ip),
                )
                return web.json_response({"error": "Malicious request detected"}, status=403)

            if not validate_input_length(body):
                logging.warning("WAF rejected large decoded body from IP %s", mask_sensitive_data(client_ip))
                return web.json_response({"error": "Request too large"}, status=413)

    return await handler(request)


__all__ = [
    "rate_limit_middleware",
    "csrf_middleware",
    "waf_middleware",
    "get_client_ip",
    "check_waf_patterns",
    "validate_input_length",
    "mask_sensitive_data",
]
