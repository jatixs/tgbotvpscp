# /opt/tg-bot/modules/optimize.py
import asyncio
import logging
import re
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_optimize"
# --------------------------------

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(optimize_handler)
    # --------------------------------------

async def optimize_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "optimize" # Имя команды оставляем

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    # --- ИЗМЕНЕНО: Используем i18n ---
    sent_message = await message.answer(
        _("optimize_start", lang),
        parse_mode="HTML"
    )
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    
    cmd = (
        "bash -c \""
        "apt update && apt full-upgrade -y && apt autoremove --purge -y && "
        "apt autoclean -y && journalctl --vacuum-time=2d && "
        "rm -rf /var/tmp/* /tmp/* /root/.cache/* && "
        "DEBIAN_FRONTEND=noninteractive apt install preload cpufrequtils zram-tools -y && "
        "systemctl enable preload && systemctl start preload && "
        "echo 'vm.swappiness=10' | tee -a /etc/sysctl.conf && "
        "echo 'vm.vfs_cache_pressure=50' | tee -a /etc/sysctl.conf && "
        "sysctl -p && systemctl restart systemd-journald && systemctl daemon-reexec"
        "\""
    )
    
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    await delete_previous_message(user_id, command, chat_id, message.bot)

    if process.returncode == 0:
        # --- ИЗМЕНЕНО: Используем i18n ---
        response_text = _("optimize_success", lang, output=escape_html(output[-1000:]))
        # --------------------------------
    else:
        # --- ИЗМЕНЕНО: Используем i18n ---
        response_text = _("optimize_fail", lang, 
                          code=process.returncode, 
                          stdout=escape_html(output[-1000:]), 
                          stderr=escape_html(error_output[-2000:]))
        # --------------------------------

    sent_message_final = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id