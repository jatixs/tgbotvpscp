from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from argon2 import PasswordHasher, exceptions as argon2_exceptions
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config as current_config
from ..auth import save_users_async
from ..config import (
    ADMIN_USER_ID,
    ADMIN_USERNAME,
    BASE_DIR,
    DEFAULT_LANGUAGE,
    TG_BOT_NAME,
    TOKEN,
    WEB_SERVER_HOST,
    WEB_SERVER_PORT,
)
from ..i18n import get_text as _, get_user_lang
from ..shared_state import ALLOWED_USERS, USER_NAMES, AUTH_TOKENS
from ..utils import encrypt_for_web

routes = web.RouteTableDef()

COOKIE_NAME: Final[str] = "vps_agent_session"
CSRF_TOKEN_COOKIE: Final[str] = "csrf_token"
LOGIN_TOKEN_TTL: Final[int] = 300
RESET_TOKEN_TTL: Final[int] = 600
CSRF_TOKEN_TTL: Final[int] = 3600
SESSION_TTL_PASSWORD: Final[int] = 7 * 24 * 60 * 60
SESSION_TTL_MAGIC: Final[int] = 30 * 24 * 60 * 60
MAX_LOGIN_ATTEMPTS: Final[int] = 5
LOGIN_BLOCK_TIME: Final[int] = 300
AGENT_FLAG: Final[str] = "🏳️"

TEMPLATE_DIR: Final[Path] = Path(BASE_DIR) / "core" / "templates"
JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

BOT_USERNAME_CACHE: str | None = None
SERVER_SESSIONS: dict[str, dict[str, Any]] = {}
RESET_TOKENS: dict[str, dict[str, Any]] = {}
CSRF_TOKENS: dict[str, float] = {}
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
PASSWORD_HASHER = PasswordHasher()
DEFAULT_ADMIN_PASSWORD_HASH = PASSWORD_HASHER.hash("admin")


def generate_csrf_token() -> str:
    """Generate and store a secure CSRF token with expiry metadata."""
    token = secrets.token_urlsafe(32)
    CSRF_TOKENS[token] = time.time() + CSRF_TOKEN_TTL
    return token


def verify_csrf_token(token: str | None) -> bool:
    """Validate a CSRF token and garbage-collect expired entries."""
    if not token:
        return False

    expires_at = CSRF_TOKENS.get(token)
    if expires_at is None:
        return False

    now = time.time()
    if now > expires_at:
        CSRF_TOKENS.pop(token, None)
        return False

    if len(CSRF_TOKENS) > 1000:
        expired = [key for key, value in CSRF_TOKENS.items() if now > value]
        for key in expired:
            CSRF_TOKENS.pop(key, None)

    return True


def get_client_ip(request: web.Request) -> str:
    """Resolve the original client IP, honoring common proxy headers."""
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "").strip()

    if forwarded:
        return forwarded
    if real_ip:
        return real_ip

    if request.transport is None:
        return "127.0.0.1"

    peer = request.transport.get_extra_info("peername")
    if isinstance(peer, tuple) and peer:
        return str(peer[0])

    return "127.0.0.1"


def check_rate_limit(ip: str) -> bool:
    """Limit brute-force password attempts per client IP."""
    now = time.time()
    attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if now - t < LOGIN_BLOCK_TIME]
    LOGIN_ATTEMPTS[ip] = attempts
    return len(attempts) < MAX_LOGIN_ATTEMPTS


def add_login_attempt(ip: str) -> None:
    """Record a failed password login attempt."""
    LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


def check_user_password(user_id: int, raw_password: str | None) -> bool:
    """Verify the stored password hash for the requested user."""
    if user_id not in ALLOWED_USERS or not raw_password:
        return False

    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, str):
        return False

    stored_hash = user_data.get("password_hash")
    if not stored_hash:
        if user_id != ADMIN_USER_ID:
            return False
        try:
            return bool(PASSWORD_HASHER.verify(DEFAULT_ADMIN_PASSWORD_HASH, raw_password))
        except argon2_exceptions.VerifyMismatchError:
            return False

    try:
        return bool(PASSWORD_HASHER.verify(stored_hash, raw_password))
    except argon2_exceptions.VerifyMismatchError:
        return False
    except Exception:
        logging.exception("Password verification failed")
        return False


