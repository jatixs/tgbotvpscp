import asyncio
import logging
import os
import sys
import re
import signal
import subprocess
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
CHECK_INTERVAL = 21600  # 6 часов
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


# --- SECURITY UTILS ---

def validate_branch_name(branch: str) -> str:
    """
    Валидирует имя ветки для защиты от Command Injection.
    Разрешает только буквы, цифры, дефис, подчеркивание, точку и слеш.
    """
    branch = (branch or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._/\-]+", branch):
        raise ValueError(f"Security Alert: Invalid branch name detected: '{branch}'")
    return branch


async def run_command(cmd: str):
    """Асинхронный запуск shell команды с захватом вывода."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode().strip(), stderr.decode().strip()
    except Exception as e:
        return -1, "", str(e)


# --- GIT HELPERS ---

async def get_current_branch():
    """Определяет текущую активную ветку."""
    code, out, err = await run_command("git rev-parse --abbrev-ref HEAD")
    if code == 0 and out:
        return out.strip()
    return "main"  # Fallback


async def get_remote_hash(branch):
    """Получает хеш последнего коммита в удаленном репозитории."""
    # Сначала обновляем информацию о ветках
    await run_command(f"git fetch origin {branch}")
    code, out, err = await run_command(f"git rev-parse origin/{branch}")
    return out.strip() if code == 0 else None


async def get_local_hash():
    """Получает хеш текущего локального коммита."""
    code, out, err = await run_command("git rev-parse HEAD")
    return out.strip() if code == 0 else None


def get_version_from_changelog() -> str:
    """Пытается найти версию в локальном CHANGELOG.md."""
    try:
        if os.path.exists("CHANGELOG.md"):
            with open("CHANGELOG.md", "r", encoding="utf-8") as f:
                content = f.read()
                # Ищем ## [1.2.3]
                match = re.search(r"## \[(\d+\.\d+\.\d+)\]", content)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "Unknown"


async def get_update_info():
    """
    Возвращает информацию об обновлении.
    Output: (local_ver, remote_ver, branch, update_available_bool)
    """
    try:
        branch = await get_current_branch()
        # Валидируем имя ветки сразу
        branch = validate_branch_name(branch)

        # 1. Синхронизируем ссылки (без изменения файлов)
        fetch_code, _, fetch_err = await run_command("git fetch origin")
        if fetch_code != 0:
            logging.error(f"Git fetch failed: {fetch_err}")
            return get_version_from_changelog(), "Error", branch, False

        local_hash = await get_local_hash()
        remote_hash = await get_remote_hash(branch)
        
        local_ver_display = get_version_from_changelog()
        
        # Если не смогли получить хеши
        if not local_hash or not remote_hash:
            return local_ver_display, "Unknown", branch, False

        # Сравниваем хеши
        update_available = local_hash != remote_hash
        
        remote_ver_display = "New Commit"
        if update_available:
            code, out, err = await run_command(f"git show origin/{branch}:CHANGELOG.md")
            if code == 0:
                match = re.search(r"## \[(\d+\.\d+\.\d+)\]", out)
                if match:
                    remote_ver_display = match.group(1)
                else:
                    remote_ver_display = remote_hash[:7]
            else:
                remote_ver_display = remote_hash[:7]
        else:
            remote_ver_display = local_ver_display

        return local_ver_display, remote_ver_display, branch, update_available

    except Exception as e:
        logging.error(f"Error getting update info: {e}")
        return "Error", "Error", "main", False


async def execute_bot_update(branch: str, restart_source: str = "unknown"):
    """
    Выполняет безопасное обновление бота.
    """
    try:
        # 1. Security Check
        branch = validate_branch_name(branch)
        logging.info(f"Starting bot update sequence on branch '{branch}'...")
        
        # 2. Fetch
        code, _, err = await run_command("git fetch origin")
        if code != 0:
            raise Exception(f"Git fetch failed: {err}")
        
        # 3. Hard Reset
        code, _, err = await run_command(f"git reset --hard origin/{branch}")
        if code != 0:
            raise Exception(f"Git reset failed: {err}")

        # 4. Dependency Update
        pip_cmd = f"{sys.executable} -m pip install -r requirements.txt"
        code, _, err = await run_command(pip_cmd)
        if code != 0:
            logging.warning(f"Pip install warning (non-critical): {err}")

        # 5. Set Restart Flag
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(restart_source)

        # 6. Self-Termination
        logging.info("Update finished successfully. Initiating self-restart...")
        asyncio.create_task(self_terminate())
        
    except Exception as e:
        logging.error(f"Execute update failed: {e}")
        raise e


async def self_terminate():
    """Мягкое завершение процесса."""
    await asyncio.sleep(1)
    os.kill(os.getpid(), signal.SIGTERM)


async def auto_update_checker(bot: Bot):
    """Фоновая задача для проверки обновлений."""
    global LAST_NOTIFIED_VERSION
    await asyncio.sleep(60)

    while True:
        try:
            local_v, remote_v, branch, available = await get_update_info()

            if available and remote_v != LAST_NOTIFIED_VERSION:
                branch = validate_branch_name(branch)
                code, out, err = await run_command(f"git log HEAD..origin/{branch} --pretty=format:'%%h - %%s' -n 5")
                changes_log = out if code == 0 else "Minor fixes"
                
                warning = _("bot_update_docker_warning", config.DEFAULT_LANGUAGE) if DEPLOY_MODE == "docker" else ""
                
                await send_alert(
                    bot, 
                    lambda lang: _("bot_update_available", lang, local=local_v, remote=remote_v, log=escape_html(changes_log)) + warning,
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
    """Обновление системных пакетов (apt)."""
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
    
    # Теперь _ это функция перевода, и она не перекрывается локальной переменной
    await callback.message.edit_text(_("bot_update_checking", lang), parse_mode="HTML")

    try:
        local_v, remote_v, branch, available = await get_update_info()
        
        if available:
            branch = validate_branch_name(branch)
            # Переменная ошибки переименована в err
            code, out, err = await run_command(f"git log HEAD..origin/{branch} --pretty=format:'%%h - %%s' -n 5")
            changes_log = out if code == 0 else "Details on GitHub"
            
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