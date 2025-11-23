import asyncio
import os
import re
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import get_country_flag, get_server_timezone_label, get_host_path

BUTTON_KEY = "btn_fail2ban"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(fail2ban_handler)


async def fail2ban_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "fall2ban"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    log_file = get_host_path("/var/log/fail2ban.log")

    if not os.path.exists(log_file):
        sent = await message.answer(_("f2b_log_not_found", lang, path=log_file), parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent.message_id
        return

    try:
        # Читаем последние строки через tail (асинхронно)
        proc = await asyncio.create_subprocess_shell(f"tail -n 50 {log_file}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        lines = out.decode('utf-8', 'ignore').split('\n')

        entries = []
        tz = get_server_timezone_label()

        for line in reversed(lines):
            if "fail2ban.actions" not in line:
                continue

            # Ban detect
            match = re.search(
                r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* Ban\s+(\S+)",
                line)
            if match:
                ts, ip = match.groups()
                # ИСПРАВЛЕНО: await
                flag = await get_country_flag(ip)
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S,%f")
                    entries.append(_("f2b_ban_entry",
                                     lang,
                                     ban_type=_("f2b_banned",
                                                lang),
                                     flag=flag,
                                     ip=ip,
                                     time=dt.strftime('%H:%M:%S'),
                                     tz=tz,
                                     date=dt.strftime('%d.%m.%Y')))
                except BaseException:
                    continue

            if len(entries) >= 10:
                break

        if entries:
            await message.answer(_("f2b_header", lang, log_output="\n\n".join(entries)), parse_mode="HTML")
        else:
            await message.answer(_("f2b_no_bans", lang))

    except Exception as e:
        logging.error(f"F2B error: {e}")
        await message.answer(_("f2b_read_error_generic", lang, error=str(e)))