def is_default_password_active(user_id: int) -> bool:
    """Return True when the main admin still uses the default password."""
    if user_id != ADMIN_USER_ID or user_id not in ALLOWED_USERS:
        return False

    user_data = ALLOWED_USERS[user_id]
    if isinstance(user_data, str):
        return True

    password_hash = user_data.get("password_hash")
    if not password_hash:
        return True

    try:
        return PasswordHasher().verify(password_hash, "admin")
    except Exception:
        return False


def get_current_user(request: web.Request) -> dict[str, Any] | None:
    """Read the active web session and resolve the authenticated user."""
    session_token = request.cookies.get(COOKIE_NAME)
    if not session_token:
        return None

    session = SERVER_SESSIONS.get(session_token)
    if not session:
        return None

    if time.time() > float(session.get("expires", 0)):
        SERVER_SESSIONS.pop(session_token, None)
        return None

    user_id = int(session.get("id", 0))
    if user_id not in ALLOWED_USERS:
        return None

    user_data = ALLOWED_USERS[user_id]
    role = user_data.get("group", "users") if isinstance(user_data, dict) else user_data
    return {
        "id": user_id,
        "role": role,
        "first_name": USER_NAMES.get(str(user_id), f"ID: {user_id}"),
        "photo_url": session.get("photo_url", AGENT_FLAG),
    }


def check_telegram_auth(data: dict[str, Any], bot_token: str) -> bool:
    """Validate Telegram Login Widget payload signature."""
    auth_data = data.copy()
    provided_hash = auth_data.pop("hash", "")
    if not provided_hash:
        return False

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(auth_data.items())
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, provided_hash):
        return False

    auth_date = int(auth_data.get("auth_date", 0))
    return time.time() - auth_date <= 900


def check_webapp_auth(init_data: str, bot_token: str) -> dict[str, Any] | None:
    """Validate Telegram Mini App (Web App) initData payload."""
    try:
        parsed_data = dict(parse_qsl(init_data))
        provided_hash = parsed_data.pop("hash", None)
        if not provided_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(parsed_data.items())
        )
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, provided_hash):
            return None

        auth_date = int(parsed_data.get("auth_date", 0))
        if time.time() - auth_date > 86400:  # 24 hours
            return None

        user_json = parsed_data.get("user")
        if not user_json:
            return None
            
        return json.loads(user_json)
    except Exception:
        logging.exception("Web App auth validation failed")
        return None


def _set_csrf_cookie(
    response: web.StreamResponse,
    request: web.Request,
    *,
    token: str | None = None,
) -> str:
    token = token or generate_csrf_token()
    is_secure = request.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
    response.set_cookie(
        CSRF_TOKEN_COOKIE,
        token,
        max_age=CSRF_TOKEN_TTL,
        secure=is_secure,
        httponly=False,
        samesite="Strict" if is_secure else "Lax",
    )
    response.headers["X-CSRF-Token"] = token
    return token


def _create_session(
    *,
    request: web.Request,
    user_id: int,
    max_age: int,
    photo_url: str | None = None,
) -> str:
    session_token = secrets.token_hex(32)
    SERVER_SESSIONS[session_token] = {
        "id": user_id,
        "expires": time.time() + max_age,
        "ip": get_client_ip(request),
        "ua": html.escape(request.headers.get("User-Agent", "Unknown Device"), quote=True),
        "created": time.time(),
        "photo_url": photo_url,
    }
    return session_token


def _set_session_cookie(
    response: web.StreamResponse,
    *,
    request: web.Request,
    session_token: str,
    max_age: int,
) -> None:
    is_secure = request.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
    response.set_cookie(
        COOKIE_NAME,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=is_secure,
        samesite="Strict" if is_secure else "Lax",
    )


