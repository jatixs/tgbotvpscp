import asyncio
import logging
import os
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.i18n import _, I18nFilter, get_user_lang
from core import config

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.config import RESTART_FLAG_FILE, DEPLOY_MODE

BUTTON_KEY = "btn_restart"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(restart_handler)


async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "restart"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    sent_msg = await message.answer(_("restart_start", lang))

    try:
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(f"{chat_id}:{sent_msg.message_id}")

        restart_cmd = ""
        if DEPLOY_MODE == "docker":
            container_name = os.environ.get("TG_BOT_CONTAINER_NAME")
            if not container_name:
                raise Exception("TG_BOT_CONTAINER_NAME не установлен в .env")
            restart_cmd = f"docker restart {container_name}"
            logging.info(f"Выполнение Docker-рестарта: {restart_cmd}")

        else:
            restart_cmd = "sudo systemctl restart tg-bot.service"
            logging.info(f"Выполнение Systemd-рестарта: {restart_cmd}")

        await asyncio.create_subprocess_shell(restart_cmd)
        logging.info(f"Команда перезапуска ({DEPLOY_MODE}) отправлена.")

    except Exception as e:
        logging.error(f"Ошибка в restart_handler: {e}")
        if os.path.exists(RESTART_FLAG_FILE):
            try:
                os.remove(RESTART_FLAG_FILE)
            except OSError:
                pass
        try:
            await message.bot.edit_message_text(
                text=_("restart_error", lang, error=str(e)),
                chat_id=chat_id,
                message_id=sent_msg.message_id
            )
        except TelegramBadRequest:
            pass