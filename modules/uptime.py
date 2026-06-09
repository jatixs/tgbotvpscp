import asyncio
import logging
import time
from aiogram import Dispatcher, types, F
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core import shared_state
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import format_uptime, format_node_event_time, get_host_path, reset_agent_availability_async

BUTTON_KEY = "btn_uptime"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(uptime_handler)
    dp.callback_query(F.data == "reset_main_uptime")(uptime_reset_callback)


async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "uptime"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id, message.bot)
    try:
        with open(get_host_path("/proc/uptime"), "r") as f:
            uptime_seconds = float(f.readline().split()[0])

        avail = shared_state.AGENT_AVAILABILITY
        total_online = float(avail.get("total_online_seconds", 0))
        total_downtime = float(avail.get("total_downtime_seconds", 0))
        internet_downtime = float(avail.get("total_internet_downtime_seconds", 0))
        physical_downtime = max(0.0, total_downtime - internet_downtime)

        response_text = _("agent_uptime_report", lang,
            os_uptime=format_uptime(uptime_seconds, lang),
            last_downtime=format_node_event_time(avail.get("last_downtime_at"), lang),
            last_reboot=format_node_event_time(avail.get("last_reboot_at"), lang),
            total_uptime=format_uptime(total_online, lang),
            total_downtime=format_uptime(total_downtime, lang),
            internet_downtime=format_uptime(internet_downtime, lang),
            physical_downtime=format_uptime(physical_downtime, lang),
        )
        
        inline_kb = []
        if total_downtime > 0:
            inline_kb.append([InlineKeyboardButton(text=_( "btn_reset_uptime", lang), callback_data="reset_main_uptime")])
        kb = InlineKeyboardMarkup(inline_keyboard=inline_kb) if inline_kb else None
    except Exception as e:
        logging.error(f"Uptime error: {e}")
        response_text = _("uptime_fail", lang, error=str(e))
        kb = None
    sent_message = await message.answer(response_text, parse_mode="HTML", reply_markup=kb)
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def uptime_reset_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "uptime"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return

    await reset_agent_availability_async()
    
    await callback.answer(_("uptime_reset_success", lang), show_alert=True)
    
    # Refresh uptime view
    try:
        with open(get_host_path("/proc/uptime"), "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            
        avail = shared_state.AGENT_AVAILABILITY
        total_online = float(avail.get("total_online_seconds", 0))
        total_downtime = float(avail.get("total_downtime_seconds", 0))
        internet_downtime = float(avail.get("total_internet_downtime_seconds", 0))
        physical_downtime = max(0.0, total_downtime - internet_downtime)

        response_text = _("agent_uptime_report", lang,
            os_uptime=format_uptime(uptime_seconds, lang),
            last_downtime=format_node_event_time(avail.get("last_downtime_at"), lang),
            last_reboot=format_node_event_time(avail.get("last_reboot_at"), lang),
            total_uptime=format_uptime(total_online, lang),
            total_downtime=format_uptime(total_downtime, lang),
            internet_downtime=format_uptime(internet_downtime, lang),
            physical_downtime=format_uptime(physical_downtime, lang),
        )
        
        inline_kb = []
        if total_downtime > 0:
            inline_kb.append([InlineKeyboardButton(text=_( "btn_reset_uptime", lang), callback_data="reset_main_uptime")])
        kb = InlineKeyboardMarkup(inline_keyboard=inline_kb) if inline_kb else None
        
        await callback.message.edit_text(response_text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logging.error(f"Uptime error: {e}")
