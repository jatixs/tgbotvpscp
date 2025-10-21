# /opt/tg-bot/core/auth.py
import os
import json
import logging # Убедитесь, что logging импортирован
import urllib.parse
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from .config import USERS_FILE, ADMIN_USER_ID, ADMIN_USERNAME, INSTALL_MODE
# ИСПРАВЛЕНИЕ: Импортируем сами словари из shared_state
from .shared_state import ALLOWED_USERS, USER_NAMES, LAST_MESSAGE_IDS
from .messaging import delete_previous_message
from .utils import escape_html

def load_users():
    """Загружает ALLOWED_USERS и USER_NAMES из users.json в shared_state"""
    # ИСПРАВЛЕНИЕ: Мы больше не используем 'global', так как импортировали словари напрямую
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        
        # ИСПРАВЛЕНИЕ: Очищаем словари перед загрузкой
        ALLOWED_USERS.clear()
        USER_NAMES.clear()

        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                # ИСПРАВЛЕНИЕ: ОБНОВЛЯЕМ (мутируем) импортированные словари
                ALLOWED_USERS.update({int(user["id"]): user["group"] for user in data.get("allowed_users", [])})
                USER_NAMES.update(data.get("user_names", {}))
        else:
            # Если файл не существует, инициализируем пустые словари
            logging.warning(f"Файл {USERS_FILE} не найден. Инициализация пустых списков пользователей.")
            # (Они уже очищены выше)

        # Всегда убеждаемся, что главный админ присутствует
        if ADMIN_USER_ID not in ALLOWED_USERS:
            logging.info(f"Главный админ ID {ADMIN_USER_ID} не найден в users.json, добавляю.")
            ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
            USER_NAMES[str(ADMIN_USER_ID)] = "Главный Админ"
            save_users() # Сохраняем сразу после добавления админа

        logging.info(f"Пользователи загружены. Разрешенные ID: {list(ALLOWED_USERS.keys())}")

    except json.JSONDecodeError as e:
        logging.error(f"Критическая ошибка загрузки users.json: Неверный JSON - {e}")
        # ИСПРАВЛЕНИЕ: Убеждаемся, что мутируем словари и здесь
        ALLOWED_USERS.clear()
        USER_NAMES.clear()
        ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
        USER_NAMES[str(ADMIN_USER_ID)] = "Главный Админ"
        save_users() # Пытаемся сохранить валидную минимальную конфигурацию
    except Exception as e:
        logging.error(f"Критическая ошибка загрузки users.json: {e}", exc_info=True)
        # ИСПРАВЛЕНИЕ: Откатываемся к только админу, мутируя словари
        ALLOWED_USERS.clear()
        USER_NAMES.clear()
        ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
        USER_NAMES[str(ADMIN_USER_ID)] = "Главный Админ"
        save_users()

