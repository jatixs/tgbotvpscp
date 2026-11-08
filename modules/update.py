import asyncio
import logging
import os
import re
import signal
import sys

import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton

from core import config, node_updates, shared_state, utils
from core.auth import is_allowed, send_access_denied_message
from core.config import DEPLOY_MODE, RESTART_FLAG_FILE
from core.i18n import I18nFilter, _, get_user_lang
from core.messaging import delete_previous_message, send_alert
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import AuditEvent, escape_html, log_audit_event

BUTTON_KEY = "btn_update"
CHECK_INTERVAL = 21600
LAST_NOTIFIED_VERSION = None
README_VERSION = re.compile(r"img\.shields\.io/badge/version-v([\d.]+)")


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(update_menu_handler)
    dp.callback_query(F.data == "update_system_apt")(confirm_system_update)
    dp.callback_query(F.data == "confirm_system_update")(run_system_update)
    dp.callback_query(F.data == "check_bot_update")(check_bot_update)
    dp.callback_query(F.data.startswith("do_bot_update"))(run_bot_update)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    return [asyncio.create_task(auto_update_checker(bot), name="AutoUpdateChecker")]


def validate_branch_name(branch: str) -> str:
    branch = (branch or "").strip()
    if not node_updates.BRANCH.fullmatch(branch):
        return "main"
    return branch


async def run_command(*args):
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return (proc.returncode, stdout.decode().strip(), stderr.decode().strip())
    except Exception as e:
        return (-1, "", str(e))


async def get_current_branch():
    code, out, err = await run_command("git", "rev-parse", "--abbrev-ref", "HEAD")
    if code == 0 and out:
        return out.strip()
    return "main"


def compare_versions(ver1, ver2):

    def normalize(v):
        v = v.lower().lstrip("v")
        return [int(x) for x in v.split(".") if x.isdigit()]

    try:
        v1_parts = normalize(ver1)
        v2_parts = normalize(ver2)
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1_val = v1_parts[i] if i < len(v1_parts) else 0
            v2_val = v2_parts[i] if i < len(v2_parts) else 0
            if v1_val > v2_val:
                return 1
            if v1_val < v2_val:
                return -1
        return 0
    except Exception:
        return 0


async def get_remote_version_github(branch="main"):
    url = f"https://raw.githubusercontent.com/jatixs/tgbotvpscp/{branch}/README.md"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    text = await response.text()
                    match = README_VERSION.search(text)
                    if match:
                        return f"v{match.group(1)}"
    except Exception as e:
        logging.error(f"Error checking remote version from GitHub: {e}")
    return None


async def get_changelog_entry(branch: str, lang: str) -> str:
    filename = "docs/CHANGELOG.en.md" if lang == "en" else "docs/CHANGELOG.md"
    code, out, err = await run_command("git", "show", f"origin/{branch}:{filename}")
    if code != 0 or not out:
        url = f"https://raw.githubusercontent.com/jatixs/tgbotvpscp/{branch}/{filename}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        out = await response.text()
                    else:
                        return "Changelog not found."
        except Exception:
            return "Changelog not available."
    lines = out.splitlines()
    result = []
    found_start = False
    for line in lines:
        if re.match("^## \\[\\d+\\.\\d+\\.\\d+\\]", line):
            if found_start:
                break
            else:
                found_start = True
                result.append(line)
        elif found_start:
            result.append(line)
    if not result:
        return "No release notes found."
    notes = "\n".join(result).strip()
    return notes if len(notes) <= 3000 else notes[:2999] + "…"


async def get_update_info():
    try:
        branch = await get_current_branch()
        branch = validate_branch_name(branch)
        local_ver = utils.get_app_version()
        code, readme, _ = await run_command("git", "show", "HEAD:README.md")
        if code == 0 and (match := README_VERSION.search(readme)):
            local_ver = f"v{match.group(1)}"
        await run_command("git", "fetch", "origin")
        remote_ver = await get_remote_version_github(branch)
        if not remote_ver:
            code, out, _ = await run_command("git", "rev-parse", f"origin/{branch}")
            if code == 0:
                remote_ver = out.strip()[:7]
            else:
                remote_ver = "Unknown"
        update_available = False
        if remote_ver != "Unknown":
            if compare_versions(remote_ver, local_ver) > 0:
                update_available = True
            else:
                update_available = False
        return (local_ver, remote_ver, branch, update_available)
    except Exception as e:
        logging.error(f"Error getting update info: {e}")
        return ("Error", "Error", "main", False)


