import os
import glob
import json
import asyncio
from aiogram import Dispatcher, types, F
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from core.i18n import I18nFilter, get_user_lang, get_text
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.keyboards import get_backups_menu_keyboard
from core.utils import format_traffic
from modules import traffic as traffic_module

BUTTON_KEY = "btn_backups"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=get_text(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(backups_main_menu_handler)
    dp.callback_query(F.data == "back_to_backups_main")(backups_main_menu_callback)
    dp.callback_query(F.data == "backup_in_dev")(backup_in_dev_handler)
    dp.callback_query(F.data == "close_backups_menu")(close_menu_handler)
    dp.callback_query(F.data == "open_traffic_backups")(traffic_backup_ui_handler)
    dp.callback_query(F.data == "create_traffic_backup")(create_traffic_backup_handler)
    dp.callback_query(F.data.startswith("delete_backup_"))(delete_traffic_backup_handler)


async def backups_main_menu_handler(message: types.Message):
    """Вход в главное меню бэкапов (через реплай кнопку)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    
    if not is_allowed(user_id, "settings"):
        await send_access_denied_message(message.bot, user_id, chat_id, "settings")
        return

    await delete_previous_message(
        user_id,
        list(LAST_MESSAGE_IDS.get(user_id, {}).keys()),
        chat_id,
        message.bot,
    )

    text = get_text("backups_menu_title", lang)
    kb = get_backups_menu_keyboard(lang)
    
    sent_msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})["backups_menu"] = sent_msg.message_id


async def backups_main_menu_callback(callback: types.CallbackQuery):
    """Возврат в главное меню бэкапов (кнопка Назад)"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    text = get_text("backups_menu_title", lang)
    kb = get_backups_menu_keyboard(lang)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


async def traffic_backup_ui_handler(callback: types.CallbackQuery):
    """Меню управления бэкапами трафика (с пояснением)"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    backups = sorted(glob.glob(os.path.join(config.TRAFFIC_BACKUP_DIR, "traffic_backup_*.json")), reverse=True)
    explanation = get_text("traffic_backup_explanation", lang)
    header = get_text("traffic_backup_menu_title", lang)
    text = f"{explanation}\n{header}\n"
    
    buttons = []
    
    if not backups:
        text += f"\n{get_text('no_backups', lang)}"
    else:
        text += "\n"
        for idx, backup_path in enumerate(backups):
            try:
                filename = os.path.basename(backup_path)
                with open(backup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    date_str = data.get("date", "Unknown")
                    rx = format_traffic(data.get("rx", 0), lang)
                    tx = format_traffic(data.get("tx", 0), lang)
                    
                    text += f"📂 <b>{date_str}</b>\n└ ⬇️{rx} | ⬆️{tx}\n"
                    
                    if idx < 3:
                        buttons.append([InlineKeyboardButton(text=f"🗑 {get_text('btn_delete', lang)} {date_str}", callback_data=f"delete_backup_{filename}")])
            except:
                pass
    
    buttons.insert(0, [InlineKeyboardButton(text=get_text("btn_create_backup", lang), callback_data="create_traffic_backup")])
    buttons.append([InlineKeyboardButton(text=f"🔙 {get_text('btn_back', lang)}", callback_data="back_to_backups_main")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


async def create_traffic_backup_handler(callback: types.CallbackQuery):
    rx, tx = traffic_module.get_current_traffic_total()
    await asyncio.to_thread(traffic_module.save_backup_file, rx, tx)
    
    await callback.answer(get_text("backup_created", get_user_lang(callback.from_user.id)))
    await traffic_backup_ui_handler(callback)


async def delete_traffic_backup_handler(callback: types.CallbackQuery):
    filename = callback.data.replace("delete_backup_", "")
    filepath = os.path.join(config.TRAFFIC_BACKUP_DIR, filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            await callback.answer(get_text("backup_deleted", get_user_lang(callback.from_user.id)))
        except Exception as e:
            await callback.answer(f"Error: {e}", show_alert=True)
    else:
        await callback.answer("File not found")
    await traffic_backup_ui_handler(callback)


async def backup_in_dev_handler(callback: types.CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.answer(get_text("backup_in_dev", lang), show_alert=True)

async def close_menu_handler(callback: types.CallbackQuery):
    await callback.message.delete()