async def handle_login_page(request: web.Request) -> web.StreamResponse:
    """Render the login page for unauthenticated users."""
    if get_current_user(request):
        raise web.HTTPFound("/")

    global BOT_USERNAME_CACHE
    if BOT_USERNAME_CACHE is None:
        try:
            bot = request.app.get("bot")
            if bot is not None:
                me = await bot.get_me()
                BOT_USERNAME_CACHE = me.username or ""
        except Exception:
            logging.exception("Failed to fetch bot username")
            BOT_USERNAME_CACHE = ""

    lang_cookie = request.cookies.get("guest_lang", DEFAULT_LANGUAGE)
    lang = lang_cookie if lang_cookie in {"ru", "en"} else DEFAULT_LANGUAGE
    web_meta = getattr(current_config, "WEB_METADATA", {})
    page_title = web_meta.get("title") or TG_BOT_NAME

    keys = [
        "web_error",
        "web_conn_error",
        "modal_title_alert",
        "modal_title_confirm",
        "modal_title_prompt",
        "modal_btn_ok",
        "modal_btn_cancel",
        "login_cookie_title",
        "login_cookie_text",
        "login_cookie_btn",
        "login_support_title",
        "login_support_desc",
        "login_github_tooltip",
        "login_support_tooltip",
        "web_title",
        "web_current_password",
        "web_login_btn",
        "login_forgot_pass",
        "login_secure_gateway",
        "login_pass_btn",
        "login_back_magic",
        "login_or",
        "login_reset_title",
        "login_reset_desc",
        "login_btn_send_link",
        "login_btn_back",
        "btn_back",
        "login_support_btn_pay",
        "login_link_sent_title",
        "login_link_sent_desc",
        "reset_success_title",
        "reset_success_desc",
        "login_error_user_not_found",
        "web_default_pass_alert",
        "web_brand_name",
        "login_telegram_id_label",
        "login_via_telegram_btn",
        "web_perf_mode_on",
        "web_perf_mode_off",
        "web_a11y_mode_on",
        "web_a11y_mode_off",
    ]

    i18n_all: dict[str, dict[str, str]] = {}
    for locale in ("ru", "en"):
        localized = {key: _(key, locale) for key in keys}
        localized["web_error"] = _("web_error", locale, error="")
        localized["web_conn_error"] = _("web_conn_error", locale, error="")
        i18n_all[locale] = localized

    current_i18n = i18n_all.get(lang, i18n_all[DEFAULT_LANGUAGE])
    default_pass_alert = ""
    if is_default_password_active(ADMIN_USER_ID):
        default_pass_alert = (
            '<div class="mb-4 p-3 bg-yellow-500/20 border border-yellow-500/50 rounded-xl flex items-start gap-3">'
            '<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-yellow-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />'
            '</svg>'
            f'<span class="text-xs text-yellow-200 font-medium" data-i18n="web_default_pass_alert">{_("web_default_pass_alert", lang)}</span>'
            '</div>'
        )

    context = {
        "web_title": page_title,
        "web_favicon": web_meta.get("favicon", "/static/favicon.ico"),
        "web_meta_desc": web_meta.get("description", ""),
        "web_meta_keywords": web_meta.get("keywords", ""),
        "default_pass_alert": default_pass_alert,
        "error_block": "",
        "bot_username": BOT_USERNAME_CACHE or "",
        "web_version": str(int(time.time())),
        "current_lang": lang,
        "i18n_json": f"{json.dumps(current_i18n)};\n        const I18N_ALL = {json.dumps(i18n_all)}",
        "login_telegram_id_label": _("login_telegram_id_label", lang),
        "login_via_telegram_btn": _("login_via_telegram_btn", lang),
    }

    template = JINJA_ENV.get_template("login.html")
    response = web.Response(text=template.render(**context), content_type="text/html")
    _set_csrf_cookie(response, request)
    return response


