# /opt/tg-bot/modules/reboot.py
import asyncio
import logging
import os
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.auth import is_allowed
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.config import REBOOT_FLAG_FILE, INSTALL_MODE
from core.keyboards import get_reboot_confirmation_keyboard

BUTTON_TEXT = "🔄 Перезагрузка сервера"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(reboot_confirm_handler)
    dp.callback_query(F.data == "reboot")(reboot_handler)

async def reboot_confirm_handler(message: types.Message):
    user_id = message.from_user.id
    command = "reboot_confirm"
    if not is_allowed(user_id, command):
        await message.bot.send_message(message.chat.id, "⛔ Эта функция доступна только в режиме 'root'.")
        return
        
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    sent_message = await message.answer(
        "⚠️ Вы уверены, что хотите <b>перезагрузить сервер</b>? Все активные соединения будут разорваны.", 
        reply_markup=get_reboot_confirmation_keyboard(), 
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def reboot_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    command = "reboot" 

    if not is_allowed(user_id, command):
        try:
             await callback.answer("⛔ Отказано в доступе (не root).", show_alert=True) 
        except TelegramBadRequest:
             pass
        return

    try:
        await callback.bot.edit_message_text(
            "✅ Подтверждено. <b>Запускаю перезагрузку VPS</b>...", 
            chat_id=chat_id, 
            message_id=message_id, 
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        logging.warning("Не удалось отредактировать сообщение о перезагрузке (возможно, удалено).")

    try:
        with open(REBOOT_FLAG_FILE, "w") as f:
            f.write(str(user_id))
    except Exception as e:
        logging.error(f"Не удалось записать флаг перезагрузки: {e}")

    try:
        reboot_cmd = "reboot" # В root-режиме 'sudo' не нужен
        logging.info(f"Выполнение команды перезагрузки: {reboot_cmd}")
        process = await asyncio.create_subprocess_shell(reboot_cmd)
        await process.wait()
        logging.info("Команда перезагрузки отправлена.")
    except Exception as e:
        logging.error(f"Ошибка при отправке команды reboot: {e}")
        try:
            await callback.bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при отправке команды перезагрузки: {e}")
        except Exception as send_e:
            logging.error(f"Не удалось отправить сообщение об ошибке перезагрузки: {send_e}")