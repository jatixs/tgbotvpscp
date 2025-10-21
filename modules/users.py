# /opt/tg-bot/modules/users.py
import asyncio
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

# ИСПРАВЛЕНИЕ: Добавляем 'get_user_name' в импорт
from core.auth import is_allowed, send_access_denied_message, refresh_user_names, save_users, get_user_name
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS, ALLOWED_USERS, USER_NAMES, ALERTS_CONFIG
from core.config import ADMIN_USER_ID
from core.keyboards import (
    get_manage_users_keyboard, get_delete_users_keyboard, get_change_group_keyboard,
    get_group_selection_keyboard, get_self_delete_confirmation_keyboard, get_back_keyboard
)

BUTTON_TEXT = "👤 Пользователи"

class ManageUsersStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    # Text handlers
    dp.message(F.text == BUTTON_TEXT)(manage_users_handler)
    dp.message(F.text == "🆔 Мой ID")(text_get_id_handler) # Связанная команда
    
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
    command = "manage_users"
    if not is_allowed(user_id, command):
        await message.bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)

    user_list = "\n".join([
        f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
        for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
    ])
    if not user_list:
        user_list = "Других пользователей нет."

    sent_message = await message.answer(
        f"👤 <b>Управление пользователями</b>:\n\n{user_list}\n\nВыберите действие:",
        reply_markup=get_manage_users_keyboard(),
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def text_get_id_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "get_id"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    sent_message = await message.answer(
        f"Ваш ID: <code>{user_id}</code>\n\n"
        "<i>(Эта кнопка удалена из главного меню, но вы можете найти ее в меню '👤 Пользователи')</i>", 
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_get_id_inline(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    command = "get_id_inline"
    if not is_allowed(user_id, command):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            f"Ваш ID: <code>{user_id}</code>",
            parse_mode="HTML",
            reply_markup=get_back_keyboard("back_to_manage_users")
        )
        await callback.answer(f"Ваш ID: {user_id}")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): await callback.answer("Вы уже здесь.")
        else:
            logging.error(f"Ошибка в cq_get_id_inline (edit): {e}")
            await callback.answer("⚠️ Ошибка", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_get_id_inline: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

async def cq_back_to_manage_users(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    command = "back_to_manage_users"
    if not is_allowed(user_id, command):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        await state.clear() 
        user_list = "\n".join([
            f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
            for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
        ])
        if not user_list: user_list = "Других пользователей нет."
        await callback.message.edit_text(
            f"👤 <b>Управление пользователями</b>:\n\n{user_list}\n\nВыберите действие:",
            reply_markup=get_manage_users_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): await callback.answer("Вы уже здесь.")
        else:
            logging.error(f"Ошибка в cq_back_to_manage_users (edit): {e}")
            await callback.answer("⚠️ Ошибка", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_back_to_manage_users: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

# --- Add User ---
async def cq_add_user_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "add_user"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Добавление пользователя</b>\n\nВведите Telegram ID пользователя:",
        reply_markup=get_back_keyboard("back_to_manage_users"),
        parse_mode="HTML"
    )
    await state.set_state(ManageUsersStates.waiting_for_user_id)
    await callback.answer()

async def process_add_user_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    original_question_msg_id = None
    if user_id in LAST_MESSAGE_IDS and "manage_users" in LAST_MESSAGE_IDS[user_id]:
        original_question_msg_id = LAST_MESSAGE_IDS[user_id].get("manage_users")
    elif message.reply_to_message and message.reply_to_message.from_user.is_bot:
         original_question_msg_id = message.reply_to_message.message_id

    try:
        new_user_id = int(message.text.strip())
        if new_user_id in ALLOWED_USERS:
            await message.reply("⚠️ Этот пользователь уже добавлен.")
            return

        await state.update_data(new_user_id=new_user_id)

        if original_question_msg_id:
            try:
                await message.bot.edit_message_text(
                    "Отлично. Теперь выберите группу для нового пользователя:",
                    chat_id=message.chat.id,
                    message_id=original_question_msg_id,
                    reply_markup=get_group_selection_keyboard()
                )
                await message.delete()
            except TelegramBadRequest as edit_err:
                 logging.warning(f"Не удалось отредактировать сообщение {original_question_msg_id} для выбора группы: {edit_err}. Отправляю новое.")
                 await message.reply(
                    "Отлично. Теперь выберите группу для нового пользователя:",
                    reply_markup=get_group_selection_keyboard()
                 )
        else:
             await message.reply(
                "Отлично. Теперь выберите группу для нового пользователя:",
                reply_markup=get_group_selection_keyboard()
             )

        await state.set_state(ManageUsersStates.waiting_for_group)
    except ValueError:
        await message.reply("⛔ Неверный ID. Пожалуйста, введите числовой Telegram ID.")
    except Exception as e:
        logging.error(f"Ошибка в process_add_user_id: {e}")
        await message.reply("⚠️ Произошла ошибка. Попробуйте еще раз.")

async def process_add_user_group(callback: types.CallbackQuery, state: FSMContext):
    try:
        group = callback.data.split('_')[-1]
        user_data = await state.get_data()
        new_user_id = user_data.get('new_user_id')

        if not new_user_id:
             raise ValueError("Не найден ID пользователя в состоянии FSM.")

        ALLOWED_USERS[new_user_id] = group
        
        # --- НАЧАЛО ИСПРАВЛЕНИЯ ---
        
        # 1. Удаляем старую логику
        # USER_NAMES[str(new_user_id)] = f"Новый_{new_user_id}"
        # save_users()
        # asyncio.create_task(refresh_user_names(callback.bot))

        # 2. Добавляем новую: получаем имя немедленно
        # Эта функция (из core/auth.py) сама получит имя, обновит USER_NAMES и вызовет save_users()
        new_user_name = await get_user_name(callback.bot, new_user_id)
        
        logging.info(f"Админ {callback.from_user.id} добавил пользователя {new_user_name} ({new_user_id}) в группу '{group}'")

        # 3. Обновляем текст ответа, чтобы показать полученное имя
        await callback.message.edit_text(
            f"✅ Пользователь <b>{new_user_name}</b> (<code>{new_user_id}</code>) успешно добавлен в группу <b>{group}</b>.", 
            parse_mode="HTML", 
            reply_markup=get_back_keyboard("back_to_manage_users")
        )
        
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
        
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка в process_add_user_group: {e}")
        await callback.message.edit_text("⚠️ Произошла ошибка при добавлении пользователя.", reply_markup=get_back_keyboard("back_to_manage_users"))
    finally:
        await callback.answer()

# --- Delete User ---
async def cq_delete_user_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "delete_user"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    keyboard = get_delete_users_keyboard(user_id)
    await callback.message.edit_text("➖ <b>Удаление пользователя</b>\n\nВыберите пользователя для удаления:", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

async def cq_delete_user_confirm(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if not is_allowed(admin_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer("⛔ Нельзя удалить Главного Админа.", show_alert=True)
            return
        if user_id_to_delete not in ALLOWED_USERS:
            await callback.answer("⚠️ Пользователь не найден.", show_alert=True)
            keyboard = get_delete_users_keyboard(admin_id)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group = ALLOWED_USERS.pop(user_id_to_delete, "Неизвестно")
        USER_NAMES.pop(str(user_id_to_delete), None)
        save_users()
        logging.info(f"Админ {admin_id} удалил пользователя {deleted_user_name} ({user_id_to_delete}) из группы '{deleted_group}'")

        keyboard = get_delete_users_keyboard(admin_id)
        await callback.message.edit_text(f"✅ Пользователь <b>{deleted_user_name}</b> удален.\n\nВыберите пользователя для удаления:", reply_markup=keyboard, parse_mode="HTML")
        await callback.answer(f"Пользователь {deleted_user_name} удален.", show_alert=False)

    except Exception as e:
        logging.error(f"Ошибка в cq_delete_user_confirm: {e}")
        await callback.answer("⚠️ Ошибка при удалении.", show_alert=True)

async def cq_request_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             await callback.answer("⛔ Ошибка: ID не совпадают.", show_alert=True)
             return
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer("⛔ Главный Админ не может удалить себя.", show_alert=True)
            return

        keyboard = get_self_delete_confirmation_keyboard(user_id)
        await callback.message.edit_text("⚠️ <b>Вы уверены, что хотите удалить себя из списка пользователей бота?</b>\nВы потеряете доступ ко всем командам.", reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logging.error(f"Ошибка в cq_request_self_delete: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

async def cq_confirm_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             await callback.answer("⛔ Ошибка: ID не совпадают.", show_alert=True)
             return
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer("⛔ Главный Админ не может удалить себя.", show_alert=True)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group = ALLOWED_USERS.pop(user_id_to_delete, "Неизвестно")
        USER_NAMES.pop(str(user_id_to_delete), None)
        save_users()
        logging.info(f"Пользователь {deleted_user_name} ({user_id_to_delete}) удалил себя из группы '{deleted_group}'")

        await callback.message.delete()
        await callback.answer("✅ Вы успешно удалены из пользователей бота.", show_alert=True)

    except Exception as e:
        logging.error(f"Ошибка в cq_confirm_self_delete: {e}")
        await callback.answer("⚠️ Ошибка при удалении.", show_alert=True)

async def cq_back_to_delete_users(callback: types.CallbackQuery):
     await cq_delete_user_list(callback)

# --- Change Group ---
async def cq_change_group_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "change_group"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    keyboard = get_change_group_keyboard()
    await callback.message.edit_text("🔄 <b>Изменение группы</b>\n\nВыберите пользователя:", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

async def cq_select_user_for_group_change(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_change = int(callback.data.split('_')[-1])
        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            await callback.answer("⚠️ Неверный пользователь или Главный Админ.", show_alert=True)
            return

        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        current_group = ALLOWED_USERS[user_id_to_change]
        keyboard = get_group_selection_keyboard(user_id_to_change)
        await callback.message.edit_text(
            f"Выбран пользователь: <b>{user_name}</b>\nТекущая группа: <b>{current_group}</b>\n\nВыберите новую группу:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в cq_select_user_for_group_change: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

async def cq_set_group_existing(callback: types.CallbackQuery, state: FSMContext):
    # Этот хэндлер вызывается только если мы НЕ в состоянии FSM (т.е. не добавляем нового юзера)
    admin_id = callback.from_user.id
    if not is_allowed(admin_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return

    try:
        parts = callback.data.split('_')
        user_id_to_change = int(parts[2])
        new_group = parts[3]

        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            await callback.answer("⚠️ Неверный пользователь или Главный Админ.", show_alert=True)
            return

        old_group = ALLOWED_USERS[user_id_to_change]
        ALLOWED_USERS[user_id_to_change] = new_group
        save_users()
        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        logging.info(f"Админ {admin_id} изменил группу для {user_name} ({user_id_to_change}) с '{old_group}' на '{new_group}'")

        keyboard = get_change_group_keyboard()
        await callback.message.edit_text(
             f"✅ Группа для <b>{user_name}</b> изменена на <b>{new_group}</b>.\n\nВыберите пользователя:",
             reply_markup=keyboard,
             parse_mode="HTML"
        )
        await callback.answer(f"Группа для {user_name} изменена.")

    except (IndexError, ValueError) as e:
         logging.error(f"Ошибка разбора callback_data в cq_set_group_existing: {e} (data: {callback.data})")
         await callback.answer("⚠️ Внутренняя ошибка.", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_set_group_existing: {e}")
        await callback.answer("⚠️ Ошибка при смене группы.", show_alert=True)