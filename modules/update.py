import asyncio
import logging
import os
import sys
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html
from core.config import RESTART_FLAG_FILE, DEPLOY_MODE

BUTTON_KEY = "btn_update"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(update_menu_handler)
    dp.callback_query(F.data == "update_system_apt")(run_system_update)
    dp.callback_query(F.data == "check_bot_update")(check_bot_update)
    dp.callback_query(F.data == "do_bot_update")(run_bot_update)

# --- МЕНЮ ОБНОВЛЕНИЯ ---
async def update_menu_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "update"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_("btn_check_bot_update", lang), callback_data="check_bot_update"),
            InlineKeyboardButton(text=_("btn_update_system", lang), callback_data="update_system_apt")
        ],
        [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
    ])

    sent_message = await message.answer(
        _("update_select_action", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

# --- 1. ОБНОВЛЕНИЕ СИСТЕМЫ (APT) ---
async def run_system_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    await callback.message.edit_text(_("update_start", lang), parse_mode="HTML")
    
    cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    if process.returncode == 0:
        text = _("update_success", lang, output=escape_html(output[-2000:]))
    else:
        text = _("update_fail", lang, code=process.returncode, error=escape_html(error_output[-2000:]))
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, parse_mode="HTML")

# --- 2. ПРОВЕРКА ОБНОВЛЕНИЯ БОТА (GIT) ---
async def check_bot_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    await callback.message.edit_text(_("bot_update_checking", lang), parse_mode="HTML")

    try:
        # Fetch origin
        await asyncio.create_subprocess_shell("git fetch origin")
        
        # Получаем хеши
        proc_local = await asyncio.create_subprocess_shell("git rev-parse HEAD", stdout=asyncio.subprocess.PIPE)
        # ИСПРАВЛЕНИЕ: Используем dummy_ вместо _
        out_local, dummy_ = await proc_local.communicate()
        local_hash = out_local.decode().strip()[:7]

        proc_remote = await asyncio.create_subprocess_shell("git rev-parse @{u}", stdout=asyncio.subprocess.PIPE)
        # ИСПРАВЛЕНИЕ: Используем dummy_ вместо _
        out_remote, dummy_ = await proc_remote.communicate()
        remote_hash = out_remote.decode().strip()[:7]

        if local_hash == remote_hash:
            await callback.message.edit_text(
                _("bot_update_up_to_date", lang, hash=local_hash),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_back", lang), callback_data="back_to_menu")]]),
                parse_mode="HTML"
            )
        else:
            # Получаем лог изменений
            proc_log = await asyncio.create_subprocess_shell(
                "git log HEAD..@{u} --pretty=format:'%h - %s (%cr)'",
                stdout=asyncio.subprocess.PIPE
            )
            # ИСПРАВЛЕНИЕ: Используем dummy_ вместо _
            out_log, dummy_ = await proc_log.communicate()
            changelog = escape_html(out_log.decode().strip())

            warning = _("bot_update_docker_warning", lang) if DEPLOY_MODE == "docker" else ""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_("btn_update_bot_now", lang), callback_data="do_bot_update")],
                [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(
                _("bot_update_available", lang, local=local_hash, remote=remote_hash, log=changelog) + warning,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

    except Exception as e:
        logging.error(f"Git check error: {e}")
        await callback.message.edit_text(f"Error checking git: {e}")

# --- 3. ВЫПОЛНЕНИЕ ОБНОВЛЕНИЯ БОТА ---
async def run_bot_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    chat_id = callback.message.chat.id
    
    await callback.message.edit_text(_("bot_update_start", lang), parse_mode="HTML")

    try:
        # 1. Pull
        pull_cmd = "git pull"
        proc = await asyncio.create_subprocess_shell(pull_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise Exception(f"Git Pull Failed: {stderr.decode()}")

        # 2. Update dependencies
        pip_cmd = f"{sys.executable} -m pip install -r requirements.txt"
        proc_pip = await asyncio.create_subprocess_shell(pip_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc_pip.communicate() 

        # 3. Restart
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(f"{chat_id}:{callback.message.message_id}")

        restart_cmd = ""
        if DEPLOY_MODE == "docker":
            container_name = os.environ.get("TG_BOT_CONTAINER_NAME")
            if container_name:
                restart_cmd = f"docker restart {container_name}"
            else:
                restart_cmd = "kill 1" 
        else:
            restart_cmd = "sudo systemctl restart tg-bot.service"

        await callback.message.edit_text(_("bot_update_success", lang), parse_mode="HTML")
        logging.info(f"Update finished. Restarting via: {restart_cmd}")
        
        asyncio.create_task(do_restart(restart_cmd))

    except Exception as e:
        logging.error(f"Update failed: {e}")
        await callback.message.edit_text(_("bot_update_fail", lang, error=str(e)), parse_mode="HTML")

async def do_restart(cmd):
    await asyncio.sleep(1)
    await asyncio.create_subprocess_shell(cmd)