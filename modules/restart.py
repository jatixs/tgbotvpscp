import asyncio
import logging
import os
import signal
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.config import RESTART_FLAG_FILE

BUTTON_KEY = "btn_restart"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(restart_confirm_handler)
    dp.callback_query(F.data == "restart_confirm")(restart_execute_handler)
    dp.callback_query(F.data == "restart_cancel")(restart_cancel_handler)


async def restart_confirm_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "restart"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=_(
                    "btn_confirm",
                    lang),
                callback_data="restart_confirm"),
            InlineKeyboardButton(
                text=_(
                    "btn_cancel",
                    lang),
                callback_data="restart_cancel")
        ]
    ])

    sent_message = await message.answer(
        _("restart_start", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def restart_cancel_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    try:
        await callback.message.delete()
    except Exception as e:
        logging.debug(f"Restart cancel delete error: {e}")
    await callback.answer(_("btn_cancel", lang))


async def restart_execute_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    lang = get_user_lang(user_id)

    await callback.message.edit_text(_("restart_start", lang), parse_mode="HTML")

    try:

        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(f"{chat_id}:{callback.message.message_id}")

        asyncio.create_task(self_terminate())

    except Exception as e:
        logging.error(f"Restart command failed: {e}")
        await callback.message.edit_text(_("restart_error", lang, error=str(e)))


async def self_terminate():
    await asyncio.sleep(1)
    os.kill(os.getpid(), signal.SIGTERM)
