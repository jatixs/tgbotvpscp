# /opt/tg-bot/modules/restart.py
import asyncio
import logging
import os
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.config import RESTART_FLAG_FILE

BUTTON_TEXT = "♻️ Перезапуск бота"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(restart_handler)

async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "restart"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    sent_msg = await message.answer("♻️ Бот уходит на перезапуск…")
    
    try:
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(f"{chat_id}:{sent_msg.message_id}")
        
        restart_cmd = "sudo systemctl restart tg-bot.service"
        process = await asyncio.create_subprocess_shell(restart_cmd)
        await process.wait()
        logging.info("Restart command sent for tg-bot.service")
        
    except Exception as e:
        logging.error(f"Ошибка в restart_handler при отправке команды перезапуска: {e}")
        if os.path.exists(RESTART_FLAG_FILE):
            try:
                os.remove(RESTART_FLAG_FILE)
            except OSError:
                pass
        try:
            await message.bot.edit_message_text(
                text=f"⚠️ Ошибка при попытке перезапуска сервиса: {str(e)}", 
                chat_id=chat_id, 
                message_id=sent_msg.message_id
            )
        except Exception as edit_e:
            logging.error(f"Failed to edit restart error message: {edit_e}")