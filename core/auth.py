# /opt-tg-bot/core/auth.py
import os
import json
import logging 
import urllib.parse
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# --- ИЗМЕНЕНО: Добавлены импорты i18n и config ---
from . import config # Нужен для DEFAULT_LANGUAGE
from .core.i18n import _
# -----------------------------------------------

from .config import USERS_FILE, ADMIN_USER_ID, ADMIN_USERNAME, INSTALL_MODE
from .shared_state import ALLOWED_USERS, USER_NAMES, LAST_MESSAGE_IDS
from .messaging import delete_previous_message
from .utils import escape_html

def load_users():
    """Загружает ALLOWED_USERS и USER_NAMES из users.json в shared_state"""
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        
        ALLOWED_USERS.clear()
        USER_NAMES.clear()

        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                ALLOWED_USERS.update({int(user["id"]): user["group"] for user in data.get("allowed_users", [])})
                USER_NAMES.update(data.get("user_names", {}))
        else:
            logging.warning(f"Файл {USERS_FILE} не найден. Инициализация пустых списков пользователей.")

        # Всегда убеждаемся, что главный админ присутствует
        if ADMIN_USER_ID not in ALLOWED_USERS:
            logging.info(f"Главный админ ID {ADMIN_USER_ID} не найден в users.json, добавляю.")
            ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
            # --- ИЗМЕНЕНО: Используем i18n для имени по умолчанию ---
            USER_NAMES[str(ADMIN_USER_ID)] = _("default_admin_name", config.DEFAULT_LANGUAGE)
            # ----------------------------------------------------
            save_users() 

        logging.info(f"Пользователи загружены. Разрешенные ID: {list(ALLOWED_USERS.keys())}")

    except json.JSONDecodeError as e:
        logging.error(f"Критическая ошибка загрузки users.json: Неверный JSON - {e}")
        ALLOWED_USERS.clear()
        USER_NAMES.clear()
        ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
        # --- ИЗМЕНЕНО: Используем i18n ---
        USER_NAMES[str(ADMIN_USER_ID)] = _("default_admin_name", config.DEFAULT_LANGUAGE)
        # ---------------------------------
        save_users()
    except Exception as e:
        logging.error(f"Критическая ошибка загрузки users.json: {e}", exc_info=True)
        ALLOWED_USERS.clear()
        USER_NAMES.clear()
        ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
        # --- ИЗМЕНЕНО: Используем i18n ---
        USER_NAMES[str(ADMIN_USER_ID)] = _("default_admin_name", config.DEFAULT_LANGUAGE)
        # ---------------------------------
        save_users()

def save_users():
    """Сохраняет ALLOWED_USERS и USER_NAMES из shared_state в users.json"""
    try:
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        allowed_users_to_save = [{"id": int(uid), "group": group} for uid, group in ALLOWED_USERS.items()]

        data = {
            "allowed_users": allowed_users_to_save,
            "user_names": user_names_to_save
        }
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logging.info(f"Успешно сохранено users.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}", exc_info=True)

