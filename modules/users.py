# /opt-tg-bot/modules/users.py
import asyncio
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

# --- ИЗМЕНЕНО: Импортируем i18n ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# -----------------------------------

# ИСПРАВЛЕНИЕ: Добавляем 'get_user_name' в импорт
from core.auth import is_allowed, send_access_denied_message, refresh_user_names, save_users, get_user_name
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS, ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
from core.config import ADMIN_USER_ID
from core.keyboards import (
    get_manage_users_keyboard, get_delete_users_keyboard, get_change_group_keyboard,
    get_group_selection_keyboard, get_self_delete_confirmation_keyboard, get_back_keyboard
)

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_users"
# --------------------------------

class ManageUsersStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(manage_users_handler)
    dp.message(I18nFilter("btn_my_id"))(text_get_id_handler)
    # --------------------------------------

    # FSM handlers
    dp.message(StateFilter(ManageUsersStates.waiting_for_user_id))(process_add_user_id)
    # --- ИСПРАВЛЕНИЕ: Обновляем фильтр callback для новых ключей ---
    dp.callback_query(StateFilter(ManageUsersStates.waiting_for_group), F.data.startswith("set_group_new_"))(process_add_user_group)
    # -----------------------------------------------------------

    # Callback handlers
    dp.callback_query(F.data == "back_to_manage_users")(cq_back_to_manage_users)
    dp.callback_query(F.data == "get_id_inline")(cq_get_id_inline)

    # Add
    dp.callback_query(F.data == "add_user")(cq_add_user_start)

    # Delete
    dp.callback_query(F.data == "delete_user")(cq_delete_user_list)
    dp.callback_query(F.data.startswith("delete_user_"))(cq_delete_user_confirm)
    dp.callback_query(F.data.startswith("request_self_delete_"))(cq_request_self_delete)
    dp.callback_query(F.data.startswith("confirm_self_delete_"))(cq_confirm_self_delete)
    dp.callback_query(F.data == "back_to_delete_users")(cq_back_to_delete_users)

    # Change Group
    dp.callback_query(F.data == "change_group")(cq_change_group_list)
    dp.callback_query(F.data.startswith("select_user_change_group_"))(cq_select_user_for_group_change)

    # Set Group (для существующих пользователей)
    # --- ИСПРАВЛЕНИЕ: Обновляем фильтр callback для новых ключей ---
    dp.callback_query(StateFilter(None), F.data.startswith("set_group_"))(cq_set_group_existing)
    # -----------------------------------------------------------


# --- Хэндлеры ---