@routes.post("/api/login/request")
async def handle_login_request(request: web.Request) -> web.StreamResponse:
    """Send a one-time magic login link via Telegram."""
    settings = await current_config.get_bot_config("security_settings", {})
    if settings.get("telegram_only_mode", False):
        return web.Response(text="Only Telegram widget login is allowed", status=403)

    data = await request.post()
    try:
        user_id = int(data.get("user_id", 0))
    except Exception:
        user_id = 0

    if user_id not in ALLOWED_USERS:
        return web.Response(text="User not found", status=403)

    login_token = secrets.token_urlsafe(32)
    AUTH_TOKENS[login_token] = {"user_id": user_id, "created_at": time.time()}

    host = request.headers.get("Host", f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
    proto = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
    link = f"{proto}://{host}/api/login/magic?token={login_token}"

    bot = request.app.get("bot")
    if bot is None:
        return web.Response(text="Bot Error", status=500)

    try:
        lang = get_user_lang(user_id)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_("web_login_btn", lang), url=link)]]
        )
        await bot.send_message(
            user_id,
            _("web_login_header", lang),
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return web.HTTPFound("/login?sent=true")
    except Exception:
        logging.exception("Failed to send magic login link")
        return web.Response(text="Bot Error", status=500)


@routes.post("/api/login/password")
async def handle_login_password(request: web.Request) -> web.StreamResponse:
    """Authenticate the main admin by password and create a web session."""
    settings = await current_config.get_bot_config("security_settings", {})
    if settings.get("telegram_only_mode", False):
        return web.Response(
            text="Password login disabled. Only Telegram widget login is allowed.",
            status=403,
        )

    data = await request.post()
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        return web.Response(text="Rate limited. Wait 5 mins.", status=429)

    try:
        user_id = int(data.get("user_id", 0))
    except Exception:
        return web.Response(text="Invalid ID", status=400)

    if user_id != ADMIN_USER_ID:
        return web.Response(text="Password login for Main Admin only.", status=403)

    if check_user_password(user_id, data.get("password")):
        session_token = _create_session(
            request=request,
            user_id=user_id,
            max_age=SESSION_TTL_PASSWORD,
        )
        response = web.HTTPFound("/")
        _set_session_cookie(
            response,
            request=request,
            session_token=session_token,
            max_age=SESSION_TTL_PASSWORD,
        )
        _set_csrf_cookie(response, request)
        return response

    add_login_attempt(client_ip)
    return web.Response(text="Invalid password", status=403)


@routes.get("/api/login/magic")
async def handle_magic_login(request: web.Request) -> web.StreamResponse:
    """Finalize a Telegram-delivered magic link login flow."""
    token = request.query.get("token")
    if not token or token not in AUTH_TOKENS:
        return web.Response(text="Link expired", status=403)

    token_data = AUTH_TOKENS.pop(token)
    if time.time() - float(token_data.get("created_at", 0)) > LOGIN_TOKEN_TTL:
        return web.Response(text="Expired", status=403)

    user_id = int(token_data.get("user_id", 0))
    if user_id not in ALLOWED_USERS:
        return web.Response(text="Denied", status=403)

    session_token = _create_session(
        request=request,
        user_id=user_id,
        max_age=SESSION_TTL_MAGIC,
    )
    response = web.HTTPFound("/")
    _set_session_cookie(
        response,
        request=request,
        session_token=session_token,
        max_age=SESSION_TTL_MAGIC,
    )
    _set_csrf_cookie(response, request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@routes.post("/api/auth/telegram")
async def handle_telegram_auth(request: web.Request) -> web.StreamResponse:
    """Authenticate a user through Telegram Login Widget payload."""
    try:
        data = await request.json()
        if not check_telegram_auth(data, TOKEN):
            return web.json_response({"error": "Invalid hash or expired"}, status=403)

        user_id = int(data.get("id"))
        if user_id not in ALLOWED_USERS:
            return web.json_response({"error": "User not allowed"}, status=403)

        session_token = _create_session(
            request=request,
            user_id=user_id,
            max_age=SESSION_TTL_MAGIC,
            photo_url=data.get("photo_url"),
        )
        csrf_token = generate_csrf_token()
        response = web.json_response({"status": "ok", "csrf_token": csrf_token})
        _set_session_cookie(
            response,
            request=request,
            session_token=session_token,
            max_age=SESSION_TTL_MAGIC,
        )
        _set_csrf_cookie(response, request, token=csrf_token)
        return response
    except Exception:
        logging.exception("Telegram auth failed")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/auth/webapp")
async def handle_webapp_auth(request: web.Request) -> web.StreamResponse:
    """Authenticate a user through Telegram Mini App initData."""
    try:
        data = await request.json()
        init_data = data.get("initData")
        if not init_data:
            return web.json_response({"error": "Missing initData"}, status=400)

        user_data = check_webapp_auth(init_data, TOKEN)
        if not user_data:
            return web.json_response({"error": "Invalid signature or expired"}, status=403)

        user_id = int(user_data.get("id"))
        if user_id not in ALLOWED_USERS:
            return web.json_response({"error": "User not allowed"}, status=403)

        session_token = _create_session(
            request=request,
            user_id=user_id,
            max_age=SESSION_TTL_MAGIC,
            photo_url=user_data.get("photo_url"),
        )
        csrf_token = generate_csrf_token()
        response = web.json_response({"status": "ok", "csrf_token": csrf_token})
        _set_session_cookie(
            response,
            request=request,
            session_token=session_token,
            max_age=SESSION_TTL_MAGIC,
        )
        _set_csrf_cookie(response, request, token=csrf_token)
        return response
    except Exception:
        logging.exception("Web App auth failed")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/logout")
async def handle_logout(request: web.Request) -> web.StreamResponse:
    """Destroy the current web session and redirect to login."""
    session_token = request.cookies.get(COOKIE_NAME)
    if session_token:
        SERVER_SESSIONS.pop(session_token, None)

    is_secure = request.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"
    response = web.HTTPFound("/login")
    response.del_cookie(COOKIE_NAME, secure=is_secure, httponly=True, samesite="Strict" if is_secure else "Lax")
    response.del_cookie(CSRF_TOKEN_COOKIE, secure=is_secure, samesite="Strict" if is_secure else "Lax")
    return response


@routes.post("/api/login/reset")
async def handle_reset_request(request: web.Request) -> web.StreamResponse:
    """Send a password reset link to the main admin via Telegram."""
    try:
        data = await request.json()
        try:
            user_id = int(data.get("user_id", 0))
        except Exception:
            user_id = 0

        if user_id != ADMIN_USER_ID:
            admin_url = (
                f"https://t.me/{ADMIN_USERNAME}"
                if ADMIN_USERNAME
                else f"tg://user?id={ADMIN_USER_ID}"
            )
            return web.json_response({"error": "not_found", "admin_url": admin_url}, status=404)

        reset_token = secrets.token_urlsafe(32)
        RESET_TOKENS[reset_token] = {"ts": time.time(), "user_id": user_id}

        host = request.headers.get("Host", f"{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
        proto = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        link = f"{proto}://{host}/reset_password?token={reset_token}"

        bot = request.app.get("bot")
        if bot is None:
            return web.json_response({"error": "bot_not_ready"}, status=500)

        lang = get_user_lang(user_id)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=_("web_reset_btn", lang), url=link)]]
        )
        await bot.send_message(
            user_id,
            _("web_reset_header", lang),
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Password reset request failed")
        return web.json_response({"error": "Internal Server Error"}, status=500)


async def handle_reset_page_render(request: web.Request) -> web.StreamResponse:
    """Render the password reset page when the token is still valid."""
    token = request.query.get("token")
    if not token or token not in RESET_TOKENS:
        return web.Response(text="Expired", status=403)

    token_data = RESET_TOKENS[token]
    if time.time() - float(token_data.get("ts", 0)) > RESET_TOKEN_TTL:
        RESET_TOKENS.pop(token, None)
        return web.Response(text="Expired", status=403)

    lang_cookie = request.cookies.get("guest_lang", DEFAULT_LANGUAGE)
    lang = lang_cookie if lang_cookie in {"ru", "en"} else DEFAULT_LANGUAGE
    web_meta = getattr(current_config, "WEB_METADATA", {})
    page_title = web_meta.get("title") or f"Reset Password - {TG_BOT_NAME}"

    i18n_data = {
        "web_error": _("web_error", lang, error=""),
        "web_conn_error": _("web_conn_error", lang, error=""),
        "modal_title_alert": _("modal_title_alert", lang),
        "modal_title_confirm": _("modal_title_confirm", lang),
        "modal_title_prompt": _("modal_title_prompt", lang),
        "modal_btn_ok": _("modal_btn_ok", lang),
        "modal_btn_cancel": _("modal_btn_cancel", lang),
        "web_brand_name": _("web_brand_name", lang),
        "reset_page_title": _("login_reset_title", lang),
        "web_new_password": _("web_new_password", lang),
        "web_confirm_password": _("web_confirm_password", lang),
        "web_save_btn": _("web_save_btn", lang),
        "pass_strength_weak": _("pass_strength_weak", lang),
        "pass_strength_fair": _("pass_strength_fair", lang),
        "pass_strength_good": _("pass_strength_good", lang),
        "pass_strength_strong": _("pass_strength_strong", lang),
        "pass_hint_title": _("pass_hint_title", lang),
        "pass_req_length": _("pass_req_length", lang),
        "pass_req_num": _("pass_req_num", lang),
        "pass_match_error": _("pass_match_error", lang),
        "pass_is_empty": _("pass_is_empty", lang),
        "web_redirecting": _("web_redirecting", lang),
        "web_logging_in": _("web_logging_in", lang),
        "web_perf_mode_on": _("web_perf_mode_on", lang),
        "web_perf_mode_off": _("web_perf_mode_off", lang),
        "web_a11y_mode_on": _("web_a11y_mode_on", lang),
        "web_a11y_mode_off": _("web_a11y_mode_off", lang),
    }

    context = {
        "web_title": page_title,
        "web_favicon": web_meta.get("favicon", "/static/favicon.ico"),
        "web_meta_desc": web_meta.get("description", ""),
        "web_meta_keywords": web_meta.get("keywords", ""),
        "web_version": str(int(time.time())),
        "token": token,
        "i18n_json": json.dumps(i18n_data),
    }

    template = JINJA_ENV.get_template("reset_password.html")
    response = web.Response(text=template.render(**context), content_type="text/html")
    _set_csrf_cookie(response, request)
    return response


@routes.post("/api/reset/confirm")
async def handle_reset_confirm(request: web.Request) -> web.StreamResponse:
    """Persist a new admin password after validating the reset token."""
    try:
        data = await request.json()
        token = data.get("token")
        new_password = data.get("password")

        if not token or token not in RESET_TOKENS:
            return web.json_response({"error": "Expired"}, status=403)

        user_id = int(RESET_TOKENS[token].get("user_id", 0))
        if user_id != ADMIN_USER_ID:
            RESET_TOKENS.pop(token, None)
            return web.json_response({"error": "Denied"}, status=403)

        if not isinstance(new_password, str) or len(new_password) < 8:
            return web.json_response(
                {"error": "Password must be at least 8 characters"},
                status=400,
            )

        new_hash = PasswordHasher().hash(new_password)
        current_user = ALLOWED_USERS.get(user_id, {"group": "admins"})
        if isinstance(current_user, str):
            ALLOWED_USERS[user_id] = {"group": current_user, "password_hash": new_hash}
        else:
            current_user["password_hash"] = new_hash
            ALLOWED_USERS[user_id] = current_user

        await save_users_async()
        RESET_TOKENS.pop(token, None)
        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Password reset confirmation failed")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/security/telegram_only_mode")
