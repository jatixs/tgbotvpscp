import asyncio
import logging
import os
import sys
import re
from packaging import version
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
    dp.callback_query(F.data == "do_bot_update")(run_bot_update)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    return [
        asyncio.create_task(auto_update_checker(bot), name="AutoUpdateChecker")
    ]


def get_version_from_content(content: str) -> str | None:
    """Извлекает версию из текста CHANGELOG (первое совпадение ## [x.x.x])."""
    try:
        match = re.search(r"## \[(\d+\.\d+\.\d+)\]", content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def extract_changelog_section(content: str, ver: str) -> str:
    """Извлекает текст изменений для конкретной версии."""
    try:
        # Ищем начало секции ## [version]
        start_pattern = re.escape(f"## [{ver}]")
        start_match = re.search(start_pattern, content)

        if not start_match:
            return "Разработчик не предоставил пока что список изменений"

        start_pos = start_match.start()

        # Ищем следующую секцию (любую ## [x.x.x]) после текущей
        next_match = re.search(r"## \[\d+\.\d+\.\d+\]", content[start_match.end():])

        if next_match:
            end_pos = start_match.end() + next_match.start()
            section = content[start_pos:end_pos]
        else:
            # Если это последняя (самая старая) запись в файле
            section = content[start_pos:]

        return section.strip()
    except Exception:
        return "Разработчик не предоставил пока что список изменений"


async def get_update_info():
    """Возвращает информацию о версиях (local, remote, branch)."""
    try:
        # 1. Fetch origin
        await asyncio.create_subprocess_shell("git fetch origin")

        # 2. Local version
        local_ver_str = "0.0.0"
        if os.path.exists("CHANGELOG.md"):
            with open("CHANGELOG.md", "r", encoding="utf-8") as f:
                content = f.read()
                local_ver_str = get_version_from_content(content) or "0.0.0"

        # 3. Remote version (branches)
        proc_branches = await asyncio.create_subprocess_shell("git branch -r", stdout=asyncio.subprocess.PIPE)
        out_branches, dummy_ = await proc_branches.communicate()
        branches_list = out_branches.decode().strip().split('\n')

        latest_ver_str = local_ver_str
        target_branch = None

        release_pattern = re.compile(r"origin/release/(\d+\.\d+\.\d+)")
        found_versions = []
        for br in branches_list:
            br = br.strip()
            match = release_pattern.search(br)
            if match:
                v_str = match.group(1)
                found_versions.append((v_str, br))

        if found_versions:
            found_versions.sort(key=lambda x: version.parse(x[0]), reverse=True)
            latest_remote_ver_str = found_versions[0][0]
            latest_remote_branch = found_versions[0][1]

            if version.parse(latest_remote_ver_str) > version.parse(local_ver_str):
                latest_ver_str = latest_remote_ver_str
                target_branch = latest_remote_branch

        return local_ver_str, latest_ver_str, target_branch
    except Exception as e:
        logging.error(f"Error getting update info: {e}")
        return "0.0.0", "0.0.0", None


async def execute_bot_update(branch: str, restart_source: str = "unknown"):
    """
    Выполняет обновление бота (checkout, pull, pip, restart).
    restart_source: строка, которая будет записана в флаг рестарта.
    """
    try:
        logging.info(f"Starting bot update to branch {branch}...")
        
        # 1. Checkout
        checkout_cmd = f"git checkout {branch}"
        proc_co = await asyncio.create_subprocess_shell(checkout_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc_co.communicate()
        
        # 2. Pull
        pull_cmd = "git pull"
        proc = await asyncio.create_subprocess_shell(pull_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise Exception(f"Git Pull Failed: {stderr.decode()}")

        # 3. Dependencies
        pip_cmd = f"{sys.executable} -m pip install -r requirements.txt"
        proc_pip = await asyncio.create_subprocess_shell(pip_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc_pip.communicate()

        # 4. Restart Flag
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(restart_source)

        # 5. Restart Command
        restart_cmd = ""
        if DEPLOY_MODE == "docker":
            container_name = os.environ.get("TG_BOT_CONTAINER_NAME")
            if container_name:
                restart_cmd = f"docker restart {container_name}"
            else:
                restart_cmd = "kill 1" 
        else:
            restart_cmd = "sudo systemctl restart tg-bot.service"
            
        logging.info(f"Update finished. Restarting via: {restart_cmd}")
        asyncio.create_task(do_restart(restart_cmd))
        
    except Exception as e:
        logging.error(f"Execute update failed: {e}")
        raise e


async def do_restart(cmd):
    await asyncio.sleep(1)
    await asyncio.create_subprocess_shell(cmd)


async def auto_update_checker(bot: Bot):
    """Фоновая задача для проверки обновлений."""
    global LAST_NOTIFIED_VERSION
    logging.info("AutoUpdateChecker started.")
    await asyncio.sleep(60)

    while True:
        try:
            local_ver, remote_ver, target_branch = await get_update_info()

            if target_branch and (version.parse(remote_ver) > version.parse(local_ver)):
                if LAST_NOTIFIED_VERSION != remote_ver:
                    proc_cl = await asyncio.create_subprocess_shell(f"git show {target_branch}:CHANGELOG.md", stdout=asyncio.subprocess.PIPE)
                    out_cl, dummy_ = await proc_cl.communicate()
                    changes_text = extract_changelog_section(out_cl.decode('utf-8', errors='ignore'), remote_ver)
                    
                    warning = _("bot_update_docker_warning", config.DEFAULT_LANGUAGE) if DEPLOY_MODE == "docker" else ""
                    
                    await send_alert(
                        bot, 
                        lambda lang: _("bot_update_available", lang, local=f"v{local_ver}", remote=f"v{remote_ver}", log=escape_html(changes_text)) + warning,
                        "update" 
                    )
                    
                    LAST_NOTIFIED_VERSION = remote_ver
            
        except Exception as e:
            logging.error(f"AutoUpdateChecker iteration failed: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)


# --- TELEGRAM HANDLERS ---
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


async def check_bot_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    await callback.message.edit_text(_("bot_update_checking", lang), parse_mode="HTML")

    try:
        local_ver, remote_ver, target_branch = await get_update_info()
        
        if target_branch and local_ver != remote_ver:
            # Есть обновление!
            proc_cl = await asyncio.create_subprocess_shell(f"git show {target_branch}:CHANGELOG.md", stdout=asyncio.subprocess.PIPE)
            out_cl, dummy_ = await proc_cl.communicate()
            
            changes_text = extract_changelog_section(out_cl.decode('utf-8', errors='ignore'), remote_ver)
            warning = _("bot_update_docker_warning", lang) if DEPLOY_MODE == "docker" else ""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=_("btn_update_bot_now", lang), callback_data=f"do_bot_update:{target_branch.replace('origin/', '')}")],
                [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(
                _("bot_update_available", lang, local=f"v{local_ver}", remote=f"v{remote_ver}", log=escape_html(changes_text)) + warning,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        else:
            await callback.message.edit_text(
                _("bot_update_up_to_date", lang, hash=f"v{local_ver}"),
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
    target_branch = "main"
    if len(data_parts) > 1:
        target_branch = data_parts[1]
    
    await callback.message.edit_text(_("bot_update_start", lang), parse_mode="HTML")

    try:
        await execute_bot_update(target_branch, restart_source=f"{chat_id}:{callback.message.message_id}")
        await callback.message.edit_text(_("bot_update_success", lang), parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Update failed: {e}")
        await callback.message.edit_text(_("bot_update_fail", lang, error=str(e)), parse_mode="HTML")