"""Validate HTTPS endpoint changes during node-agent migration."""
from __future__ import annotations

from urllib.parse import urlsplit


def _parse_origin(value: str, scheme: str):
    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid endpoint URL") from exc

    if (
        parsed.scheme.lower() != scheme
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Expected a plain {scheme.upper()} origin")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid endpoint port")
    return parsed


def validate_https_migration_url(current_url: str, advertised_url: str) -> str:
    """Keep the established host and require a valid HTTPS origin for upgrade."""
    current = _parse_origin(current_url, "http")
    target = _parse_origin(advertised_url, "https")
    if current.hostname.lower().rstrip(".") != target.hostname.lower().rstrip("."):
        raise ValueError("HTTPS migration host does not match the configured agent host")
    return advertised_url.rstrip("/")