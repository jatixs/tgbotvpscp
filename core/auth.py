# /opt-tg-bot/core/auth.py
import os
import json
import logging
import urllib.parse
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# --- ИЗМЕНЕНО: Исправлен путь импорта ---
from . import config  # Нужен для DEFAULT_LANGUAGE
from .i18n import _  # Убрано .core
# -----------------------------------------------

from .config import USERS_FILE, ADMIN_USER_ID, ADMIN_USERNAME, INSTALL_MODE
# --- ИСПРАВЛЕНИЕ: Добавляем ALERTS_CONFIG, USER_SETTINGS для удаления пользователя ---
from .shared_state import ALLOWED_USERS, USER_NAMES, LAST_MESSAGE_IDS, ALERTS_CONFIG, USER_SETTINGS
# --------------------------------------------------------------------------
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
                # --- ИСПРАВЛЕНИЕ: Используем ключ 'admins'/'users' при загрузке ---
                ALLOWED_USERS.update(
                    {int(user["id"]): user["group"] for user in data.get("allowed_users", [])})
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                USER_NAMES.update(data.get("user_names", {}))
        else:
            logging.warning(
                f"Файл {USERS_FILE} не найден. Инициализация пустых списков пользователей.")

        # Всегда убеждаемся, что главный админ присутствует
        if ADMIN_USER_ID not in ALLOWED_USERS:
            logging.info(
                f"Главный админ ID {ADMIN_USER_ID} не найден в users.json, добавляю.")
            # --- ИСПРАВЛЕНИЕ: Используем ключ 'admins' ---
            ALLOWED_USERS[ADMIN_USER_ID] = "admins"
            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
            USER_NAMES[str(ADMIN_USER_ID)] = _(
                "default_admin_name", config.DEFAULT_LANGUAGE)
            save_users()  # Сохраняем сразу после добавления главного админа

        logging.info(
            f"Пользователи загружены. Разрешенные ID: {list(ALLOWED_USERS.keys())}")

    except json.JSONDecodeError as e:
        logging.error(
            f"Критическая ошибка загрузки users.json: Неверный JSON - {e}")
        ALLOWED_USERS.clear()
        USER_NAMES.clear()
        # --- ИСПРАВЛЕНИЕ: Используем ключ 'admins' ---
        ALLOWED_USERS[ADMIN_USER_ID] = "admins"
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
        USER_NAMES[str(ADMIN_USER_ID)] = _(
            "default_admin_name", config.DEFAULT_LANGUAGE)
        save_users()  # Сохраняем базовую конфигурацию
    except Exception as e:
        logging.error(
            f"Критическая ошибка загрузки users.json: {e}",
            exc_info=True)
        ALLOWED_USERS.clear()
        USER_NAMES.clear()
        # --- ИСПРАВЛЕНИЕ: Используем ключ 'admins' ---
        ALLOWED_USERS[ADMIN_USER_ID] = "admins"
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
        USER_NAMES[str(ADMIN_USER_ID)] = _(
            "default_admin_name", config.DEFAULT_LANGUAGE)
        save_users()  # Сохраняем базовую конфигурацию


