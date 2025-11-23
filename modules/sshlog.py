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
from core.utils import get_country_flag, get_server_timezone_label, escape_html, get_host_path

BUTTON_KEY = "btn_sshlog"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(sshlog_handler)


async def sshlog_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "sshlog"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    sent = await message.answer(_("sshlog_searching", lang))
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent.message_id

    try:
        log_file = None
        if os.path.exists(get_host_path("/var/log/secure")):
            log_file = get_host_path("/var/log/secure")
        elif os.path.exists(get_host_path("/var/log/auth.log")):
            log_file = get_host_path("/var/log/auth.log")

        lines = []
        src_txt = ""

        if log_file:
            src_txt = _(
                "selftest_ssh_source",
                lang,
                source=os.path.basename(log_file))
            proc = await asyncio.create_subprocess_shell(f"tail -n 200 {log_file}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            # FIX: _ -> stderr_dummy
            out, stderr_dummy = await proc.communicate()
            lines = out.decode('utf-8', 'ignore').split('\n')
        else:
            src_txt = _("selftest_ssh_source_journal", lang)
            proc = await asyncio.create_subprocess_shell("journalctl -u ssh -n 100 --no-pager -o short-precise", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            # FIX: _ -> stderr_dummy
            out, stderr_dummy = await proc.communicate()
            lines = out.decode('utf-8', 'ignore').split('\n')

        entries = []
        count = 0
        tz = get_server_timezone_label()

        for line in reversed(lines):
            if count >= 10:
                break
            if "sshd" not in line:
                continue

            dt = None
            match_iso = re.search(
                r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            match_sys = re.search(
                r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

            try:
                if match_iso:
                    dt = datetime.strptime(
                        match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                elif match_sys:
                    dt = datetime.strptime(
                        match_sys.group(1), "%b %d %H:%M:%S")
                    dt = dt.replace(year=datetime.now().year)
            except BaseException:
                continue

            if not dt:
                continue

            key = None
            data = {}

            # Success
            m = re.search(
                r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
            if m:
                key = "sshlog_entry_success"
                u, ip = m.groups()
                fl = await get_country_flag(ip)
                data = {
                    "user": escape_html(u),
                    "ip": escape_html(ip),
                    "flag": fl}

            # Failures
            if not key:
                m = re.search(
                    r"Failed\s+(?:\S+)\s+for\s+invalid\s+user\s+(\S+)\s+from\s+(\S+)", line)
                if m:
                    key = "sshlog_entry_invalid_user"
                    u, ip = m.groups()
                    fl = await get_country_flag(ip)
                    data = {
                        "user": escape_html(u),
                        "ip": escape_html(ip),
                        "flag": fl}

            if not key:
                m = re.search(r"Failed password for (\S+) from (\S+)", line)
                if m:
                    key = "sshlog_entry_wrong_pass"
                    u, ip = m.groups()
                    fl = await get_country_flag(ip)
                    data = {
                        "user": escape_html(u),
                        "ip": escape_html(ip),
                        "flag": fl}

            if key:
                data.update({"time": dt.strftime('%H:%M:%S'),
                            "date": dt.strftime('%d.%m.%Y'), "tz": tz})
                entries.append(_(key, lang, **data))
                count += 1

        if entries:
            await message.bot.edit_message_text(_("sshlog_header", lang, count=count, source=src_txt, log_output="\n\n".join(entries)), chat_id=chat_id, message_id=sent.message_id, parse_mode="HTML")
        else:
            await message.bot.edit_message_text(_("sshlog_not_found", lang, source=src_txt), chat_id=chat_id, message_id=sent.message_id)

    except Exception as e:
        logging.error(f"SSHLog error: {e}")
        await message.bot.edit_message_text(_("sshlog_read_error", lang, error=str(e)), chat_id=chat_id, message_id=sent.message_id)