def is_allowed(user_id, command=None):
    """Проверяет, имеет ли пользователь доступ к команде."""
    logging.info(f"Проверка is_allowed для user_id: {user_id}, command: '{command}'")
    logging.debug(f"Текущие ключи ALLOWED_USERS: {list(ALLOWED_USERS.keys())}")

    if user_id not in ALLOWED_USERS:
        logging.warning(f"Пользователь {user_id} НЕ найден в ALLOWED_USERS для команды '{command}'. Доступ запрещен.")
        return False

    # Определяем группы команд
    user_commands = [
        "start", "menu", "back_to_menu", "uptime", "traffic", "selftest",
        "get_id", "get_id_inline", "notifications_menu", "toggle_alert_resources",
        "toggle_alert_logins", "toggle_alert_bans", "alert_downtime_stub",
        "language" # <-- ДОБАВЛЕНО: Команда смены языка
    ]
    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray",
        "adduser", "add_user", "delete_user", "set_group", "change_group",
        "back_to_manage_users", "back_to_delete_users"
    ]
    root_only_commands = [
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs", "restart", "update",
        "optimize"
    ]

    if command in user_commands:
        logging.debug(f"Команда '{command}' разрешена для всех пользователей. Доступ для {user_id} предоставлен.")
        return True 

    is_admin_group = (user_id == ADMIN_USER_ID) or (ALLOWED_USERS.get(user_id) == "Админы")

    if command in admin_only_commands:
        if is_admin_group:
            logging.debug(f"Команда '{command}' разрешена для админов. Доступ для админа {user_id} предоставлен.")
            return True
        else:
            logging.warning(f"Команда '{command}' требует прав админа. Доступ для пользователя {user_id} запрещен.")
            return False

    if command in root_only_commands:
        if INSTALL_MODE == "root" and is_admin_group:
             logging.debug(f"Команда '{command}' разрешена для админов в root-режиме. Доступ для админа {user_id} предоставлен.")
             return True
        elif INSTALL_MODE != "root":
            logging.warning(f"Команда '{command}' требует root-режима установки. Доступ для {user_id} запрещен (текущий режим: {INSTALL_MODE}).")
            return False
        else: 
            logging.warning(f"Команда '{command}' требует прав админа даже в root-режиме. Доступ для пользователя {user_id} запрещен.")
            return False

    if is_admin_group:
         logging.warning(f"Команда '{command}' не перечислена явно, но разрешаю админу {user_id} по умолчанию.")
         return True
    else:
         logging.warning(f"Команда '{command}' не перечислена явно. Доступ для не-админа {user_id} запрещен.")
         return False

async def refresh_user_names(bot: Bot):
    """Обновляет имена пользователей, особенно новых или с плейсхолдерами."""
    needs_save = False
    user_ids_to_check = list(ALLOWED_USERS.keys())
    logging.info(f"Начинаю обновление имен для {len(user_ids_to_check)} пользователей...")

    # --- ИЗМЕНЕНО: Получаем переводы плейсхолдеров ---
    # Мы используем язык по умолчанию, т.к. эта функция фоновая
    lang = config.DEFAULT_LANGUAGE
    new_user_prefix = _("default_new_user_name", lang, uid="").split('_')[0] # "Новый"
    id_user_prefix = _("default_id_user_name", lang, uid="").split(' ')[0]   # "ID:"
    admin_name_default = _("default_admin_name", lang)
    # --------------------------------------------------

    for uid in user_ids_to_check:
        uid_str = str(uid)
        current_name = USER_NAMES.get(uid_str)

        should_refresh = (
            not current_name
            or current_name.startswith(new_user_prefix) # "Новый_..."
            or current_name.startswith(id_user_prefix)  # "ID: ..."
            or (current_name == admin_name_default and uid == ADMIN_USER_ID) # "Главный Админ"
        )

        if should_refresh:
            # --- ИЗМЕНЕНО: Используем i18n ---
            new_name = _("default_id_user_name", lang, uid=uid) # Запасное имя "ID: {uid}"
            # ----------------------------------
            try:
                logging.debug(f"Пытаюсь получить информацию о чате для ID: {uid}")
                chat = await bot.get_chat(uid)
                fetched_name = chat.first_name or chat.username
                if fetched_name:
                    new_name = escape_html(fetched_name) 
                else:
                    logging.warning(f"Не удалось получить Имя/Юзернейм для {uid}, использую запасное '{new_name}'")

                if current_name != new_name:
                    logging.info(f"Имя обновлено для {uid}: '{current_name}' -> '{new_name}'")
                    USER_NAMES[uid_str] = new_name
                    needs_save = True
                else:
                    logging.debug(f"Имя для {uid} не изменилось ('{current_name}').")

            except TelegramBadRequest as e:
                if "chat not found" in str(e).lower() or "bot was blocked by the user" in str(e).lower():
                     logging.warning(f"Не удалось обновить имя для {uid}: {e}. Использую запасное '{new_name}'.")
                     if current_name != new_name:
                          USER_NAMES[uid_str] = new_name
                          needs_save = True
                else:
                     logging.error(f"Неожиданная ошибка Telegram API при получении имени для {uid}: {e}")
                     if not current_name or current_name.startswith(new_user_prefix):
                          USER_NAMES[uid_str] = new_name
                          needs_save = True
            except Exception as e:
                logging.error(f"Неожиданная ошибка при обновлении имени для {uid}: {e}", exc_info=True)
                if not current_name or current_name.startswith(new_user_prefix):
                     USER_NAMES[uid_str] = new_name
                     needs_save = True

    if needs_save:
        logging.info("Обнаружены изменения в именах, сохраняю users.json...")
        save_users()
    else:
        logging.info("Обновление имен завершено, изменений не найдено.")

