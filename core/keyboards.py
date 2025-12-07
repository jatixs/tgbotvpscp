import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .i18n import _, get_user_lang, STRINGS as I18N_STRINGS
from .shared_state import ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
from .config import ADMIN_USER_ID, INSTALL_MODE, DEFAULT_LANGUAGE, KEYBOARD_CONFIG

# Маппинг ключей кнопок на ключи конфигурации (какой флаг отвечает за кнопку)
BTN_CONFIG_MAP = {
    "btn_selftest": "enable_selftest",
    "btn_traffic": "enable_traffic",
    "btn_uptime": "enable_uptime",
    "btn_speedtest": "enable_speedtest",
    "btn_top": "enable_top",
    "btn_xray": "enable_xray",
    "btn_sshlog": "enable_sshlog",
    "btn_fail2ban": "enable_fail2ban",
    "btn_logs": "enable_logs",
    "btn_users": "enable_users",
    "btn_vless": "enable_vless",
    "btn_update": "enable_update",
    "btn_optimize": "enable_optimize",
    "btn_restart": "enable_restart",
    "btn_reboot": "enable_reboot",
    "btn_notifications": "enable_notifications",
    "btn_nodes": "enable_nodes"
}

# Структура меню: Категория -> Список кнопок в ней
CATEGORY_MAP = {
    "cat_monitoring": ["btn_selftest", "btn_traffic", "btn_uptime", "btn_speedtest", "btn_top"],
    "cat_management": ["btn_nodes", "btn_users", "btn_update", "btn_optimize", "btn_restart", "btn_reboot"],
    "cat_security": ["btn_sshlog", "btn_fail2ban", "btn_logs"],
    "cat_tools": ["btn_xray", "btn_vless", "btn_notifications"],
    "cat_settings": ["btn_language", "btn_configure_menu"] 
}

def get_main_reply_keyboard(user_id: int, buttons_map: dict = None) -> ReplyKeyboardMarkup:
    """Возвращает главное меню, состоящее из категорий."""
    lang = get_user_lang(user_id)
    
    # Раскладка категорий: 2 в ряд, настройки снизу
    keyboard_layout = [
        [KeyboardButton(text=_("cat_monitoring", lang)), KeyboardButton(text=_("cat_management", lang))],
        [KeyboardButton(text=_("cat_security", lang)), KeyboardButton(text=_("cat_tools", lang))],
        [KeyboardButton(text=_("cat_settings", lang))]
    ]
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard_layout,
        resize_keyboard=True,     # Подгонять размер под кол-во кнопок
        is_persistent=True,       # Меню не сворачивается при нажатии (Telegram 5.0+)
        one_time_keyboard=False   # Явно запрещаем одноразовое скрытие
        # input_field_placeholder убран, чтобы не триггерить фокус ввода на некоторых устройствах
    )