async def handle_get_telegram_only_mode(request: web.Request) -> web.StreamResponse:
    """Return whether Telegram-only login mode is enabled."""
    try:
        settings = await current_config.get_bot_config("security_settings", {})
        enabled = bool(settings.get("telegram_only_mode", False))
        return web.json_response({"enabled": enabled})
    except Exception:
        logging.exception("Failed to read telegram_only_mode")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/security/telegram_only_mode")
async def handle_set_telegram_only_mode(request: web.Request) -> web.StreamResponse:
    """Allow the main admin to toggle Telegram-only login mode."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if int(user["id"]) != ADMIN_USER_ID:
        return web.json_response({"error": "Main Admin only"}, status=403)

    try:
        data = await request.json()
        enabled = bool(data.get("enabled", False))
        settings = await current_config.get_bot_config("security_settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["telegram_only_mode"] = enabled
        await current_config.set_bot_config("security_settings", settings)
        return web.json_response({"status": "ok", "enabled": enabled})
    except Exception:
        logging.exception("Failed to update telegram_only_mode")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.get("/api/sessions/list")
@routes.get("/sessions/list")
async def api_get_sessions(request: web.Request) -> web.StreamResponse:
    """Return active web sessions for the current user or all sessions for the main admin."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    current_token = request.cookies.get(COOKIE_NAME)
    user_sessions: list[dict[str, Any]] = []
    expired_tokens: list[str] = []
    is_main_admin = int(user["id"]) == ADMIN_USER_ID

    for token, session in list(SERVER_SESSIONS.items()):
        if time.time() > float(session.get("expires", 0)):
            expired_tokens.append(token)
            continue

        session_user_id = int(session.get("id", 0))
        if is_main_admin or session_user_id == int(user["id"]):
            ip_raw = str(session.get("ip", "Unknown"))
            user_sessions.append(
                {
                    "token_prefix": token[:6] + "...",
                    "id": token,
                    "ip": encrypt_for_web(ip_raw),
                    "ua": str(session.get("ua", "Unknown")),
                    "created": float(session.get("created", 0)),
                    "current": token == current_token,
                    "user_id": session_user_id,
                    "user_name": USER_NAMES.get(str(session_user_id), f"ID: {session_user_id}"),
                    "is_mine": session_user_id == int(user["id"]),
                }
            )

    for token in expired_tokens:
        SERVER_SESSIONS.pop(token, None)

    user_sessions.sort(key=lambda item: (not item["current"], not item["is_mine"], item["created"]))
    return web.json_response({"sessions": user_sessions})


