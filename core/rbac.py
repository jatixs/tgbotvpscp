"""
core/rbac.py — централизованный модуль контроля доступа (RBAC).

Иерархия ролей:
  root  — ADMIN_USER_ID из .env, полный доступ
  admin — group == "admins", управление нодами/пользователями/сервисами
  user  — group == "users",  только просмотр статистики

Все остальные модули должны импортировать хелперы отсюда
вместо того чтобы дублировать логику на месте.
"""
from __future__ import annotations

from typing import Any

from .config import ADMIN_USER_ID
from .shared_state import ALLOWED_USERS
from .utils import get_web_key

# Строковые константы ролей, используемые в ALLOWED_USERS["group"]
ROLE_USER: str = "users"
ROLE_ADMIN: str = "admins"


# ---------------------------------------------------------------------------
# Web-контекст: user — dict из серверной сессии {"id": int, "role": str, ...}
# ---------------------------------------------------------------------------

def is_admin(user: dict[str, Any]) -> bool:
    """Root и Admin → True; User → False."""
    return bool(
        user.get("role") == ROLE_ADMIN
        or int(user.get("id", 0)) == ADMIN_USER_ID
    )


def is_root(user: dict[str, Any]) -> bool:
    """True только для главного администратора (Owner/Root)."""
    return int(user.get("id", 0)) == ADMIN_USER_ID


# ---------------------------------------------------------------------------
# Bot/service-контекст: принимает Telegram user_id (int)
# ---------------------------------------------------------------------------

def get_role_level(user_id: int) -> int:
    """
    Числовой уровень прав пользователя:
      0 — только просмотр (User)
      1 — запуск / рестарт сервисов (Admin)
      2 — полный контроль, включая остановку (Root)
    """
    if user_id == ADMIN_USER_ID:
        return 2

    user_data = ALLOWED_USERS.get(user_id)
    if not user_data:
        return 0

    group = user_data.get("group", ROLE_USER) if isinstance(user_data, dict) else user_data
    return 1 if group == ROLE_ADMIN else 0


# ---------------------------------------------------------------------------
# Утилита для шаблонов
# ---------------------------------------------------------------------------

def build_user_role_js(role: str, user_id: int) -> str:
    """Генерирует инлайн-JS со строками USER_ROLE, IS_MAIN_ADMIN, WEB_KEY."""
    is_main = str(user_id == ADMIN_USER_ID).lower()
    return (
        f"const USER_ROLE = '{role}'; "
        f"const IS_MAIN_ADMIN = {is_main}; "
        f"const WEB_KEY = '{get_web_key()}';"
    )