def get_subcategory_keyboard(category_key: str, user_id: int) -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру для конкретной категории с учетом прав и настроек."""
    lang = get_user_lang(user_id)
    
    is_admin = user_id == ADMIN_USER_ID or (ALLOWED_USERS.get(user_id, {}).get("group") == "admins" if isinstance(ALLOWED_USERS.get(user_id), dict) else ALLOWED_USERS.get(user_id) == "admins")
    is_root_mode = INSTALL_MODE == 'root'

    # Списки кнопок, требующих особых прав
    admin_only = ["btn_users", "btn_speedtest", "btn_top", "btn_xray", "btn_vless", "btn_nodes"]
    root_only = ["btn_sshlog", "btn_fail2ban", "btn_logs", "btn_update", "btn_restart", "btn_reboot", "btn_optimize"]

    buttons_in_category = CATEGORY_MAP.get(category_key, [])
    keyboard_rows = []
    current_row = []

    for btn_key in buttons_in_category:
        # 1. Проверяем, включена ли кнопка в настройках
        config_key = BTN_CONFIG_MAP.get(btn_key)
        if config_key and not KEYBOARD_CONFIG.get(config_key, True):
            continue

        # 2. Проверяем права доступа
        if btn_key in admin_only and not is_admin:
            continue
        if btn_key in root_only and not (is_root_mode and is_admin):
            continue

        # Добавляем кнопку
        current_row.append(KeyboardButton(text=_(btn_key, lang)))
        
        # Разбиваем по 2 кнопки в ряд
        if len(current_row) == 2:
            keyboard_rows.append(current_row)
            current_row = []

    # Добавляем оставшиеся кнопки
    if current_row:
        keyboard_rows.append(current_row)

    # Всегда добавляем кнопку "Назад в меню"
    keyboard_rows.append([KeyboardButton(text=_("btn_back_to_menu", lang))])

    return ReplyKeyboardMarkup(
        keyboard=keyboard_rows,
        resize_keyboard=True,
        is_persistent=True,       # Меню не сворачивается при нажатии
        one_time_keyboard=False   # Явно запрещаем одноразовое скрытие
    )

def get_keyboard_settings_inline(lang: str) -> InlineKeyboardMarkup:
    """Возвращает inline-клавиатуру для включения/выключения кнопок."""
    buttons = []
    
    # Проходим по всем кнопкам, которые можно настроить
    for btn_key, config_key in BTN_CONFIG_MAP.items():
        is_enabled = KEYBOARD_CONFIG.get(config_key, True)
        status_icon = "✅" if is_enabled else "❌"
        btn_label = _(btn_key, lang)
        text = f"{status_icon} {btn_label}"
        callback_data = f"toggle_kb_{config_key}"
        buttons.append(InlineKeyboardButton(text=text, callback_data=callback_data))

    # Разбиваем на ряды по 2 кнопки
    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i+2])
    
    # Кнопка "Готово"
    rows.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="close_kb_settings")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

# --- Стандартные клавиатуры ---

def get_manage_users_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_add_user", lang), callback_data="add_user"), InlineKeyboardButton(text=_("btn_delete_user", lang), callback_data="delete_user")], [InlineKeyboardButton(text=_("btn_change_group", lang), callback_data="change_group"), InlineKeyboardButton(text=_("btn_my_id", lang), callback_data="get_id_inline")], [InlineKeyboardButton(text=_("btn_back_to_menu", lang), callback_data="back_to_menu")]])

def get_delete_users_keyboard(current_user_id: int):
    lang = get_user_lang(current_user_id)
    buttons = []
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower())
    for uid, user_data in sorted_users:
        if uid == ADMIN_USER_ID: continue
        group_key = user_data.get("group", "users") if isinstance(user_data, dict) else user_data
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        group_display = _("group_admins", lang) if group_key == "admins" else _("group_users", lang)
        button_text = _("delete_user_button_text", lang, user_name=user_name, group=group_display)
        callback_data = f"delete_user_{uid}"
        if uid == current_user_id:
            button_text = _("delete_self_button_text", lang, user_name=user_name, group=group_display)
            callback_data = f"request_self_delete_{uid}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    buttons.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_change_group_keyboard(admin_user_id: int):
    lang = get_user_lang(admin_user_id)
    buttons = []
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower())
    for uid, user_data in sorted_users:
        if uid == ADMIN_USER_ID: continue
        group_key = user_data.get("group", "users") if isinstance(user_data, dict) else user_data
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        group_display = _("group_admins", lang) if group_key == "admins" else _("group_users", lang)
        button_text = _("delete_user_button_text", lang, user_name=user_name, group=group_display)
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"select_user_change_group_{uid}")])
    buttons.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_selection_keyboard(lang: str, user_id_to_change=None):
    user_identifier = user_id_to_change or 'new'
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_group_admins", lang), callback_data=f"set_group_{user_identifier}_admins"), InlineKeyboardButton(text=_("btn_group_users", lang), callback_data=f"set_group_{user_identifier}_users")], [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_manage_users")]])

def get_self_delete_confirmation_keyboard(user_id: int):
    lang = get_user_lang(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_confirm", lang), callback_data=f"confirm_self_delete_{user_id}"), InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_delete_users")]])

def get_reboot_confirmation_keyboard(user_id: int):
    lang = get_user_lang(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_reboot_confirm", lang), callback_data="reboot"), InlineKeyboardButton(text=_("btn_reboot_cancel", lang), callback_data="back_to_menu")]])

def get_back_keyboard(lang: str, callback_data="back_to_manage_users"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_back", lang), callback_data=callback_data)]])

def get_alerts_menu_keyboard(user_id: int):
    lang = get_user_lang(user_id)
    user_config = ALERTS_CONFIG.get(user_id, {})
    res_enabled = user_config.get("resources", False)
    logins_enabled = user_config.get("logins", False)
    bans_enabled = user_config.get("bans", False)
    downtime_enabled = user_config.get("downtime", False)
    status_yes = _("status_enabled", lang)
    status_no = _("status_disabled", lang)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("alerts_menu_res", lang, status=(status_yes if res_enabled else status_no)), callback_data="toggle_alert_resources")], [InlineKeyboardButton(text=_("alerts_menu_logins", lang, status=(status_yes if logins_enabled else status_no)), callback_data="toggle_alert_logins")], [InlineKeyboardButton(text=_("alerts_menu_bans", lang, status=(status_yes if bans_enabled else status_no)), callback_data="toggle_alert_bans")], [InlineKeyboardButton(text=_("alerts_menu_downtime", lang, status=(status_yes if downtime_enabled else status_no)), callback_data="toggle_alert_downtime")], [InlineKeyboardButton(text=_("btn_back_to_menu", lang), callback_data="back_to_menu")]])

def get_nodes_list_keyboard(nodes_dict: dict, lang: str) -> InlineKeyboardMarkup:
    buttons = []
    for token, node_data in nodes_dict.items():
        name = node_data.get('name', 'Unknown')
        icon = node_data.get('status_icon', '❓')
        buttons.append([InlineKeyboardButton(text=f"{name} {icon}", callback_data=f"node_select_{token}")])
    buttons.append([InlineKeyboardButton(text=_("node_btn_add", lang), callback_data="node_add_new"), InlineKeyboardButton(text=_("node_btn_delete", lang), callback_data="node_delete_menu")])
    buttons.append([InlineKeyboardButton(text=_("btn_back_to_menu", lang), callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_nodes_delete_keyboard(nodes_dict: dict, lang: str) -> InlineKeyboardMarkup:
    buttons = []
    for token, node_data in nodes_dict.items():
        name = node_data.get('name', 'Unknown')
        buttons.append([InlineKeyboardButton(text=f"🗑 {name}", callback_data=f"node_delete_confirm_{token}")])
    buttons.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="nodes_list_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_node_management_keyboard(token: str, lang: str) -> InlineKeyboardMarkup:
    layout = [[InlineKeyboardButton(text=_("btn_selftest", lang), callback_data=f"node_cmd_{token}_selftest"), InlineKeyboardButton(text=_("btn_uptime", lang), callback_data=f"node_cmd_{token}_uptime")], [InlineKeyboardButton(text=_("btn_traffic", lang), callback_data=f"node_cmd_{token}_traffic"), InlineKeyboardButton(text=_("btn_top", lang), callback_data=f"node_cmd_{token}_top")], [InlineKeyboardButton(text=_("btn_speedtest", lang), callback_data=f"node_cmd_{token}_speedtest"), InlineKeyboardButton(text=_("btn_reboot", lang), callback_data=f"node_cmd_{token}_reboot")], [InlineKeyboardButton(text=_("btn_back", lang), callback_data="nodes_list_refresh")]]
    return InlineKeyboardMarkup(inline_keyboard=layout)