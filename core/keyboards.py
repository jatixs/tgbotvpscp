# /opt/tg-bot/core/keyboards.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .shared_state import ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
from .config import ADMIN_USER_ID, INSTALL_MODE

# --- НАЧАЛО ВОССТАНОВЛЕННОГО КОДА ---

def get_main_reply_keyboard(user_id: int, buttons_map: dict) -> ReplyKeyboardMarkup:
    """
    Собирает главную клавиатуру из кнопок, предоставленных загруженными модулями,
    с логической группировкой по строкам (как было до подменю).
    """
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    is_root_mode = INSTALL_MODE == 'root'

    # 1. Получаем ВСЕ кнопки, доступные этому пользователю
    available_buttons_texts = set()
    available_buttons_map = {} # Словарь для быстрого доступа к объекту KeyboardButton по тексту

    # Пользовательские кнопки
    for btn in buttons_map.get("user", []): # Используем 'user'
        available_buttons_texts.add(btn.text)
        available_buttons_map[btn.text] = btn

    # Админские кнопки
    if is_admin:
        for btn in buttons_map.get("admin", []): # Используем 'admin'
            available_buttons_texts.add(btn.text)
            available_buttons_map[btn.text] = btn

    # Root кнопки (только если режим root И пользователь админ)
    if is_root_mode and is_admin:
        for btn in buttons_map.get("root", []): # Используем 'root'
            available_buttons_texts.add(btn.text)
            available_buttons_map[btn.text] = btn

    # 2. Определяем структуру строк (группы) - возвращаем старую группировку
    button_layout = [
        # Группа 1: Информация и Мониторинг (User+)
        ["🛠 Сведения о сервере", "📡 Трафик сети", "⏱ Аптайм"],
        # Группа 2: Инструменты и Тесты (Admin+)
        ["🚀 Скорость сети", "🔥 Топ процессов", "🩻 Обновление X-ray"],
        # Группа 3: Логи и Безопасность (Root Only)
        ["📜 SSH-лог", "🔒 Fail2Ban Log", "📜 Последние события"],
        # Группа 4: Управление (Admin+)
        ["👤 Пользователи", "🔗 VLESS-ссылка"],
        # Группа 5: Системные Действия (Admin/Root)
        ["🔄 Обновление VPS", "♻️ Перезапуск бота", "🔄 Перезагрузка сервера"],
        # Группа 6: Настройки Бота (User+)
        ["🔔 Уведомления"],
    ]

    # 3. Собираем финальную клавиатуру
    final_keyboard_rows = []
    for row_template in button_layout:
        current_row = []
        for btn_text in row_template:
            # Добавляем кнопку в ряд, только если она доступна пользователю
            if btn_text in available_buttons_texts:
                current_row.append(available_buttons_map[btn_text])

        # Добавляем ряд в клавиатуру, только если он не пустой
        if current_row:
            final_keyboard_rows.append(current_row)

    return ReplyKeyboardMarkup(
        keyboard=final_keyboard_rows,
        resize_keyboard=True,
        # Возвращаем старый плейсхолдер
        input_field_placeholder="Выберите опцию в меню..."
    )

# --- КОНЕЦ ВОССТАНОВЛЕННОГО КОДА ---


# --- Остальные функции get_*_keyboard остаются без изменений ---
def get_manage_users_keyboard():
    """Клавиатура для меню управления пользователями."""
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
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu") # Эта кнопка все еще нужна
        ]
    ])
    return keyboard

def get_delete_users_keyboard(current_user_id):
    """Клавиатура для выбора пользователя для удаления."""
    buttons = []
    sorted_users = sorted(
        ALLOWED_USERS.items(),
        key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower()
    )
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID: continue
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
    """Клавиатура для выбора пользователя для смены группы."""
    buttons = []
    sorted_users = sorted(
        ALLOWED_USERS.items(),
        key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower()
    )
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID: continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        buttons.append([InlineKeyboardButton(text=f"{user_name} ({group})", callback_data=f"select_user_change_group_{uid}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_selection_keyboard(user_id_to_change=None):
    """Клавиатура для выбора группы (Админ/Пользователь)."""
    user_identifier = user_id_to_change or 'new'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👑 Админы", callback_data=f"set_group_{user_identifier}_Админы"),
            InlineKeyboardButton(text="👤 Пользователи", callback_data=f"set_group_{user_identifier}_Пользователи")
        ],
        [ InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_manage_users") ]
    ])
    return keyboard

def get_self_delete_confirmation_keyboard(user_id):
    """Клавиатура подтверждения удаления себя."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_self_delete_{user_id}"),
            InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_delete_users")
        ]
    ])
    return keyboard

def get_reboot_confirmation_keyboard():
    """Клавиатура подтверждения перезагрузки сервера."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, перезагрузить", callback_data="reboot"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_menu") # Эта кнопка остается
        ]
    ])
    return keyboard

def get_back_keyboard(callback_data="back_to_manage_users"):
    """Универсальная инлайн-кнопка 'Назад'."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [ InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data) ]
    ])
    return keyboard

def get_alerts_menu_keyboard(user_id):
    """Клавиатура для меню настроек уведомлений."""
    user_config = ALERTS_CONFIG.get(user_id, {})
    res_enabled = user_config.get("resources", False)
    logins_enabled = user_config.get("logins", False)
    bans_enabled = user_config.get("bans", False)
    res_text = f"{'✅' if res_enabled else '❌'} Ресурсы (CPU/RAM/Disk)"; logins_text = f"{'✅' if logins_enabled else '❌'} Входы SSH"; bans_text = f"{'✅' if bans_enabled else '❌'} Баны (Fail2Ban)"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=res_text, callback_data="toggle_alert_resources")],
        [InlineKeyboardButton(text=logins_text, callback_data="toggle_alert_logins")],
        [InlineKeyboardButton(text=bans_text, callback_data="toggle_alert_bans")],
        [InlineKeyboardButton(text="⏳ Даунтайм сервера (WIP)", callback_data="alert_downtime_stub")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")] # И эта остается
    ])
    return keyboard