@routes.post("/api/sessions/revoke")
@routes.post("/sessions/revoke")
async def api_revoke_session(request: web.Request) -> web.StreamResponse:
    """Revoke a specific web session if it belongs to the current user or caller is the main admin."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        target_token = str(data.get("token", "")).strip()
        current_token = request.cookies.get(COOKIE_NAME)
        if not target_token:
            return web.json_response({"error": "Token required"}, status=400)
        if target_token == current_token:
            return web.json_response({"error": "Cannot revoke current session"}, status=400)

        session = SERVER_SESSIONS.get(target_token)
        if session is None:
            return web.json_response({"error": "Session not found or access denied"}, status=404)

        if int(user["id"]) == ADMIN_USER_ID or int(session.get("id", 0)) == int(user["id"]):
            SERVER_SESSIONS.pop(target_token, None)
            return web.json_response({"status": "ok"})

        return web.json_response({"error": "Session not found or access denied"}, status=404)
    except Exception:
        logging.exception("Failed to revoke session")
        return web.json_response({"error": "Internal Server Error"}, status=500)


@routes.post("/api/sessions/revoke_all")
@routes.post("/sessions/revoke_all")
async def api_revoke_all_sessions(request: web.Request) -> web.StreamResponse:
    """Revoke all other sessions for the current user."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    current_token = request.cookies.get(COOKIE_NAME)
    uid = int(user["id"])
    count = 0
    for token in list(SERVER_SESSIONS.keys()):
        session = SERVER_SESSIONS[token]
        if int(session.get("id", 0)) == uid and token != current_token:
            SERVER_SESSIONS.pop(token, None)
            count += 1

    return web.json_response({"status": "ok", "revoked_count": count})


