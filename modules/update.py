import asyncio
import logging
import os
import sys
import re
import signal
import shlex
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html
from core.config import RESTART_FLAG_FILE, DEPLOY_MODE

BUTTON_KEY = "btn_update"
CHECK_INTERVAL = 21600
LAST_NOTIFIED_VERSION = None

def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(update_menu_handler)
    dp.callback_query(F.data == "update_system_apt")(run_system_update)
    dp.callback_query(F.data == "check_bot_update")(check_bot_update)
    dp.callback_query(F.data.startswith("do_bot_update"))(run_bot_update)

def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    return [
        asyncio.create_task(auto_update_checker(bot), name="AutoUpdateChecker")
    ]

# --- SYSTEM UTILS ---

def validate_branch_name(branch: str) -> str:
    branch = (branch or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._/\-]+", branch):
        raise ValueError(f"Security Alert: Invalid branch name: '{branch}'")
    return branch

async def run_command(cmd):
    """
    Run a command asynchronously without invoking a shell.

    `cmd` can be either:
      - a list/tuple of arguments: ['git', 'fetch', 'origin']
      - a string, which will be split into args with shlex.split
    """
    try:
        if isinstance(cmd, (str, bytes)):
            # Safely split string into arguments; no shell is used.
            if isinstance(cmd, bytes):
                cmd = cmd.decode()
            args = shlex.split(cmd)
        else:
            args = list(cmd)

        if not args:
            return -1, "", "Empty command"

        proc = await asyncio.create_subprocess_exec(
            args[0],
            *args[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode().strip(), stderr.decode().strip()
    except Exception as e:
        return -1, "", str(e)

# --- GIT HELPERS ---

async def get_current_branch():
    code, out, err = await run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if code == 0 and out:
        return out.strip()
    return "main"

async def get_remote_hash(branch):
    await run_command(f"git fetch origin {branch}")
    code, out, err = await run_command(f"git rev-parse origin/{branch}")
    return out.strip() if code == 0 else None

async def get_local_hash():
    code, out, err = await run_command("git rev-parse HEAD")
    return out.strip() if code == 0 else None

async def get_changelog_entry(branch: str, lang: str) -> str:
    """
    Получает описание последнего обновления из CHANGELOG.md или CHANGELOG.en.md.
    """
    filename = "CHANGELOG.en.md" if lang == "en" else "CHANGELOG.md"
    cmd = f"git show origin/{branch}:{filename}"
    
    code, out, err = await run_command(cmd)
    
    if code != 0 or not out:
        return "Changelog not found or empty."

    lines = out.splitlines()
    result = []
    found_start = False
    
    # Ищем блок, начинающийся с ## [X.Y.Z] и берем всё до следующего такого блока
    for line in lines:
        # Регулярка для поиска заголовка версии: ## [1.2.3] ...
        if re.match(r"^## \[\d+\.\d+\.\d+\]", line):
            if found_start:
                # Нашли СЛЕДУЮЩУЮ версию - останавливаемся
                break
            else:
                # Нашли ПЕРВУЮ (новую) версию
                found_start = True
                result.append(line)
        elif found_start:
            result.append(line)
            
    if not result:
        return "No release notes found in recent CHANGELOG."
        
    return "\n".join(result).strip()

def get_version_from_file() -> str:
    try:
        if os.path.exists("CHANGELOG.md"):
            with open("CHANGELOG.md", "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"## \[(\d+\.\d+\.\d+)\]", content)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "Unknown"

async def get_update_info():
    try:
        branch = await get_current_branch()
        branch = validate_branch_name(branch)

        fetch_code, _, _ = await run_command(["git", "fetch", "origin"])
        if fetch_code != 0:
            return get_version_from_file(), "Error", branch, False

        local_hash = await get_local_hash()
        remote_hash = await get_remote_hash(branch)
        local_ver_display = get_version_from_file()
        
        if not local_hash or not remote_hash:
            return local_ver_display, "Unknown", branch, False

        update_available = (local_hash != remote_hash)
        remote_ver_display = "New Commit"
        
        if update_available:
            # Пытаемся вытащить номер версии из удаленного файла для красоты
            code, out, err = await run_command(["git", "show", f"origin/{branch}:CHANGELOG.md"])
            if code == 0:
                match = re.search(r"## \[(\d+\.\d+\.\d+)\]", out)
                remote_ver_display = match.group(1) if match else remote_hash[:7]
            else:
                remote_ver_display = remote_hash[:7]
        else:
            remote_ver_display = local_ver_display

        return local_ver_display, remote_ver_display, branch, update_available

    except Exception as e:
        logging.error(f"Error getting update info: {e}")
        return "Error", "Error", "main", False

async def execute_bot_update(branch: str, restart_source: str = "unknown"):
    try:
        branch = validate_branch_name(branch)
        # Log Injection protection
        safe_branch = branch.replace('\n', '').replace('\r', '')
        logging.info(f"Starting bot update on branch '{safe_branch}'...")
        
        fetch_code, _, fetch_err = await run_command(["git", "fetch", "origin"])
        if fetch_code != 0:
            raise Exception(f"Git fetch failed: {fetch_err}")
        
        reset_code, _, reset_err = await run_command(["git", "reset", "--hard", f"origin/{branch}"])
        if reset_code != 0:
            raise Exception(f"Git reset failed: {reset_err}")

        pip_cmd = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
        pip_code, _, pip_err = await run_command(pip_cmd)
        if pip_code != 0:
            logging.warning(f"Pip install warning: {pip_err}")

        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(restart_source)

        logging.info("Update finished. Restarting...")
        asyncio.create_task(self_terminate())
        
    except Exception as e:
        logging.error(f"Execute update failed: {e}")
        raise e

async def self_terminate():
    await asyncio.sleep(1)
    os.kill(os.getpid(), signal.SIGTERM)

async def auto_update_checker(bot: Bot):
    global LAST_NOTIFIED_VERSION
    await asyncio.sleep(60)

    while True:
        try:
            local_v, remote_v, branch, available = await get_update_info()

            if available and remote_v != LAST_NOTIFIED_VERSION:
                branch = validate_branch_name(branch)
                
                # Заранее получаем логи для поддерживаемых языков
                log_ru = await get_changelog_entry(branch, "ru")
                log_en = await get_changelog_entry(branch, "en")
                
                def get_log_for_lang(l):
                    return log_en if l == "en" else log_ru

                warning = _("bot_update_docker_warning", config.DEFAULT_LANGUAGE) if DEPLOY_MODE == "docker" else ""
                
                # Передаем правильный лог в зависимости от языка админа
                await send_alert(
                    bot, 
                    lambda lang: _("bot_update_available", lang, local=local_v, remote=remote_v, log=escape_html(get_log_for_lang(lang))) + warning,
                    "update" 
                )
                LAST_NOTIFIED_VERSION = remote_v
            
        except Exception as e:
            logging.error(f"AutoUpdateChecker failed: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)

# --- HANDLERS ---

async def update_menu_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "update"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

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

async def run_system_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    await callback.message.edit_text(_("update_start", lang), parse_mode="HTML")
    
    cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"
    code, out, err = await run_command(cmd)

    if code == 0:
        text = _("update_success", lang, output=escape_html(out[-2000:]))
    else:
        text = _("update_fail", lang, code=code, error=escape_html(err[-2000:]))
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, parse_mode="HTML")

async def check_bot_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    await callback.message.edit_text(_("bot_update_checking", lang), parse_mode="HTML")

    try:
        local_v, remote_v, branch, available = await get_update_info()
        
        if available:
            branch = validate_branch_name(branch)
            # Получаем лог именно для языка пользователя
            changes_log = await get_changelog_entry(branch, lang)
            
            warning = _("bot_update_docker_warning", lang) if DEPLOY_MODE == "docker" else ""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_("btn_update_bot_now", lang), callback_data=f"do_bot_update:{branch}")],
                [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(
                _("bot_update_available", lang, local=local_v, remote=remote_v, log=escape_html(changes_log)) + warning,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        else:
            await callback.message.edit_text(
                _("bot_update_up_to_date", lang, hash=local_v),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_("btn_back", lang), callback_data="back_to_menu")]]),
                parse_mode="HTML"
            )

    except Exception as e:
        logging.error(f"Update check error: {e}", exc_info=True)
        await callback.message.edit_text(f"Error checking updates: {e}")

async def run_bot_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    chat_id = callback.message.chat.id
    
    data_parts = callback.data.split(":")
    branch = data_parts[1] if len(data_parts) > 1 else "main"
    
    await callback.message.edit_text(_("bot_update_start", lang), parse_mode="HTML")

    try:
        restart_token = f"{chat_id}:{callback.message.message_id}"
        await execute_bot_update(branch, restart_source=restart_token)
        
        await callback.message.edit_text(_("bot_update_success", lang), parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Update failed: {e}")
        await callback.message.edit_text(_("bot_update_fail", lang, error=str(e)), parse_mode="HTML")