def save_users():
    """Сохраняет ALLOWED_USERS и USER_NAMES из shared_state в users.json"""
    try:
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        # --- ИСПРАВЛЕНИЕ: Сохраняем ключ 'admins'/'users' ---
        allowed_users_to_save = [
            {"id": int(uid), "group": group_key} for uid, group_key in ALLOWED_USERS.items()]
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

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
    logging.info(
        f"Проверка is_allowed для user_id: {user_id}, command: '{command}'")
    logging.debug(f"Текущие ключи ALLOWED_USERS: {list(ALLOWED_USERS.keys())}")

    # --- НАЧАЛО ИСПРАВЛЕНИЯ ---
    # 1. Проверяем, есть ли пользователь вообще в списке разрешенных
    if user_id not in ALLOWED_USERS:
        logging.warning(
            f"Пользователь {user_id} НЕ найден в ALLOWED_USERS для команды '{command}'. Доступ запрещен.")
        return False

    # 2. Получаем ключ группы пользователя ('admins' или 'users')
    user_group_key = ALLOWED_USERS.get(user_id)
    # Определяем, является ли пользователь админом (Главный админ ИЛИ группа 'admins')
    # Эта проверка теперь надежна, т.к. использует ключ 'admins'
    is_admin_group = (user_id == ADMIN_USER_ID) or (user_group_key == "admins")
    logging.debug(
        f"User {user_id}: group_key='{user_group_key}', is_admin_group={is_admin_group}")

    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    # Определяем группы команд
    user_commands = [
        "start",
        "menu",
        "back_to_menu",
        "uptime",
        "traffic",
        "selftest",
        "get_id",
        "get_id_inline",
        "notifications_menu",
        "toggle_alert_resources",
        "toggle_alert_logins",
        "toggle_alert_bans",
        "alert_downtime_stub",
        "language"]
    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray",
        "adduser", "add_user", "delete_user", "set_group", "change_group",
        "back_to_manage_users", "back_to_delete_users"
    ]
    root_only_commands = [
        "reboot_confirm",
        "reboot",
        "fall2ban",  # Убедитесь, что здесь правильное имя, возможно "fail2ban"?
        "sshlog",
        "logs",
        "restart",
        "update",
        "optimize"]

    # --- Проверка доступа ---
    if command in user_commands:
        logging.debug(
            f"Команда '{command}' разрешена для всех пользователей. Доступ для {user_id} предоставлен.")
        return True

    if command in admin_only_commands:
        if is_admin_group:
            logging.debug(
                f"Команда '{command}' разрешена для админов. Доступ для админа {user_id} предоставлен.")
            return True
        else:
            logging.warning(
                f"Команда '{command}' требует прав админа. Доступ для пользователя {user_id} (группа: {user_group_key}) запрещен.")
            return False

    if command in root_only_commands:
        # --- ИСПРАВЛЕНИЕ: Убеждаемся, что оба условия проверяются правильно ---
        if INSTALL_MODE == "root" and is_admin_group:
            # Важно: Оба условия должны быть True
            logging.debug(
                f"Команда '{command}' разрешена для админов в root-режиме. Доступ для админа {user_id} предоставлен.")
            return True
        elif INSTALL_MODE != "root":
            logging.warning(
                f"Команда '{command}' требует root-режима установки. Доступ для {user_id} запрещен (текущий режим: {INSTALL_MODE}).")
            return False
        elif not is_admin_group:  # Добавлено явное условие
            logging.warning(
                f"Команда '{command}' требует прав админа (даже в root-режиме). Доступ для пользователя {user_id} (группа: {user_group_key}) запрещен.")
            return False
        else:  # Непредвиденный случай
            logging.error(
                f"Непредвиденная комбинация для root команды '{command}': режим={INSTALL_MODE}, админ={is_admin_group}. Доступ запрещен.")
            return False
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    # --- Обработка динамических callback_data ---
    # (Эта часть уже должна работать правильно после исправления is_admin_group)
    if isinstance(command, str):
        parts = command.split('_')
        base_command = parts[0]
        # Проверяем команды управления пользователями, требующие прав админа
        if base_command in [
            "delete",
            "request",
            "confirm",
            "select",
                "set"] and len(parts) > 1:
            if is_admin_group:
                logging.debug(
                    f"Динамическая команда '{command}' разрешена для админа {user_id}.")
                return True
            else:
                logging.warning(
                    f"Динамическая команда '{command}' требует прав админа. Доступ для пользователя {user_id} (группа: {user_group_key}) запрещен.")
                return False

    # Если команда не найдена ни в одном списке и не является динамической
    logging.warning(
        f"Команда '{command}' не найдена в списках доступа или не распознана как динамическая. Доступ для {user_id} запрещен по умолчанию.")
    return False


