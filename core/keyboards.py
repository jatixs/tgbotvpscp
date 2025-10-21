# /opt/tg-bot/core/keyboards.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- ИЗМЕНЕНО: Импортируем i18n ---
from .i18n import _, get_user_lang, STRINGS as I18N_STRINGS # Импортируем STRINGS для поиска
# -----------------------------------

from .shared_state import ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
# --- ИЗМЕНЕНО: Добавляем импорт DEFAULT_LANGUAGE ---
from .config import ADMIN_USER_ID, INSTALL_MODE, DEFAULT_LANGUAGE
# ----------------------------------------------------

# --- НАЧАЛО ВОССТАНОВЛЕННОГО КОДА (с i18n) ---

def get_main_reply_keyboard(user_id: int, buttons_map: dict) -> ReplyKeyboardMarkup:
    """
    Собирает главную клавиатуру из кнопок, предоставленных загруженными модулями,
    с логической группировкой по строкам (как было до подменю).
    """
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    is_root_mode = INSTALL_MODE == 'root'

    lang = get_user_lang(user_id)

    available_buttons_texts = set()
    available_buttons_map = {}

    def translate_button(btn: KeyboardButton) -> KeyboardButton:
        """Находит ключ i18n по тексту кнопки по умолчанию и возвращает новую кнопку с переводом."""

        key_to_find = None
        # --- ИЗМЕНЕНО: Используем I18N_STRINGS и DEFAULT_LANGUAGE ---
        default_strings = I18N_STRINGS.get(DEFAULT_LANGUAGE, {})
        # -----------------------------------------------------------
        for key, text in default_strings.items():
            if text == btn.text:
                key_to_find = key
                break

        if key_to_find:
            translated_text = _(key_to_find, lang)
            return KeyboardButton(text=translated_text)
        else:
            return btn

    # Пользовательские кнопки
    for btn in buttons_map.get("user", []):
        translated_btn = translate_button(btn)
        available_buttons_texts.add(translated_btn.text)
        available_buttons_map[translated_btn.text] = translated_btn

    # Админские кнопки
    if is_admin:
        for btn in buttons_map.get("admin", []):
            translated_btn = translate_button(btn)
            available_buttons_texts.add(translated_btn.text)
            available_buttons_map[translated_btn.text] = translated_btn

    # Root кнопки
    if is_root_mode and is_admin:
        for btn in buttons_map.get("root", []):
            translated_btn = translate_button(btn)
            available_buttons_texts.add(translated_btn.text)
            available_buttons_map[translated_btn.text] = translated_btn

    button_layout_keys = [
        ["btn_selftest", "btn_traffic", "btn_uptime"],
        ["btn_speedtest", "btn_top", "btn_xray"],
        ["btn_sshlog", "btn_fail2ban", "btn_logs"],
        ["btn_users", "btn_vless"],
        ["btn_update", "btn_optimize", "btn_restart", "btn_reboot"],
        ["btn_notifications", "btn_language"],
    ]

    final_keyboard_rows = []
    for row_template_keys in button_layout_keys:
        current_row = []
        for btn_key in row_template_keys:
            btn_text = _(btn_key, lang)
            if btn_text in available_buttons_texts:
                current_row.append(available_buttons_map[btn_text])

        if current_row:
            final_keyboard_rows.append(current_row)

    return ReplyKeyboardMarkup(
        keyboard=final_keyboard_rows,
        resize_keyboard=True,
        input_field_placeholder=_( "main_menu_placeholder", lang)
    )

# --- КОНЕЦ ВОССТАНОВЛЕННОГО КОДА ---


# --- Остальные функции get_*_keyboard ИЗМЕНЕНЫ для поддержки i18n ---

def get_manage_users_keyboard(lang: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_("btn_add_user", lang), callback_data="add_user"),
            InlineKeyboardButton(text=_("btn_delete_user", lang), callback_data="delete_user")
        ],
        [
            InlineKeyboardButton(text=_("btn_change_group", lang), callback_data="change_group"),
            InlineKeyboardButton(text=_("btn_my_id", lang), callback_data="get_id_inline")
        ],
        [
            InlineKeyboardButton(text=_("btn_back_to_menu", lang), callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_delete_users_keyboard(current_user_id: int):
    lang = get_user_lang(current_user_id)
    buttons = []
    sorted_users = sorted(
        ALLOWED_USERS.items(),
        key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower()
    )
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID: continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        group_display = _("group_admins", lang) if group == "Админы" else _("group_users", lang) # Переводим группу

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
    sorted_users = sorted(
        ALLOWED_USERS.items(),
        key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower()
    )
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID: continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        group_display = _("group_admins", lang) if group == "Админы" else _("group_users", lang) # Переводим группу
        button_text = _("delete_user_button_text", lang, user_name=user_name, group=group_display)
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"select_user_change_group_{uid}")])

    buttons.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_selection_keyboard(lang: str, user_id_to_change=None):
    user_identifier = user_id_to_change or 'new'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_("btn_group_admins", lang), callback_data=f"set_group_{user_identifier}_Админы"),
            InlineKeyboardButton(text=_("btn_group_users", lang), callback_data=f"set_group_{user_identifier}_Пользователи")
        ],
        [ InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_manage_users") ]
    ])
    return keyboard

def get_self_delete_confirmation_keyboard(user_id: int):
    lang = get_user_lang(user_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_("btn_confirm", lang), callback_data=f"confirm_self_delete_{user_id}"),
            InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_delete_users")
        ]
    ])
    return keyboard

def get_reboot_confirmation_keyboard(user_id: int):
    lang = get_user_lang(user_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_("btn_reboot_confirm", lang), callback_data="reboot"),
            InlineKeyboardButton(text=_("btn_reboot_cancel", lang), callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_back_keyboard(lang: str, callback_data="back_to_manage_users"):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [ InlineKeyboardButton(text=_("btn_back", lang), callback_data=callback_data) ]
    ])
    return keyboard

def get_alerts_menu_keyboard(user_id: int):
    lang = get_user_lang(user_id)

    user_config = ALERTS_CONFIG.get(user_id, {})
    res_enabled = user_config.get("resources", False)
    logins_enabled = user_config.get("logins", False)
    bans_enabled = user_config.get("bans", False)

    status_yes = _("status_enabled", lang)
    status_no = _("status_disabled", lang)

    res_text = _("alerts_menu_res", lang, status=(status_yes if res_enabled else status_no))
    logins_text = _("alerts_menu_logins", lang, status=(status_yes if logins_enabled else status_no))
    bans_text = _("alerts_menu_bans", lang, status=(status_yes if bans_enabled else status_no))
    downtime_text = _("alerts_menu_downtime", lang)
    back_text = _("btn_back_to_menu", lang)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=res_text, callback_data="toggle_alert_resources")],
        [InlineKeyboardButton(text=logins_text, callback_data="toggle_alert_logins")],
        [InlineKeyboardButton(text=bans_text, callback_data="toggle_alert_bans")],
        [InlineKeyboardButton(text=downtime_text, callback_data="alert_downtime_stub")],
        [InlineKeyboardButton(text=back_text, callback_data="back_to_menu")]
    ])
    return keyboard