async def execute_bot_update(
    branch: str,
    restart_source: str = "unknown",
    *,
    node_ids: tuple[int, ...] = (),
    user_id: int = config.ADMIN_USER_ID,
) -> int:
    if node_ids and user_id != config.ADMIN_USER_ID:
        raise PermissionError("Only the main administrator can update node clients")
    if node_updates.agent_update_lock.locked() or shared_state.IS_RESTARTING:
        raise RuntimeError("An agent update or restart is already in progress")
    async with node_updates.agent_update_lock:
        branch = validate_branch_name(branch)
        logging.info(f"Starting bot update on branch '{branch}'...")
        # Audit logging
        log_audit_event(
            AuditEvent.SYSTEM_UPDATE_STARTED,
            user_id,
            details={"branch": branch, "source": restart_source, "confirmed_node_ids": node_ids},
            severity="CRITICAL"
        )

        # Pre-update integrity check & automatic backup of modified files
        try:
            from core.integrity import backup_modified_files
            success, backup_dir, backed_up = backup_modified_files(repo_root=config.BASE_DIR, branch=branch)
            if backed_up:
                logging.info(f"Created pre-update backup of {len(backed_up)} modified files in {backup_dir}")
        except Exception as be:
            logging.warning(f"Pre-update backup warning: {be}")

        code, _, err = await run_command("git", "fetch", "origin")
        if code != 0:
            raise RuntimeError(f"Git fetch failed: {err}")
        code, commit, err = await run_command("git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}")
        if code != 0 or not node_updates.COMMIT.fullmatch(commit):
            raise RuntimeError(f"Could not resolve the update revision: {err}")
        previous_commit = await node_updates.read_agent_commit()
        code, _, err = await run_command("git", "reset", "--hard", commit)
        if code != 0:
            raise RuntimeError(f"Git reset failed: {err}")
        code, _, err = await run_command(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        )
        if code != 0:
            if previous_commit:
                rollback, _, rollback_error = await run_command("git", "reset", "--hard", previous_commit)
                if rollback != 0:
                    logging.error("Could not restore the agent revision: %s", rollback_error)
            raise RuntimeError(f"Dependency installation failed: {err}")
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        with open(RESTART_FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(restart_source)
        shared_state.IS_RESTARTING = True
        queued = 0
        try:
            if node_ids:
                code, _, _ = await run_command("git", "cat-file", "-e", f"{commit}:node/software_update.py")
                if code == 0:
                    queued = await node_updates.queue_updates(node_ids, branch, commit, user_id)
        except Exception:
            logging.exception("Could not queue the confirmed node updates")
        finally:
            logging.info("Update finished. Restarting...")
            asyncio.create_task(self_terminate())
        return queued


async def self_terminate():
    shared_state.IS_RESTARTING = True
    await asyncio.sleep(5)
    os.kill(os.getpid(), signal.SIGTERM)


async def auto_update_checker(bot: Bot):
    global LAST_NOTIFIED_VERSION
    await asyncio.sleep(60)
    while True:
        try:
            local_v, remote_v, branch, available = await get_update_info()
            if available and remote_v != LAST_NOTIFIED_VERSION:
                branch = validate_branch_name(branch)
                log_ru = await get_changelog_entry(branch, "ru")
                log_en = await get_changelog_entry(branch, "en")

                def get_log_for_lang(l):
                    return log_en if l == "en" else log_ru

                warning = (
                    _("bot_update_docker_warning", config.DEFAULT_LANGUAGE)
                    if DEPLOY_MODE == "docker"
                    else ""
                )
                await send_alert(
                    bot,
                    lambda lang: _(
                        "bot_update_available",
                        lang,
                        local=local_v,
                        remote=remote_v,
                        log=escape_html(get_log_for_lang(lang)),
                    )
                    + warning,
                    "update",
                )
                LAST_NOTIFIED_VERSION = remote_v
        except Exception as e:
            logging.error(f"AutoUpdateChecker failed: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def update_menu_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "update"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id, message.bot)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("btn_check_bot_update", lang),
                    callback_data="check_bot_update",
                ),
                InlineKeyboardButton(
                    text=_("btn_update_system", lang), callback_data="update_system_apt"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_("btn_cancel", lang), callback_data="back_to_menu", style="danger"
                )
            ],
        ]
    )
    sent_message = await message.answer(
        _("update_select_action", lang), reply_markup=keyboard, parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def confirm_system_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "update"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("btn_confirm_update", lang),
                    callback_data="confirm_system_update",
                    style="success"
                )
            ],
            [
                InlineKeyboardButton(
                    text=_("btn_cancel", lang), callback_data="back_to_menu", style="danger"
                )
            ],
        ]
    )
    await callback.message.edit_text(
        _("update_confirm", lang), reply_markup=keyboard, parse_mode="HTML"
    )


