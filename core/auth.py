# /opt/tg-bot/core/auth.py
import os
import json
import logging
import urllib.parse
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from .config import USERS_FILE, ADMIN_USER_ID, ADMIN_USERNAME, INSTALL_MODE
from .shared_state import ALLOWED_USERS, USER_NAMES, LAST_MESSAGE_IDS
from .messaging import delete_previous_message
from .utils import escape_html

def load_users():
    """Загружает ALLOWED_USERS и USER_NAMES из shared_state"""
    global ALLOWED_USERS, USER_NAMES
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                ALLOWED_USERS = {int(user["id"]): user["group"] for user in data.get("allowed_users", [])}
                USER_NAMES = data.get("user_names", {})

        if ADMIN_USER_ID not in ALLOWED_USERS:
            ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
            USER_NAMES[str(ADMIN_USER_ID)] = "Главный Админ"
            save_users()

        logging.info(f"Пользователи загружены. Разрешено ID: {list(ALLOWED_USERS.keys())}")
    except Exception as e:
        logging.error(f"Критическая ошибка загрузки users.json: {e}")
        ALLOWED_USERS = {ADMIN_USER_ID: "Админы"}
        USER_NAMES = {str(ADMIN_USER_ID): "Главный Админ"}
        save_users()

def save_users():
    """Сохраняет ALLOWED_USERS и USER_NAMES в shared_state"""
    try:
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        data = {
            "allowed_users": [{"id": uid, "group": group} for uid, group in ALLOWED_USERS.items()],
            "user_names": user_names_to_save
        }
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logging.info(f"Успешно сохранено users.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}")

def is_allowed(user_id, command=None):
    if user_id not in ALLOWED_USERS:
        return False

    user_commands = ["start", "menu", "back_to_menu", "uptime", "traffic", "selftest", "get_id", "get_id_inline", "notifications_menu", "toggle_alert_resources", "toggle_alert_logins", "toggle_alert_bans", "alert_downtime_stub"]
    if command in user_commands:
        return True

    is_admin_group = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    if not is_admin_group:
        return False

    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray", "adduser", "add_user"
    ]
    if command in admin_only_commands:
        return True

    root_only_commands = [
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs", "restart", "update"
    ]
    if command in root_only_commands:
        return INSTALL_MODE == "root"

    # Добавил команды, которых не хватало для проверки
    if command and any(cmd in command for cmd in ["delete_user", "set_group", "change_group", "xray_install", "back_to_manage_users", "back_to_delete_users"]):
        return True

    return False

async def refresh_user_names(bot: Bot):
    global USER_NAMES
    needs_save = False
    user_ids_to_check = list(ALLOWED_USERS.keys())
    logging.info(f"Начинаю обновление имен для {len(user_ids_to_check)} пользователей...")

    for uid in user_ids_to_check:
        uid_str = str(uid)
        current_name = USER_NAMES.get(uid_str)

        should_refresh = (
            not current_name
            or current_name.startswith("Новый_")
            or current_name.startswith("ID: ")
            or current_name == "Главный Админ"
        )

        if should_refresh:
            try:
                logging.debug(f"Пытаюсь получить имя для ID: {uid}")
                chat = await bot.get_chat(uid)
                new_name = chat.first_name or chat.username
                if not new_name:
                    new_name = f"ID: {uid}"
                    logging.warning(f"Не удалось получить Имя/Юзернейм для {uid}, использую '{new_name}'")
                else:
                    new_name = escape_html(new_name)

                if current_name != new_name:
                    logging.info(f"Обновлено имя для {uid}: '{current_name}' -> '{new_name}'")
                    USER_NAMES[uid_str] = new_name
                    needs_save = True
                else:
                    logging.debug(f"Имя для {uid} не изменилось ('{current_name}').")

            except TelegramBadRequest as e:
                if "chat not found" in str(e) or "bot was blocked by the user" in str(e):
                     logging.warning(f"Не удалось обновить имя для {uid}: {e}. Использую 'ID: {uid}'.")
                     if current_name != f"ID: {uid}":
                          USER_NAMES[uid_str] = f"ID: {uid}"
                          needs_save = True
                else:
                     logging.error(f"Непредвиденная ошибка Telegram API при получении имени для {uid}: {e}")
                     if not current_name or current_name.startswith("Новый_"):
                          USER_NAMES[uid_str] = f"ID: {uid}"
                          needs_save = True
            except Exception as e:
                logging.error(f"Непредвиденная ошибка при обновлении имени для {uid}: {e}")
                if not current_name or current_name.startswith("Новый_"):
                     USER_NAMES[uid_str] = f"ID: {uid}"
                     needs_save = True

    if needs_save:
        logging.info("Обнаружены изменения в именах, сохраняю users.json...")
        save_users()
    else:
        logging.info("Обновление имен завершено, изменений не найдено.")

async def get_user_name(bot: Bot, user_id: int) -> str:
    try:
        cached_name = USER_NAMES.get(str(user_id))
        if cached_name and "Unknown" not in cached_name and "Главный Админ" not in cached_name:
            return cached_name

        chat = await bot.get_chat(user_id)
        name = chat.first_name or chat.username or f"Unknown_{user_id}"
        USER_NAMES[str(user_id)] = name
        save_users()
        return name
    except Exception as e:
        logging.error(f"Ошибка получения имени для ID {user_id}: {e}")
        return f"Unknown_{user_id}"

async def send_access_denied_message(bot: Bot, user_id: int, chat_id: int, command: str):
    await delete_previous_message(user_id, command, chat_id, bot)

    text_to_send = f"мой ID: {user_id}"
    admin_link = ""

    if ADMIN_USERNAME:
        admin_link = f"https://t.me/{ADMIN_USERNAME}?text={urllib.parse.quote(text_to_send)}"
    else:
        admin_link = f"tg://user?id={ADMIN_USER_ID}&text={urllib.parse.quote(text_to_send)}"
        logging.warning("Переменная TG_ADMIN_USERNAME не установлена. Используется ссылка по ID (открывает профиль).")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить свой ID администратору", url=admin_link)]
    ])
    sent_message = await bot.send_message(
        chat_id,
        f"⛔ Вы не являетесь пользователем бота. Ваш ID: <code>{user_id}</code>.\n"
        "К командам нет доступа, обратитесь к администратору.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id