@routes.post("/api/settings/password")
async def handle_change_password(request: web.Request) -> web.StreamResponse:
    """Allow the main admin to change the current password from settings."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if int(user["id"]) != ADMIN_USER_ID:
        return web.json_response({"error": "Main Admin only"}, status=403)

    try:
        data = await request.json()
        current_password = data.get("current_password")
        new_password = data.get("new_password")

        if not check_user_password(ADMIN_USER_ID, current_password):
            return web.json_response({"error": "Wrong password"}, status=400)
        if not isinstance(new_password, str) or len(new_password) < 8:
            return web.json_response({"error": "Password must be at least 8 characters"}, status=400)

        new_hash = PasswordHasher().hash(new_password)
        current_user = ALLOWED_USERS.get(ADMIN_USER_ID, {"group": "admins"})
        if isinstance(current_user, str):
            ALLOWED_USERS[ADMIN_USER_ID] = {"group": current_user, "password_hash": new_hash}
        else:
            current_user["password_hash"] = new_hash
            ALLOWED_USERS[ADMIN_USER_ID] = current_user

        await save_users_async()
        return web.json_response({"status": "ok"})
    except Exception:
        logging.exception("Password change failed")
        return web.json_response({"error": "Internal Server Error"}, status=500)


__all__ = [
    "routes",
    "SERVER_SESSIONS",
    "RESET_TOKENS",
    "CSRF_TOKENS",
    "generate_csrf_token",
    "verify_csrf_token",
    "get_current_user",
    "handle_login_page",
    "handle_login_request",
    "handle_login_password",
    "handle_magic_login",
    "handle_telegram_auth",
    "handle_logout",
    "handle_reset_request",
    "handle_reset_page_render",
    "handle_reset_confirm",
    "is_default_password_active",
]
