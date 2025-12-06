import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from .i18n import _, get_user_lang, STRINGS as I18N_STRINGS
from .shared_state import ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
from .config import ADMIN_USER_ID, INSTALL_MODE, DEFAULT_LANGUAGE, KEYBOARD_CONFIG

# Маппинг ключей кнопок на ключи конфигурации
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
    "btn_notifications": "enable_notifications"
}

def get_main_reply_keyboard(user_id: int, buttons_map: dict) -> ReplyKeyboardMarkup:
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id, {}).get("group") == "admins" if isinstance(ALLOWED_USERS.get(user_id), dict) else ALLOWED_USERS.get(user_id) == "admins"
    is_root_mode = INSTALL_MODE == 'root'
    lang = get_user_lang(user_id)
    available_buttons_texts = set()
    available_buttons_map = {}

    def translate_button(btn: KeyboardButton) -> KeyboardButton:
        key_to_find = None
        default_strings = I18N_STRINGS.get(DEFAULT_LANGUAGE, {})
        for key, text in default_strings.items():
            if text == btn.text:
                key_to_find = key
                break
        if key_to_find:
            return KeyboardButton(text=_(key_to_find, lang))
        return btn

    for btn in buttons_map.get("user", []):
        translated_btn = translate_button(btn)
        available_buttons_texts.add(translated_btn.text)
        available_buttons_map[translated_btn.text] = translated_btn

    if is_admin:
        for btn in buttons_map.get("admin", []):
            translated_btn = translate_button(btn)
            available_buttons_texts.add(translated_btn.text)
            available_buttons_map[translated_btn.text] = translated_btn

    if is_root_mode and is_admin:
        for btn in buttons_map.get("root", []):
            translated_btn = translate_button(btn)
            available_buttons_texts.add(translated_btn.text)
            available_buttons_map[translated_btn.text] = translated_btn

    button_layout_keys = [
        ["btn_selftest", "btn_traffic", "btn_uptime"],
        ["btn_speedtest", "btn_top", "btn_xray"],
        ["btn_sshlog", "btn_fail2ban", "btn_logs"],
        ["btn_nodes", "btn_users", "btn_vless"],
        ["btn_update", "btn_optimize", "btn_restart", "btn_reboot"],
        ["btn_notifications", "btn_language"],
    ]

    final_keyboard_rows = []
    for row_template_keys in button_layout_keys:
        current_row = []
        for btn_key in row_template_keys:
            # --- ЛОГИКА ФИЛЬТРАЦИИ ---
            config_key = BTN_CONFIG_MAP.get(btn_key)
            # Если для кнопки есть настройка и она False - пропускаем
            if config_key and not KEYBOARD_CONFIG.get(config_key, True):
                continue
            # -------------------------

            btn_text = _(btn_key, lang)
            if btn_text in available_buttons_texts:
                button_obj = available_buttons_map.get(btn_text)
                if button_obj:
                    current_row.append(button_obj)
        if current_row:
            final_keyboard_rows.append(current_row)

    return ReplyKeyboardMarkup(
        keyboard=final_keyboard_rows,
        resize_keyboard=True,
        input_field_placeholder=_("main_menu_placeholder", lang))

# ... (Остальные функции клавиатур оставляем как есть) ...
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