async def refresh_user_names(bot: Bot):
    """Обновляет имена пользователей, особенно новых или с плейсхолдерами."""
    needs_save = False
    user_ids_to_check = list(ALLOWED_USERS.keys())
    logging.info(
        f"Начинаю обновление имен для {len(user_ids_to_check)} пользователей...")

    lang = config.DEFAULT_LANGUAGE
    new_user_prefix = _("default_new_user_name", lang, uid="").split('_')[0]
    id_user_prefix = _("default_id_user_name", lang, uid="").split(' ')[0]
    admin_name_default = _("default_admin_name", lang)

    for uid in user_ids_to_check:
        uid_str = str(uid)
        current_name = USER_NAMES.get(uid_str)

        # --- ИСПРАВЛЕНИЕ: Используем 'admins' для проверки группы при обновлении имени ---
        user_group_key = ALLOWED_USERS.get(uid)
        # --------------------------------------------------------------------------

        should_refresh = (
            not current_name
            or current_name.startswith(new_user_prefix)
            or current_name.startswith(id_user_prefix)
            # Обновляем имя главного админа, если оно все еще по умолчанию
            or (current_name == admin_name_default and uid == ADMIN_USER_ID)
            # --- ИСПРАВЛЕНИЕ: Добавлено обновление имени для добавленных
            # админов с именем по умолчанию ---
            # (Если пользователь в группе 'admins', но имя у него все еще "ID:
            # xxx" или "Новый_xxx")
            or (user_group_key == "admins" and uid != ADMIN_USER_ID and (
                current_name.startswith(new_user_prefix) or current_name.startswith(id_user_prefix)))
            # -------------------------------------------------------------------------------------
        )

        if should_refresh:
            # Имя по умолчанию, если не удастся получить из API
            new_name = _("default_id_user_name", lang, uid=uid)
            try:
                logging.debug(
                    f"Пытаюсь получить информацию о чате для ID: {uid}")
                chat = await bot.get_chat(uid)
                # Отдаем приоритет first_name, потом username
                fetched_name = chat.first_name or chat.username
                if fetched_name:
                    new_name = escape_html(fetched_name)
                else:
                    logging.warning(
                        f"Не удалось получить Имя/Юзернейм для {uid}, использую запасное '{new_name}'")

                if current_name != new_name:
                    logging.info(
                        f"Имя обновлено для {uid}: '{current_name}' -> '{new_name}'")
                    USER_NAMES[uid_str] = new_name
                    needs_save = True
                else:
                    logging.debug(
                        f"Имя для {uid} не изменилось ('{current_name}').")

            except TelegramBadRequest as e:
                # Обрабатываем ошибки API
                if "chat not found" in str(e).lower(
                ) or "bot was blocked by the user" in str(e).lower():
                    logging.warning(
                        f"Не удалось обновить имя для {uid}: {e}. Использую запасное '{new_name}'.")
                    # Сохраняем имя по умолчанию, если текущее некорректно
                    if current_name != new_name:
                        USER_NAMES[uid_str] = new_name
                        needs_save = True
                else:
                    logging.error(
                        f"Неожиданная ошибка Telegram API при получении имени для {uid}: {e}")
                    # Сохраняем имя по умолчанию, если текущее некорректно
                    if not current_name or current_name.startswith(
                            new_user_prefix):
                        USER_NAMES[uid_str] = new_name
                        needs_save = True
            except Exception as e:
                logging.error(
                    f"Неожиданная ошибка при обновлении имени для {uid}: {e}",
                    exc_info=True)
                # Сохраняем имя по умолчанию, если текущее некорректно
                if not current_name or current_name.startswith(
                        new_user_prefix):
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

    lang = config.DEFAULT_LANGUAGE
    try:
        from .i18n import get_user_lang  # Импорт здесь для избежания цикла
        lang = get_user_lang(user_id)
    except Exception as e:
        logging.warning(
            f"Ошибка получения языка для {user_id} в get_user_name: {e}. Использую язык по умолчанию.")

    new_user_prefix = _("default_new_user_name", lang, uid="").split('_')[0]
    id_user_prefix = _("default_id_user_name", lang, uid="").split(' ')[0]

    # Если имя есть в кеше и оно не является плейсхолдером, возвращаем его
    if cached_name and not cached_name.startswith(
            new_user_prefix) and not cached_name.startswith(id_user_prefix):
        return cached_name

    logging.debug(
        f"Имя для {user_id} не кешировано или является плейсхолдером ('{cached_name}'). Запрашиваю...")
    new_name = _("default_id_user_name", lang, uid=user_id)  # Имя по умолчанию
    try:
        chat = await bot.get_chat(user_id)
        fetched_name = chat.first_name or chat.username  # Приоритет first_name
        if fetched_name:
            new_name = escape_html(fetched_name)
            USER_NAMES[uid_str] = new_name
            save_users()  # Сохраняем сразу
            logging.info(
                f"Получено и кешировано имя для {user_id}: '{new_name}'")
            return new_name
        else:
            logging.warning(
                f"Получен чат для {user_id}, но имя/юзернейм не найдены. Использую запасное.")
            # Сохраняем имя по умолчанию, если оно отличается от кешированного
            # (или не было кеша)
            if cached_name != new_name:
                USER_NAMES[uid_str] = new_name
                save_users()
            return new_name
    except Exception as e:
        logging.error(f"Ошибка получения имени для ID {user_id}: {e}")
        # Сохраняем имя по умолчанию, если оно отличается от кешированного (или
        # не было кеша)
        if cached_name != new_name:
            USER_NAMES[uid_str] = new_name
            save_users()
        return new_name


