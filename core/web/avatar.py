import html
import logging
from urllib.parse import urlsplit


def get_avatar_html(user: dict) -> str:
    raw = str(user.get("photo_url", ""))
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        ):
            safe_url = html.escape(raw, quote=True)
            return f'<img src="{safe_url}" alt="ava" class="w-6 h-6 rounded-full flex-shrink-0">'
    except ValueError as exc:
        logging.debug("Ignoring malformed avatar URL: %s", exc)
    return f'<span class="text-lg leading-none select-none">{html.escape(raw)}</span>'
