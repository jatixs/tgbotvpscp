# /opt/tg-bot/modules/users.py
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
    dp.callback_query(StateFilter(ManageUsersStates.waiting_for_group), F.data.startswith("set_group_new_"))(process_add_user_group)
    
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
    dp.callback_query(StateFilter(None), F.data.startswith("set_group_"))(cq_set_group_existing)


# --- Хэндлеры ---

async def manage_users_handler(message: types.Message):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "manage_users"
    if not is_allowed(user_id, command):
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.bot.send_message(message.chat.id, _("access_denied_no_rights", lang))
        # --------------------------------
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)

    user_list = "\n".join([
        f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
        for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
    ])
    if not user_list:
        # --- ИЗМЕНЕНО: Используем i18n ---
        user_list = _("users_list_empty", lang)
        # --------------------------------

    sent_message = await message.answer(
        # --- ИЗМЕНЕНО: Используем i18n ---
        _("users_menu_header", lang, user_list=user_list),
        reply_markup=get_manage_users_keyboard(lang),
        # --------------------------------
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def text_get_id_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "get_id"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    sent_message = await message.answer(
        # --- ИЗМЕНЕНО: Используем i18n ---
        _("my_id_text", lang, user_id=user_id),
        # --------------------------------
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_get_id_inline(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "get_id_inline"
    if not is_allowed(user_id, command):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        await callback.message.edit_text(
            # --- ИЗМЕНЕНО: Используем i18n ---
            _("my_id_inline_text", lang, user_id=user_id),
            parse_mode="HTML",
            reply_markup=get_back_keyboard(lang, "back_to_manage_users")
            # --------------------------------
        )
        await callback.answer(f"Your ID: {user_id}") # Это всплывающее, можно оставить
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): 
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_already_here", lang))
            # --------------------------------
        else:
            logging.error(f"Ошибка в cq_get_id_inline (edit): {e}")
            await callback.answer(_("error_unexpected", lang), show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_get_id_inline: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_back_to_manage_users(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "back_to_manage_users"
    if not is_allowed(user_id, command):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        await state.clear() 
        user_list = "\n".join([
            f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
            for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
        ])
        # --- ИЗМЕНЕНО: Используем i18n ---
        if not user_list: user_list = _("users_list_empty", lang)
        await callback.message.edit_text(
            _("users_menu_header", lang, user_list=user_list),
            reply_markup=get_manage_users_keyboard(lang),
            parse_mode="HTML"
        )
        # --------------------------------
        await callback.answer()
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): 
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_already_here", lang))
            # --------------------------------
        else:
            logging.error(f"Ошибка в cq_back_to_manage_users (edit): {e}")
            await callback.answer(_("error_unexpected", lang), show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_back_to_manage_users: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

# --- Add User ---
async def cq_add_user_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    if not is_allowed(user_id, "add_user"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    # --- ИЗМЕНЕНО: Используем i18n ---
    await callback.message.edit_text(
        _("users_add_title", lang),
        reply_markup=get_back_keyboard(lang, "back_to_manage_users"),
        parse_mode="HTML"
    )
    # --------------------------------
    await state.set_state(ManageUsersStates.waiting_for_user_id)
    await callback.answer()

async def process_add_user_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    original_question_msg_id = None
    if user_id in LAST_MESSAGE_IDS and "manage_users" in LAST_MESSAGE_IDS[user_id]:
        original_question_msg_id = LAST_MESSAGE_IDS[user_id].get("manage_users")
    elif message.reply_to_message and message.reply_to_message.from_user.is_bot:
         original_question_msg_id = message.reply_to_message.message_id

    try:
        new_user_id = int(message.text.strip())
        if new_user_id in ALLOWED_USERS:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await message.reply(_("users_add_exists", lang))
            # --------------------------------
            return

        await state.update_data(new_user_id=new_user_id)

        # --- ИЗМЕНЕНО: Используем i18n ---
        prompt_text = _("users_add_group_prompt", lang)
        keyboard = get_group_selection_keyboard(lang)
        # --------------------------------

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
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.reply(_("users_add_invalid_id", lang))
        # --------------------------------
    except Exception as e:
        logging.error(f"Ошибка в process_add_user_id: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.reply(_("error_unexpected", lang))
        # --------------------------------

async def process_add_user_group(callback: types.CallbackQuery, state: FSMContext):
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(callback.from_user.id)
    # ------------------------------
    try:
        group = callback.data.split('_')[-1]
        user_data = await state.get_data()
        new_user_id = user_data.get('new_user_id')

        if not new_user_id:
             # --- ИЗМЕНЕНО: Используем i18n ---
             raise ValueError(_("users_add_fsm_error", lang))
             # --------------------------------

        ALLOWED_USERS[new_user_id] = group
        
        new_user_name = await get_user_name(callback.bot, new_user_id)
        
        logging.info(f"Админ {callback.from_user.id} добавил пользователя {new_user_name} ({new_user_id}) в группу '{group}'")

        # --- ИЗМЕНЕНО: Используем i18n ---
        group_display = _("group_admins", lang) if group == "Админы" else _("group_users", lang)
        await callback.message.edit_text(
            _("users_add_success", lang, user_name=new_user_name, user_id=new_user_id, group=group_display), 
            parse_mode="HTML", 
            reply_markup=get_back_keyboard(lang, "back_to_manage_users")
        )
        # --------------------------------
        
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка в process_add_user_group: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        await callback.message.edit_text(
            f"{_('error_unexpected', lang)}: {e}", 
            reply_markup=get_back_keyboard(lang, "back_to_manage_users")
        )
        # --------------------------------
    finally:
        await callback.answer()

# --- Delete User ---
async def cq_delete_user_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    if not is_allowed(user_id, "delete_user"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    # --- ИЗМЕНЕНО: Передаем ID ---
    keyboard = get_delete_users_keyboard(user_id)
    await callback.message.edit_text(
        _("users_delete_title", lang), 
        reply_markup=keyboard, 
        parse_mode="HTML"
    )
    # --------------------------------
    await callback.answer()

async def cq_delete_user_confirm(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(admin_id)
    # ------------------------------
    if not is_allowed(admin_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id_to_delete == ADMIN_USER_ID:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_delete_cant_admin", lang), show_alert=True)
            # --------------------------------
            return
        if user_id_to_delete not in ALLOWED_USERS:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_delete_not_found", lang), show_alert=True)
            keyboard = get_delete_users_keyboard(admin_id)
            # --------------------------------
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group = ALLOWED_USERS.pop(user_id_to_delete, _("group_unknown", lang))
        USER_NAMES.pop(str(user_id_to_delete), None)
        save_users()
        logging.info(f"Админ {admin_id} удалил пользователя {deleted_user_name} ({user_id_to_delete}) из группы '{deleted_group}'")

        # --- ИЗМЕНЕНО: Используем i18n ---
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
        # --------------------------------

    except Exception as e:
        logging.error(f"Ошибка в cq_delete_user_confirm: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_request_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    if not is_allowed(user_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             # --- ИЗМЕНЕНО: Используем i18n ---
             await callback.answer(_("users_delete_self_id_mismatch", lang), show_alert=True)
             # --------------------------------
             return
        if user_id_to_delete == ADMIN_USER_ID:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_delete_cant_admin", lang), show_alert=True)
            # --------------------------------
            return
        
        # --- ИЗМЕНЕНО: Используем i18n ---
        keyboard = get_self_delete_confirmation_keyboard(user_id)
        await callback.message.edit_text(
            _("users_delete_self_prompt", lang), 
            reply_markup=keyboard, 
            parse_mode="HTML"
        )
        # --------------------------------
        await callback.answer()

    except Exception as e:
        logging.error(f"Ошибка в cq_request_self_delete: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_confirm_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    if not is_allowed(user_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             # --- ИЗМЕНЕНО: Используем i18n ---
             await callback.answer(_("users_delete_self_id_mismatch", lang), show_alert=True)
             # --------------------------------
             return
        if user_id_to_delete == ADMIN_USER_ID:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_delete_cant_admin", lang), show_alert=True)
            # --------------------------------
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group = ALLOWED_USERS.pop(user_id_to_delete, _("group_unknown", lang))
        USER_NAMES.pop(str(user_id_to_delete), None)
        save_users()
        logging.info(f"Пользователь {deleted_user_name} ({user_id_to_delete}) удалил себя из группы '{deleted_group}'")

        await callback.message.delete()
        # --- ИЗМЕНЕНО: Используем i18n ---
        await callback.answer(_("users_delete_self_success", lang), show_alert=True)
        # --------------------------------

    except Exception as e:
        logging.error(f"Ошибка в cq_confirm_self_delete: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_back_to_delete_users(callback: types.CallbackQuery):
     await cq_delete_user_list(callback)

# --- Change Group ---
async def cq_change_group_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    if not is_allowed(user_id, "change_group"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    # --- ИЗМЕНЕНО: Передаем ID ---
    keyboard = get_change_group_keyboard(user_id)
    await callback.message.edit_text(
        _("users_change_group_title", lang), 
        reply_markup=keyboard, 
        parse_mode="HTML"
    )
    # ------------------------------
    await callback.answer()

async def cq_select_user_for_group_change(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    if not is_allowed(user_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    try:
        user_id_to_change = int(callback.data.split('_')[-1])
        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_change_group_invalid", lang), show_alert=True)
            # --------------------------------
            return

        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        current_group_key = ALLOWED_USERS[user_id_to_change]
        # --- ИЗМЕНЕНО: Используем i18n ---
        current_group_display = _("group_admins", lang) if current_group_key == "Админы" else _("group_users", lang)
        
        keyboard = get_group_selection_keyboard(lang, user_id_to_change)
        await callback.message.edit_text(
            _("users_change_group_prompt", lang, user_name=user_name, group=current_group_display),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        # --------------------------------
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в cq_select_user_for_group_change: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_set_group_existing(callback: types.CallbackQuery, state: FSMContext):
    admin_id = callback.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(admin_id)
    # ------------------------------
    if not is_allowed(admin_id, callback.data):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return

    try:
        parts = callback.data.split('_')
        user_id_to_change = int(parts[2])
        new_group = parts[3] # "Админы" или "Пользователи" (не переведено)

        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("users_change_group_invalid", lang), show_alert=True)
            # --------------------------------
            return

        old_group = ALLOWED_USERS[user_id_to_change]
        ALLOWED_USERS[user_id_to_change] = new_group
        save_users()
        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        logging.info(f"Админ {admin_id} изменил группу для {user_name} ({user_id_to_change}) с '{old_group}' на '{new_group}'")

        # --- ИЗМЕНЕНО: Используем i18n ---
        keyboard = get_change_group_keyboard(admin_id)
        new_group_display = _("group_admins", lang) if new_group == "Админы" else _("group_users", lang)
        
        await callback.message.edit_text(
             _("users_change_group_success_text", lang, user_name=user_name, group=new_group_display),
             reply_markup=keyboard,
             parse_mode="HTML"
        )
        await callback.answer(_("users_change_group_success_alert", lang, user_name=user_name))
        # --------------------------------

    except (IndexError, ValueError) as e:
         logging.error(f"Ошибка разбора callback_data в cq_set_group_existing: {e} (data: {callback.data})")
         # --- ИЗМЕНЕНО: Используем i18n ---
         await callback.answer(_("error_internal", lang), show_alert=True)
         # --------------------------------
    except Exception as e:
        logging.error(f"Ошибка в cq_set_group_existing: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)