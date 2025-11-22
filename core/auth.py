import os
import json
import logging
import urllib.parse
import hashlib
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from . import config
from .i18n import _
from .config import USERS_FILE, ADMIN_USER_ID, ADMIN_USERNAME, INSTALL_MODE
from .shared_state import ALLOWED_USERS, USER_NAMES, LAST_MESSAGE_IDS
from .messaging import delete_previous_message
from .utils import escape_html


def load_users():
    """Загружает данные пользователей в ALLOWED_USERS."""
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)

        ALLOWED_USERS.clear()
        USER_NAMES.clear()

        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                
                for user in data.get("allowed_users", []):
                    uid = int(user["id"])
                    # Поддержка миграции со старого формата
                    group = user.get("group", "users")
                    password_hash = user.get("password_hash", None)
                    
                    ALLOWED_USERS[uid] = {
                        "group": group,
                        "password_hash": password_hash
                    }

                USER_NAMES.update(data.get("user_names", {}))
        else:
            logging.warning(f"Файл {USERS_FILE} не найден. Инициализация.")

        # Гарантируем наличие главного админа
        if ADMIN_USER_ID not in ALLOWED_USERS:
            logging.info(f"Главный админ ID {ADMIN_USER_ID} не найден, добавляю.")
            # Дефолтный хеш для "admin" (sha256)
            default_hash = "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"
            
            ALLOWED_USERS[ADMIN_USER_ID] = {
                "group": "admins",
                "password_hash": default_hash 
            }
            USER_NAMES[str(ADMIN_USER_ID)] = _("default_admin_name", config.DEFAULT_LANGUAGE)
            save_users()
        
        # Миграция старой записи админа (если вдруг в памяти строка)
        elif isinstance(ALLOWED_USERS[ADMIN_USER_ID], str):
             ALLOWED_USERS[ADMIN_USER_ID] = {"group": "admins", "password_hash": None}

        logging.info(f"Пользователи загружены: {len(ALLOWED_USERS)}")

    except Exception as e:
        logging.error(f"Критическая ошибка загрузки users.json: {e}", exc_info=True)
        # Аварийное восстановление доступа админа
        ALLOWED_USERS[ADMIN_USER_ID] = {"group": "admins", "password_hash": None}
        save_users()


def save_users():
    """Сохраняет пользователей в users.json."""
    try:
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        
        allowed_users_to_save = []
        for uid, data in ALLOWED_USERS.items():
            if isinstance(data, str):
                group = data
                p_hash = None
            else:
                group = data.get("group", "users")
                p_hash = data.get("password_hash")
            
            allowed_users_to_save.append({
                "id": int(uid),
                "group": group,
                "password_hash": p_hash
            })

        data = {
            "allowed_users": allowed_users_to_save,
            "user_names": user_names_to_save
        }
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush() 
            os.fsync(f.fileno())
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}", exc_info=True)


def is_allowed(user_id, command=None):
    """Проверяет права доступа."""
    if user_id not in ALLOWED_USERS:
        return False

    user_data = ALLOWED_USERS[user_id]
    user_group = user_data if isinstance(user_data, str) else user_data.get("group", "users")

    user_commands = [
        "start", "menu", "back_to_menu", "uptime", "traffic", "selftest",
        "get_id", "get_id_inline", "notifications_menu", "toggle_alert_resources",
        "toggle_alert_logins", "toggle_alert_bans", "alert_downtime_stub",
        "language"
    ]
    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray",
        "adduser", "add_user", "delete_user", "set_group", "change_group",
        "back_to_manage_users", "back_to_delete_users",
        "nodes", "node_add_new", "nodes_list_refresh" 
    ]
    root_only_commands = [
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs",
        "restart", "update", "optimize"
    ]

    if command in user_commands:
        return True

    is_admin_group = (user_id == ADMIN_USER_ID) or (user_group == "admins")

    if command in admin_only_commands:
        return is_admin_group

    if command in root_only_commands:
        if INSTALL_MODE == "root" and is_admin_group:
            return True
        return False

    if command and (command.startswith("delete_user_") or
                    command.startswith("request_self_delete_") or
                    command.startswith("confirm_self_delete_") or
                    command.startswith("select_user_change_group_") or
                    command.startswith("set_group_") or
                    command.startswith("node_select_") or
                    command.startswith("node_delete_") or
                    command.startswith("node_cmd_")):
        return is_admin_group

    return True


