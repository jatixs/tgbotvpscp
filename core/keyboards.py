# /opt/tg-bot/core/keyboards.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .shared_state import ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
from .config import ADMIN_USER_ID, INSTALL_MODE

def get_main_reply_keyboard(user_id: int, buttons_map: dict) -> ReplyKeyboardMarkup:
    """
    Собирает главную клавиатуру из кнопок, предоставленных загруженными модулями,
    сохраняя оригинальный макет.
    """
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    
    button_rows_config = [] # Здесь будут строки с ТЕКСТОМ кнопок

    if is_admin:
        if INSTALL_MODE == 'root':
            button_rows_config = [
                 ["👤 Пользователи", "🔗 VLESS-ссылка"],
                 ["🔥 Топ процессов", "📜 SSH-лог"],
                 ["🔒 Fail2Ban Log", "📜 Последние события"],
                 ["🚀 Скорость сети"],
                 ["🔄 Обновление VPS", "🩻 Обновление X-ray"],
                 ["🔄 Перезагрузка сервера", "♻️ Перезапуск бота"]
            ]
        elif INSTALL_MODE == 'secure':
            button_rows_config = [
                 ["👤 Пользователи", "🔗 VLESS-ссылка"],
                 ["🚀 Скорость сети", "🔥 Топ процессов"],
                 ["🩻 Обновление X-ray"],
            ]
    
    # Добавляем пользовательские кнопки
    button_rows_config.extend([
        ["🛠 Сведения о сервере", "📡 Трафик сети"],
        ["⏱ Аптайм", "🔔 Уведомления"],
    ])

    # Собираем карту всех доступных кнопок из модулей
    all_available_buttons = {}
    for level in buttons_map:
        for btn in buttons_map[level]:
            all_available_buttons[btn.text] = btn

    # Собираем финальную клавиатуру, используя только доступные кнопки
    final_keyboard = []
    for row_config in button_rows_config:
        new_row = []
        for btn_text in row_config:
            if btn_text in all_available_buttons:
                new_row.append(all_available_buttons[btn_text])
        if new_row: # Добавляем ряд, только если в нем есть хотя бы одна кнопка
            final_keyboard.append(new_row)

    return ReplyKeyboardMarkup(
        keyboard=final_keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите опцию в меню..."
    )

def get_manage_users_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="add_user"),
            InlineKeyboardButton(text="➖ Удалить пользователя", callback_data="delete_user")
        ],
        [
            InlineKeyboardButton(text="🔄 Изменить группу", callback_data="change_group"),
            InlineKeyboardButton(text="🆔 Мой ID", callback_data="get_id_inline")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_delete_users_keyboard(current_user_id):
    buttons = []
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}"), reverse=False)

    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID:
            continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        button_text = f"{user_name} ({group})"
        callback_data = f"delete_user_{uid}"
        if uid == current_user_id:
            button_text = f"❌ Удалить себя ({user_name}, {group})"
            callback_data = f"request_self_delete_{uid}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_change_group_keyboard():
    buttons = []
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}"), reverse=False)
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID:
            continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        buttons.append([InlineKeyboardButton(text=f"{user_name} ({group})", callback_data=f"select_user_change_group_{uid}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_selection_keyboard(user_id_to_change=None):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👑 Админы", callback_data=f"set_group_{user_id_to_change or 'new'}_Админы"),
            InlineKeyboardButton(text="👤 Пользователи", callback_data=f"set_group_{user_id_to_change or 'new'}_Пользователи")
        ],
        [
            InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_manage_users")
        ]
    ])
    return keyboard

def get_self_delete_confirmation_keyboard(user_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_self_delete_{user_id}"),
            InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_delete_users")
        ]
    ])
    return keyboard

def get_reboot_confirmation_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, перезагрузить", callback_data="reboot"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_back_keyboard(callback_data="back_to_manage_users"):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)
        ]
    ])
    return keyboard

def get_alerts_menu_keyboard(user_id):
    user_config = ALERTS_CONFIG.get(user_id, {})
    res_enabled = user_config.get("resources", False)
    logins_enabled = user_config.get("logins", False)
    bans_enabled = user_config.get("bans", False)

    res_text = f"{'✅' if res_enabled else '❌'} Ресурсы (CPU/RAM/Disk)"
    logins_text = f"{'✅' if logins_enabled else '❌'} Входы/Выходы SSH"
    bans_text = f"{'✅' if bans_enabled else '❌'} Баны (Fail2Ban)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=res_text, callback_data="toggle_alert_resources")],
        [InlineKeyboardButton(text=logins_text, callback_data="toggle_alert_logins")],
        [InlineKeyboardButton(text=bans_text, callback_data="toggle_alert_bans")],
        [InlineKeyboardButton(text="⏳ Даунтайм сервера", callback_data="alert_downtime_stub")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])
    return keyboard