async def run_system_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "update"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    await callback.message.edit_text(_("update_start", lang), parse_mode="HTML")

    if DEPLOY_MODE == "docker":
        base_cmd = "DEBIAN_FRONTEND=noninteractive apt update && DEBIAN_FRONTEND=noninteractive apt upgrade -y && apt autoremove -y"
        cmd_args = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "bash", "-c", base_cmd]
    else:
        script_path = "/opt/tg-bot/scripts/update_os.sh"
        if os.path.isfile(script_path):
            base_cmd = f"sudo {script_path}"
            cmd_args = ["bash", "-c", base_cmd]
        else:
            base_cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y && sudo apt clean"
            cmd_args = ["bash", "-c", base_cmd]

    code, out, err = await run_command(*cmd_args)
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
    if not is_allowed(user_id, "update"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    await callback.message.edit_text(_("bot_update_checking", lang), parse_mode="HTML")
    try:
        local_v, remote_v, branch, available = await get_update_info()
        if available:
            branch = validate_branch_name(branch)
            changes_log = await get_changelog_entry(branch, lang)
            warning = (
                _("bot_update_docker_warning", lang) if DEPLOY_MODE == "docker" else ""
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=_("btn_update_bot_now", lang),
                            callback_data=f"do_bot_update:{branch}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=_("btn_cancel", lang), callback_data="back_to_menu"
                        )
                    ],
                ]
            )
            await callback.message.edit_text(
                _(
                    "bot_update_available",
                    lang,
                    local=local_v,
                    remote=remote_v,
                    log=escape_html(changes_log),
                )
                + warning,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                _("bot_update_up_to_date", lang, hash=local_v),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=_("btn_back", lang), callback_data="back_to_menu", style="primary"
                            )
                        ]
                    ]
                ),
                parse_mode="HTML",
            )
    except Exception as e:
        logging.error(f"Update check error: {e}", exc_info=True)
        await callback.message.edit_text(f"Error checking updates: {e}")


async def run_bot_update(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "update"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    action, _separator, value = callback.data.partition(":")
    node_ids = ()
    if action in {"do_bot_update_agent", "do_bot_update_nodes"}:
        plan = node_updates.consume(value, user_id)
        if not plan:
            await callback.answer(_("node_client_update_plan_expired", lang), show_alert=True)
            return
        branch = plan.branch
        if action == "do_bot_update_nodes":
            node_ids = plan.nodes
    elif action == "do_bot_update":
        branch = validate_branch_name(value)
        plan = await node_updates.prepare(user_id, branch)
        if plan["nodes"]:
            names = [f"• #{node['id']} {escape_html(node['name'][:100])}" for node in plan["nodes"]]
            listing = "\n".join(names)
            if len(listing) > 3200:
                for start in range(0, len(names), 15):
                    await callback.message.answer("\n".join(names[start:start + 15]), parse_mode="HTML")
                listing = _("node_client_update_list_above", lang, count=len(names))
            prompt = _("node_client_update_confirm", lang, nodes=listing)
            if plan["skipped"]:
                prompt += "\n\n" + _("node_client_update_skipped", lang, count=plan["skipped"])
            token = plan["token"]
            await callback.message.edit_text(
                prompt,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=_("btn_update_agent_and_nodes", lang), callback_data=f"do_bot_update_nodes:{token}", style="success")],
                    [InlineKeyboardButton(text=_("btn_update_agent_only", lang), callback_data=f"do_bot_update_agent:{token}")],
                    [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu", style="danger")],
                ]),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        if plan["skipped"]:
            await callback.answer(_("node_client_update_skipped", lang, count=plan["skipped"]), show_alert=True)
    else:
        return

    chat_id = callback.message.chat.id
    await callback.message.edit_text(_("bot_update_start", lang), parse_mode="HTML")
    try:
        restart_token = f"{chat_id}:{callback.message.message_id}"
        queued = await execute_bot_update(
            branch, restart_source=restart_token, node_ids=node_ids, user_id=user_id,
        )
        message = _("bot_update_success", lang)
        if node_ids:
            message += "\n" + _("node_client_update_queued", lang, count=queued, total=len(node_ids))
        await callback.message.edit_text(message, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Update failed: {e}")
        await callback.message.edit_text(
            _("bot_update_fail", lang, error=escape_html(str(e)[-2000:])), parse_mode="HTML"
        )