async def refresh_user_names(bot: Bot):
    needs_save = False
    user_ids_to_check = list(ALLOWED_USERS.keys())

    lang = config.DEFAULT_LANGUAGE
    new_user_prefix = _("default_new_user_name", lang, uid="").split('_')[0]
    id_user_prefix = _("default_id_user_name", lang, uid="").split(' ')[0]
    admin_name_default = _("default_admin_name", lang)

    for uid in user_ids_to_check:
        uid_str = str(uid)
        current_name = USER_NAMES.get(uid_str)

        should_refresh = (
            not current_name
            or current_name.startswith(new_user_prefix)
            or current_name.startswith(id_user_prefix)
            or (current_name == admin_name_default and uid == ADMIN_USER_ID)
        )

        if should_refresh:
            new_name = _("default_id_user_name", lang, uid=uid)
            try:
                chat = await bot.get_chat(uid)
                fetched_name = chat.first_name or chat.username
                if fetched_name:
                    new_name = escape_html(fetched_name)

                if current_name != new_name:
                    USER_NAMES[uid_str] = new_name
                    needs_save = True

            except TelegramBadRequest as e:
                if "chat not found" in str(e).lower() or "bot was blocked by the user" in str(e).lower():
                    if current_name != new_name:
                        USER_NAMES[uid_str] = new_name
                        needs_save = True
                else:
                    logging.error(f"Ошибка Telegram API при обновлении имени для {uid}: {e}")
            except Exception as e:
                logging.error(f"Ошибка при обновлении имени для {uid}: {e}")

    if needs_save:
        save_users()


async def get_user_name(bot: Bot, user_id: int) -> str:
    uid_str = str(user_id)
    cached_name = USER_NAMES.get(uid_str)

    lang = config.DEFAULT_LANGUAGE
    try:
        from .i18n import get_user_lang
        lang = get_user_lang(user_id)
    except ImportError: pass
    except Exception: pass

    new_user_prefix = _("default_new_user_name", lang, uid="").split('_')[0]
    id_user_prefix = _("default_id_user_name", lang, uid="").split(' ')[0]

    if cached_name and not cached_name.startswith(new_user_prefix) and not cached_name.startswith(id_user_prefix):
        return cached_name

    new_name = _("default_id_user_name", lang, uid=user_id)
    try:
        chat = await bot.get_chat(user_id)
        fetched_name = chat.first_name or chat.username
        if fetched_name:
            new_name = escape_html(fetched_name)
            USER_NAMES[uid_str] = new_name
            save_users()
            return new_name
        else:
            if cached_name != new_name:
                USER_NAMES[uid_str] = new_name
                save_users()
            return new_name
    except Exception as e:
        logging.error(f"Ошибка получения имени для ID {user_id}: {e}")
        if cached_name != new_name:
            USER_NAMES[uid_str] = new_name
            save_users()
        return new_name


async def send_access_denied_message(bot: Bot, user_id: int, chat_id: int, command: str):
    await delete_previous_message(user_id, command, chat_id, bot)

    lang = config.DEFAULT_LANGUAGE
    try:
        from .i18n import get_user_lang
        lang = get_user_lang(user_id)
    except Exception: pass

    text_to_send = f"my ID: {user_id}"
    admin_link = ""

    if ADMIN_USERNAME:
        admin_link = f"https://t.me/{ADMIN_USERNAME}?text={urllib.parse.quote(text_to_send)}"
    else:
        admin_link = f"tg://user?id={ADMIN_USER_ID}"

    button_text = _("access_denied_button", lang)
    message_text = _("access_denied_message", lang, user_id=user_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text, url=admin_link)]
    ])
    try:
        sent_message = await bot.send_message(chat_id, message_text, reply_markup=keyboard, parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение об отказе в доступе пользователю {user_id}: {e}")