def save_users():
    """Сохраняет ALLOWED_USERS и USER_NAMES из shared_state в users.json"""
    try:
        # Убеждаемся, что ключи имен пользователей - строки перед сохранением
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        # Убеждаемся, что ID разрешенных пользователей - целые числа (хотя они и так должны быть)
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
    # --- Отладочное логирование ---
    logging.info(f"Проверка is_allowed для user_id: {user_id}, command: '{command}'")
    # Логируем только ключи для краткости и потенциальной приватности
    logging.debug(f"Текущие ключи ALLOWED_USERS: {list(ALLOWED_USERS.keys())}")
    # --- Конец отладочного логирования ---

    if user_id not in ALLOWED_USERS:
        # Добавлено дополнительное логирование для ясности
        logging.warning(f"Пользователь {user_id} НЕ найден в ALLOWED_USERS для команды '{command}'. Доступ запрещен.")
        return False

    # Определяем группы команд
    user_commands = [
        "start", "menu", "back_to_menu", "uptime", "traffic", "selftest",
        "get_id", "get_id_inline", "notifications_menu", "toggle_alert_resources",
        "toggle_alert_logins", "toggle_alert_bans", "alert_downtime_stub"
    ]
    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray",
        "adduser", "add_user", "delete_user", "set_group", "change_group",
        "back_to_manage_users", "back_to_delete_users" # Включаем колбэки, связанные с управлением пользователями
    ]
    root_only_commands = [
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs", "restart", "update",
        "optimize"  # <-- ДОБАВЛЕНО
    ]

    # Проверяем, требует ли команда какой-либо роли
    if command in user_commands:
        logging.debug(f"Команда '{command}' разрешена для всех пользователей. Доступ для {user_id} предоставлен.")
        return True # Разрешено для любого зарегистрированного пользователя

    # Проверяем статус админской группы
    is_admin_group = (user_id == ADMIN_USER_ID) or (ALLOWED_USERS.get(user_id) == "Админы")

    if command in admin_only_commands:
        if is_admin_group:
            logging.debug(f"Команда '{command}' разрешена для админов. Доступ для админа {user_id} предоставлен.")
            return True
        else:
            logging.warning(f"Команда '{command}' требует прав админа. Доступ для пользователя {user_id} запрещен.")
            return False

    if command in root_only_commands:
        # Root-команды требуют и root-режима И админской группы
        if INSTALL_MODE == "root" and is_admin_group:
             logging.debug(f"Команда '{command}' разрешена для админов в root-режиме. Доступ для админа {user_id} предоставлен.")
             return True
        elif INSTALL_MODE != "root":
            logging.warning(f"Команда '{command}' требует root-режима установки. Доступ для {user_id} запрещен (текущий режим: {INSTALL_MODE}).")
            return False
        else: # Режим root, но пользователь не админ
            logging.warning(f"Команда '{command}' требует прав админа даже в root-режиме. Доступ для пользователя {user_id} запрещен.")
            return False

    # Обработка команд, не перечисленных явно (в идеале такого быть не должно)
    # Для безопасности предположим, что неперечисленные команды требуют прав админа
    if is_admin_group:
         logging.warning(f"Команда '{command}' не перечислена явно, но разрешаю админу {user_id} по умолчанию.")
         return True
    else:
         logging.warning(f"Команда '{command}' не перечислена явно. Доступ для не-админа {user_id} запрещен.")
         return False