async def manage_users_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "manage_users"
    if not is_allowed(user_id, command):
        await message.bot.send_message(message.chat.id, _("access_denied_no_rights", lang))
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)

    # --- ИСПРАВЛЕНИЕ: Используем ключ group_key для перевода ---
    user_list_items = []
    sorted_users = sorted(
        ALLOWED_USERS.items(),
        key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower()
    )
    for uid, group_key in sorted_users: # Используем group_key
        if uid == ADMIN_USER_ID:
            continue
        # Переводим группу по ключу
        group_display = _("group_admins", lang) if group_key == "admins" else _("group_users", lang)
        user_name = USER_NAMES.get(str(uid), f'ID: {uid}')
        user_list_items.append(f" • {user_name} (<b>{group_display}</b>)")
    user_list = "\n".join(user_list_items)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    if not user_list:
        user_list = _("users_list_empty", lang)

    sent_message = await message.answer(
        _("users_menu_header", lang, user_list=user_list),
        reply_markup=get_manage_users_keyboard(lang),
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def text_get_id_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "get_id"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    sent_message = await message.answer(
        _("my_id_text", lang, user_id=user_id),
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_get_id_inline(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    command = "get_id_inline"
    if not is_allowed(user_id, command):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        await callback.message.edit_text(
            _("my_id_inline_text", lang, user_id=user_id),
            parse_mode="HTML",
            reply_markup=get_back_keyboard(lang, "back_to_manage_users")
        )
        await callback.answer(f"Your ID: {user_id}")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer(_("users_already_here", lang))
        else:
            logging.error(f"Ошибка в cq_get_id_inline (edit): {e}")
            await callback.answer(_("error_unexpected", lang), show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_get_id_inline: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_back_to_manage_users(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    command = "back_to_manage_users"
    if not is_allowed(user_id, command):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        await state.clear()

        # --- ИСПРАВЛЕНИЕ: Используем ключ group_key для перевода ---
        user_list_items = []
        sorted_users = sorted(
            ALLOWED_USERS.items(),
            key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}").lower()
        )
        for uid, group_key in sorted_users: # Используем group_key
            if uid == ADMIN_USER_ID:
                continue
            # Переводим группу по ключу
            group_display = _("group_admins", lang) if group_key == "admins" else _("group_users", lang)
            user_name = USER_NAMES.get(str(uid), f'ID: {uid}')
            user_list_items.append(f" • {user_name} (<b>{group_display}</b>)")
        user_list = "\n".join(user_list_items)
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        if not user_list: user_list = _("users_list_empty", lang)

        await callback.message.edit_text(
            _("users_menu_header", lang, user_list=user_list),
            reply_markup=get_manage_users_keyboard(lang),
            parse_mode="HTML"
        )
        await callback.answer()
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer(_("users_already_here", lang))
        else:
            logging.error(f"Ошибка в cq_back_to_manage_users (edit): {e}")
            await callback.answer(_("error_unexpected", lang), show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_back_to_manage_users: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

# --- Add User ---
async def cq_add_user_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "add_user"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    await callback.message.edit_text(
        _("users_add_title", lang),
        reply_markup=get_back_keyboard(lang, "back_to_manage_users"),
        parse_mode="HTML"
    )
    await state.set_state(ManageUsersStates.waiting_for_user_id)
    await callback.answer()

async def process_add_user_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    original_question_msg_id = None
    if user_id in LAST_MESSAGE_IDS and "manage_users" in LAST_MESSAGE_IDS[user_id]:
        original_question_msg_id = LAST_MESSAGE_IDS[user_id].get("manage_users")
    elif message.reply_to_message and message.reply_to_message.from_user.is_bot:
         original_question_msg_id = message.reply_to_message.message_id

    try:
        new_user_id = int(message.text.strip())
        if new_user_id in ALLOWED_USERS:
            await message.reply(_("users_add_exists", lang))
            return

        await state.update_data(new_user_id=new_user_id)
        prompt_text = _("users_add_group_prompt", lang)
        keyboard = get_group_selection_keyboard(lang) # Клавиатура уже использует новые callback_data

        if original_question_msg_id:
            try:
                await message.bot.edit_message_text(
                    prompt_text,
                    chat_id=message.chat.id,
                    message_id=original_question_msg_id,
                    reply_markup=keyboard
                )
                await message.delete()
            except TelegramBadRequest as edit_err:
                 logging.warning(f"Не удалось отредактировать сообщение {original_question_msg_id} для выбора группы: {edit_err}. Отправляю новое.")
                 await message.reply(prompt_text, reply_markup=keyboard)
        else:
             await message.reply(prompt_text, reply_markup=keyboard)

        await state.set_state(ManageUsersStates.waiting_for_group)
    except ValueError:
        await message.reply(_("users_add_invalid_id", lang))
    except Exception as e:
        logging.error(f"Ошибка в process_add_user_id: {e}")
        await message.reply(_("error_unexpected", lang))

# --- ИСПРАВЛЕНИЕ: Извлекаем ключ 'admins'/'users' и сохраняем его ---
async def process_add_user_group(callback: types.CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback.from_user.id)
    try:
        group_key = callback.data.split('_')[-1] # Получаем 'admins' или 'users'
        if group_key not in ["admins", "users"]:
             raise ValueError(f"Неверный ключ группы в callback_data: {group_key}")

        user_data = await state.get_data()
        new_user_id = user_data.get('new_user_id')

        if not new_user_id:
             raise ValueError(_("users_add_fsm_error", lang))

        ALLOWED_USERS[new_user_id] = group_key # Сохраняем ключ
        new_user_name = await get_user_name(callback.bot, new_user_id) # get_user_name сохранит имя в USER_NAMES и вызовет save_users()

        logging.info(f"Админ {callback.from_user.id} добавил пользователя {new_user_name} ({new_user_id}) в группу '{group_key}'")

        # Переводим ключ для отображения
        group_display = _("group_admins", lang) if group_key == "admins" else _("group_users", lang)
        await callback.message.edit_text(
            _("users_add_success", lang, user_name=new_user_name, user_id=new_user_id, group=group_display),
            parse_mode="HTML",
            reply_markup=get_back_keyboard(lang, "back_to_manage_users")
        )
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка в process_add_user_group: {e}")
        await callback.message.edit_text(
            f"{_('error_unexpected', lang)}: {e}",
            reply_markup=get_back_keyboard(lang, "back_to_manage_users")
        )
    finally:
        await callback.answer()
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

# --- Delete User ---
async def cq_delete_user_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "delete_user"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    # get_delete_users_keyboard уже исправлен для использования ключей
    keyboard = get_delete_users_keyboard(user_id)
    await callback.message.edit_text(
        _("users_delete_title", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

async def cq_delete_user_confirm(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user_lang(admin_id)
    # Права проверяются по callback.data, которая содержит ID, это ОК
    if not is_allowed(admin_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer(_("users_delete_cant_admin", lang), show_alert=True)
            return
        if user_id_to_delete not in ALLOWED_USERS:
            await callback.answer(_("users_delete_not_found", lang), show_alert=True)
            keyboard = get_delete_users_keyboard(admin_id)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group_key = ALLOWED_USERS.pop(user_id_to_delete, "unknown") # Используем ключ 'unknown'
        USER_NAMES.pop(str(user_id_to_delete), None)
        # Удаляем настройки уведомлений и языка для удаленного пользователя
        ALERTS_CONFIG.pop(user_id_to_delete, None)
        shared_state.USER_SETTINGS.pop(user_id_to_delete, None)
        # Сохраняем все изменения
        save_users()
        from core.utils import save_alerts_config # Импорт здесь, чтобы избежать цикла
        save_alerts_config()
        from core.i18n import save_user_settings # Импорт здесь, чтобы избежать цикла
        save_user_settings()

        logging.info(f"Админ {admin_id} удалил пользователя {deleted_user_name} ({user_id_to_delete}) из группы '{deleted_group_key}'")

        keyboard = get_delete_users_keyboard(admin_id)
        await callback.message.edit_text(
            _("users_delete_success_text", lang, user_name=deleted_user_name),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer(
            _("users_delete_success_alert", lang, user_name=deleted_user_name),
            show_alert=False
        )

    except Exception as e:
        logging.error(f"Ошибка в cq_delete_user_confirm: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_request_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    # Права проверяются по callback.data, которая содержит ID, это ОК
    if not is_allowed(user_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             await callback.answer(_("users_delete_self_id_mismatch", lang), show_alert=True)
             return
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer(_("users_delete_cant_admin", lang), show_alert=True)
            return

        keyboard = get_self_delete_confirmation_keyboard(user_id)
        await callback.message.edit_text(
            _("users_delete_self_prompt", lang),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logging.error(f"Ошибка в cq_request_self_delete: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_confirm_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    # Права проверяются по callback.data, которая содержит ID, это ОК
    if not is_allowed(user_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             await callback.answer(_("users_delete_self_id_mismatch", lang), show_alert=True)
             return
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer(_("users_delete_cant_admin", lang), show_alert=True)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group_key = ALLOWED_USERS.pop(user_id_to_delete, "unknown")
        USER_NAMES.pop(str(user_id_to_delete), None)
        # Удаляем настройки уведомлений и языка
        ALERTS_CONFIG.pop(user_id_to_delete, None)
        shared_state.USER_SETTINGS.pop(user_id_to_delete, None)
        # Сохраняем
        save_users()
        from core.utils import save_alerts_config
        save_alerts_config()
        from core.i18n import save_user_settings
        save_user_settings()

        logging.info(f"Пользователь {deleted_user_name} ({user_id_to_delete}) удалил себя из группы '{deleted_group_key}'")

        await callback.message.delete()
        await callback.answer(_("users_delete_self_success", lang), show_alert=True)

    except Exception as e:
        logging.error(f"Ошибка в cq_confirm_self_delete: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_back_to_delete_users(callback: types.CallbackQuery):
     await cq_delete_user_list(callback)

# --- Change Group ---
async def cq_change_group_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "change_group"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    # get_change_group_keyboard уже исправлен для использования ключей
    keyboard = get_change_group_keyboard(user_id)
    await callback.message.edit_text(
        _("users_change_group_title", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

async def cq_select_user_for_group_change(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    # Права проверяются по callback.data, которая содержит ID, это ОК
    if not is_allowed(user_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_change = int(callback.data.split('_')[-1])
        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            await callback.answer(_("users_change_group_invalid", lang), show_alert=True)
            return

        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        current_group_key = ALLOWED_USERS[user_id_to_change] # Получаем ключ 'admins' или 'users'
        # Переводим ключ для отображения
        current_group_display = _("group_admins", lang) if current_group_key == "admins" else _("group_users", lang)

        keyboard = get_group_selection_keyboard(lang, user_id_to_change) # Клавиатура уже использует новые callback_data
        await callback.message.edit_text(
            _("users_change_group_prompt", lang, user_name=user_name, group=current_group_display),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в cq_select_user_for_group_change: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

# --- ИСПРАВЛЕНИЕ: Извлекаем ключ 'admins'/'users' и сохраняем его ---
async def cq_set_group_existing(callback: types.CallbackQuery, state: FSMContext):
    admin_id = callback.from_user.id
    lang = get_user_lang(admin_id)
    # Права проверяются по callback.data, это ОК
    if not is_allowed(admin_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return

    try:
        parts = callback.data.split('_')
        # Проверяем, что это не callback для нового пользователя
        if parts[2] == 'new':
             logging.warning(f"cq_set_group_existing получил callback для нового пользователя: {callback.data}")
             await callback.answer(_("error_internal", lang) + " (wrong handler)", show_alert=True)
             return

        user_id_to_change = int(parts[2])
        new_group_key = parts[3] # Получаем 'admins' или 'users'
        if new_group_key not in ["admins", "users"]:
             raise ValueError(f"Неверный ключ группы в callback_data: {new_group_key}")


        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            await callback.answer(_("users_change_group_invalid", lang), show_alert=True)
            return

        old_group_key = ALLOWED_USERS[user_id_to_change]
        ALLOWED_USERS[user_id_to_change] = new_group_key # Сохраняем ключ
        save_users()
        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        logging.info(f"Админ {admin_id} изменил группу для {user_name} ({user_id_to_change}) с '{old_group_key}' на '{new_group_key}'")

        # get_change_group_keyboard уже исправлен для отображения по ключам
        keyboard = get_change_group_keyboard(admin_id)
        # Переводим новый ключ для отображения
        new_group_display = _("group_admins", lang) if new_group_key == "admins" else _("group_users", lang)

        await callback.message.edit_text(
             _("users_change_group_success_text", lang, user_name=user_name, group=new_group_display),
             reply_markup=keyboard,
             parse_mode="HTML"
        )
        await callback.answer(_("users_change_group_success_alert", lang, user_name=user_name))

    except (IndexError, ValueError) as e:
         logging.error(f"Ошибка разбора callback_data в cq_set_group_existing: {e} (data: {callback.data})")
         await callback.answer(_("error_internal", lang), show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_set_group_existing: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---