async def send_access_denied_message(
        bot: Bot,
        user_id: int,
        chat_id: int,
        command: str):
    """Отправляет сообщение об отказе в доступе."""
    # Удаляем предыдущее сообщение с *той же* командой, на которую отказано в
    # доступе
    await delete_previous_message(user_id, command, chat_id, bot)
    # Также удаляем предыдущее сообщение об ошибке доступа, если оно было
    await delete_previous_message(user_id, 'access_denied', chat_id, bot)

    lang = config.DEFAULT_LANGUAGE  # По умолчанию
    try:
        from .i18n import get_user_lang  # Импорт здесь для избежания цикла
        lang = get_user_lang(user_id)
    except Exception as e:
        logging.warning(
            f"Ошибка получения языка для {user_id} в send_access_denied_message: {e}. Использую язык по умолчанию.")

    text_to_send = f"my ID: {user_id}"
    admin_link = ""

    if ADMIN_USERNAME:
        admin_link = f"https://t.me/{ADMIN_USERNAME}?text={urllib.parse.quote(text_to_send)}"
    else:
        # Ссылка для открытия профиля по ID
        admin_link = f"tg://user?id={ADMIN_USER_ID}"
        logging.warning(
            "Переменная TG_ADMIN_USERNAME не установлена. Используется ссылка по ID (открывает профиль).")

    button_text = _("access_denied_button", lang)
    # --- ИСПРАВЛЕНИЕ: Получаем правильный текст ошибки ---
    # Проверяем, почему доступ запрещен
    user_group_key = ALLOWED_USERS.get(user_id)
    is_admin_group = (user_id == ADMIN_USER_ID) or (user_group_key == "admins")

    root_only_commands = [  # Повторное определение для проверки
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs", "restart", "update", "optimize"]
    admin_only_commands = [  # Повторное определение для проверки
        "manage_users", "generate_vless", "speedtest", "top", "updatexray",
        "adduser", "add_user", "delete_user", "set_group", "change_group",
        "back_to_manage_users", "back_to_delete_users"
    ]

    # Сообщение по умолчанию (нет в списке разрешенных)
    message_key = "access_denied_message"
    if user_id in ALLOWED_USERS:  # Если пользователь есть, но прав не хватило
        if command in root_only_commands and INSTALL_MODE != "root":
            message_key = "access_denied_not_root"  # Требуется режим Root
        elif command in root_only_commands and not is_admin_group:
            # Требуются права админа для Root-команды
            message_key = "access_denied_no_rights"
        # --- ИСПРАВЛЕНИЕ: Добавляем проверку для admin_only_commands ---
        elif command in admin_only_commands and not is_admin_group:
            # Требуются права админа для Админ-команды
            message_key = "access_denied_no_rights"
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
        # Для команд пользователя или неизвестных
        elif command not in root_only_commands and command not in admin_only_commands:
            message_key = "access_denied_no_rights"  # Общее сообщение об отсутствии прав
        else:  # Другие случаи (например, админ пытается выполнить команду пользователя - должно быть разрешено раньше)
            # Общее сообщение, если логика не сработала
            message_key = "access_denied_generic"

    # Используем соответствующий ключ i18n
    message_text = _(message_key, lang, user_id=user_id)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

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
        # Сохраняем ID сообщения об ошибке доступа под ключ 'access_denied'
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})['access_denied'] = sent_message.message_id
    except Exception as e:
        logging.error(
            f"Не удалось отправить сообщение об отказе в доступе пользователю {user_id}: {e}")
