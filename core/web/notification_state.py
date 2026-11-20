"""Common user-scoped WebUI notification operations used by API and SSE."""
from __future__ import annotations

import time
from typing import Any

from .. import shared_state


def get_user_notifications(user_id: int, language: str, default_language: str) -> dict[str, Any]:
    """Return notifications visible to this user, honoring per-user clear/read state."""
    alert_settings = shared_state.ALERTS_CONFIG.get(user_id, {})
    cleared_at = shared_state.WEB_USER_CLEARED_AT.get(user_id, 0)
    filtered: list[dict[str, Any]] = []

    for item in list(shared_state.WEB_NOTIFICATIONS):
        if item["time"] <= cleared_at or not alert_settings.get(item["type"], False):
            continue
        notification = item.copy()
        text_map = notification.pop("text_map", None)
        if isinstance(text_map, dict):
            localized = text_map.get(language) or text_map.get(default_language)
            if localized:
                notification["text"] = localized
        filtered.append(notification)

    last_read = shared_state.WEB_USER_LAST_READ.get(user_id, 0)
    unread_count = sum(1 for item in filtered if item["time"] > last_read)
    return {"notifications": filtered, "unread_count": unread_count}


def clear_user_notifications(user_id: int, *, now: float | None = None) -> None:
    """Hide existing notifications only for the requesting user."""
    cleared_at = time.time() if now is None else now
    shared_state.WEB_USER_CLEARED_AT[user_id] = cleared_at
    shared_state.WEB_USER_LAST_READ[user_id] = cleared_at