async def refresh_user_names(bot: Bot):
    """Обновляет имена пользователей, особенно новых или с плейсхолдерами."""
    # ИСПРАВЛЕНИЕ: Убираем 'global', так как USER_NAMES импортирован
    needs_save = False
    # Итерируем по копии ключей на случай, если словарь изменится во время итерации (здесь маловероятно, но хорошая практика)
    user_ids_to_check = list(ALLOWED_USERS.keys())
    logging.info(f"Начинаю обновление имен для {len(user_ids_to_check)} пользователей...")

    for uid in user_ids_to_check:
        uid_str = str(uid)
        current_name = USER_NAMES.get(uid_str)

        # Условия для попытки обновления:
        # 1. ID пользователя отсутствует в словаре имен.
        # 2. Имя - временный плейсхолдер "Новый_...".
        # 3. Имя - запасной плейсхолдер "ID: ...".
        # 4. Имя - "Главный Админ" (на случай, если админ сменил имя/юзернейм в TG).
        should_refresh = (
            not current_name
            or current_name.startswith("Новый_")
            or current_name.startswith("ID: ")
            # Обновляем 'Главный Админ' только если это ID реального админа
            or (current_name == "Главный Админ" and uid == ADMIN_USER_ID)
        )

        if should_refresh:
            new_name = f"ID: {uid}" # Запасное имя по умолчанию
            try:
                logging.debug(f"Пытаюсь получить информацию о чате для ID: {uid}")
                chat = await bot.get_chat(uid)
                # Приоритет: Имя, затем Юзернейм
                fetched_name = chat.first_name or chat.username
                if fetched_name:
                    new_name = escape_html(fetched_name) # Используем полученное имя, если оно есть
                else:
                    logging.warning(f"Не удалось получить Имя/Юзернейм для {uid}, использую запасное '{new_name}'")

                # Обновляем только если имя действительно изменилось или отсутствовало
                if current_name != new_name:
                    logging.info(f"Имя обновлено для {uid}: '{current_name}' -> '{new_name}'")
                    USER_NAMES[uid_str] = new_name
                    needs_save = True
                else:
                    logging.debug(f"Имя для {uid} не изменилось ('{current_name}').")

            except TelegramBadRequest as e:
                # Частые ошибки: чат не найден (пользователь удалился?), бот заблокирован
                if "chat not found" in str(e).lower() or "bot was blocked by the user" in str(e).lower():
                     logging.warning(f"Не удалось обновить имя для {uid}: {e}. Использую запасное '{new_name}'.")
                     # Устанавливаем запасное имя, если оно еще не установлено или отличается
                     if current_name != new_name:
                          USER_NAMES[uid_str] = new_name
                          needs_save = True
                else:
                     # Другие ошибки Telegram API
                     logging.error(f"Неожиданная ошибка Telegram API при получении имени для {uid}: {e}")
                     # Убеждаемся, что запасное имя установлено, если текущее невалидно/отсутствует
                     if not current_name or current_name.startswith("Новый_"):
                          USER_NAMES[uid_str] = new_name
                          needs_save = True
            except Exception as e:
                # Любые другие неожиданные ошибки
                logging.error(f"Неожиданная ошибка при обновлении имени для {uid}: {e}", exc_info=True)
                if not current_name or current_name.startswith("Новый_"):
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
    # Возвращаем кешированное имя, если оно валидно (не плейсхолдер)
    if cached_name and not cached_name.startswith("Новый_") and not cached_name.startswith("ID: "):
        return cached_name

    # Если не кешировано или плейсхолдер, пытаемся получить
    logging.debug(f"Имя для {user_id} не кешировано или является плейсхолдером ('{cached_name}'). Запрашиваю...")
    new_name = f"ID: {user_id}" # Запасной вариант
    try:
        chat = await bot.get_chat(user_id)
        fetched_name = chat.first_name or chat.username
        if fetched_name:
            new_name = escape_html(fetched_name)
            USER_NAMES[uid_str] = new_name # Обновляем кеш
            save_users() # Сохраняем обновление
            logging.info(f"Получено и кешировано имя для {user_id}: '{new_name}'")
            return new_name
        else:
            logging.warning(f"Получен чат для {user_id}, но имя/юзернейм не найдены. Использую запасное.")
            # Обновляем кеш запасным вариантом, если он еще не установлен
            if cached_name != new_name:
                USER_NAMES[uid_str] = new_name
                save_users()
            return new_name
    except Exception as e:
        logging.error(f"Ошибка получения имени для ID {user_id}: {e}")
        # Возвращаем запасной вариант и кешируем его, если еще не кеширован
        if cached_name != new_name:
             USER_NAMES[uid_str] = new_name
             save_users()
        return new_name

async def send_access_denied_message(bot: Bot, user_id: int, chat_id: int, command: str):
    """Отправляет сообщение об отказе в доступе."""
    # Пытаемся удалить предыдущее сообщение, связанное с этой командой
    await delete_previous_message(user_id, command, chat_id, bot)

    text_to_send = f"мой ID: {user_id}"
    admin_link = ""

    if ADMIN_USERNAME:
        # Ссылка на прямой чат с админом
        admin_link = f"https://t.me/{ADMIN_USERNAME}?text={urllib.parse.quote(text_to_send)}"
    else:
        # Ссылка на профиль админа (менее удобная)
        admin_link = f"tg://user?id={ADMIN_USER_ID}" # Текст не передается в этой ссылке
        logging.warning("Переменная TG_ADMIN_USERNAME не установлена. Используется ссылка по ID (открывает профиль).")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить свой ID администратору", url=admin_link)]
    ])
    try:
        sent_message = await bot.send_message(
            chat_id,
            f"⛔ Вы не являетесь пользователем бота. Ваш ID: <code>{user_id}</code>.\n"
            "К командам нет доступа, обратитесь к администратору.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        # Сохраняем ID отправленного сообщения об отказе
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение об отказе в доступе пользователю {user_id}: {e}")