async def get_user_name(bot: Bot, user_id: int) -> str:
    """Получает имя пользователя из кеша или запрашивает его."""
    uid_str = str(user_id)
    cached_name = USER_NAMES.get(uid_str)
    
    # --- ИЗМЕНЕНО: Получаем язык пользователя для плейсхолдеров ---
    lang = config.DEFAULT_LANGUAGE # По умолчанию
    try:
        # Пытаемся получить реальный язык пользователя, если он уже задан
        from .core.i18n import get_user_lang
        lang = get_user_lang(user_id)
    except ImportError:
        pass # Произойдет, если i18n еще не загружен

    new_user_prefix = _("default_new_user_name", lang, uid="").split('_')[0]
    id_user_prefix = _("default_id_user_name", lang, uid="").split(' ')[0]
    # --------------------------------------------------------------

    if cached_name and not cached_name.startswith(new_user_prefix) and not cached_name.startswith(id_user_prefix):
        return cached_name

    logging.debug(f"Имя для {user_id} не кешировано или является плейсхолдером ('{cached_name}'). Запрашиваю...")
    # --- ИЗМЕНЕНО: Используем i18n ---
    new_name = _("default_id_user_name", lang, uid=user_id) # Запасной вариант "ID: {user_id}"
    # ----------------------------------
    try:
        chat = await bot.get_chat(user_id)
        fetched_name = chat.first_name or chat.username
        if fetched_name:
            new_name = escape_html(fetched_name)
            USER_NAMES[uid_str] = new_name 
            save_users() 
            logging.info(f"Получено и кешировано имя для {user_id}: '{new_name}'")
            return new_name
        else:
            logging.warning(f"Получен чат для {user_id}, но имя/юзернейм не найдены. Использую запасное.")
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
    """Отправляет сообщение об отказе в доступе."""
    await delete_previous_message(user_id, command, chat_id, bot)

    # --- ИЗМЕНЕНО: Используем i18n ---
    # Получаем язык пользователя, чтобы кнопка и текст были на его языке
    from .core.i18n import get_user_lang
    lang = get_user_lang(user_id)

    text_to_send = f"my ID: {user_id}"
    admin_link = ""

    if ADMIN_USERNAME:
        admin_link = f"https://t.me/{ADMIN_USERNAME}?text={urllib.parse.quote(text_to_send)}"
    else:
        admin_link = f"tg://user?id={ADMIN_USER_ID}"
        logging.warning("Переменная TG_ADMIN_USERNAME не установлена. Используется ссылка по ID (открывает профиль).")

    button_text = _("access_denied_button", lang)
    message_text = _("access_denied_message", lang, user_id=user_id)
    # ----------------------------------

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text, url=admin_link)]
    ])
    try:
        sent_message = await bot.send_message(
            chat_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение об отказе в доступе пользователю {user_id}: {e}")