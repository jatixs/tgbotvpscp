import asyncio
import logging
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core import shared_state

BUTTON_KEY = "btn_reboot"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(reboot_confirm_handler)
    dp.callback_query(F.data == "reboot_confirm")(reboot_execute_handler)
    dp.callback_query(F.data == "reboot_cancel")(reboot_cancel_handler)


async def reboot_confirm_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "reboot"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id, message.bot)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("btn_reboot_confirm", lang), callback_data="reboot_confirm"
                ),
                InlineKeyboardButton(
                    text=_("btn_reboot_cancel", lang), callback_data="reboot_cancel"
                ),
            ]
        ]
    )
    sent_message = await message.answer(
        _("reboot_confirm_prompt", lang), reply_markup=keyboard, parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def reboot_cancel_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    try:
        await callback.message.delete()
    except Exception as e:
        logging.debug(f"Reboot cancel delete error: {e}")
    await callback.answer(_("btn_cancel", lang))


async def reboot_execute_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    bot: Bot = callback.bot
    await callback.message.edit_text(_("reboot_confirmed", lang), parse_mode="HTML")
    try:
        shared_state.IS_RESTARTING = True
        cmd = "nohup sh -c 'sleep 5 && /sbin/reboot' >/dev/null 2>&1 &"
        await asyncio.create_subprocess_shell(cmd)
    except Exception as e:
        logging.error(f"Reboot command failed: {e}")
        await callback.message.edit_text(_("reboot_error", lang, error=str(e)))
