import asyncio
import logging
import psutil
import time
import re
import os
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import LAST_MESSAGE_IDS, ALERTS_CONFIG, RESOURCE_ALERT_STATE, LAST_RESOURCE_ALERT_TIME
from core.utils import save_alerts_config, get_country_flag, get_server_timezone_label, escape_html, get_host_path
from core.keyboards import get_alerts_menu_keyboard

BUTTON_KEY = "btn_notifications"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(notifications_menu_handler)
    dp.callback_query(F.data.startswith("toggle_alert_"))(cq_toggle_alert)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    tasks = [
        asyncio.create_task(
            resource_monitor(bot),
            name="ResourceMonitor")]

    ssh_log = None
    if os.path.exists(get_host_path("/var/log/secure")):
        ssh_log = get_host_path("/var/log/secure")
    elif os.path.exists(get_host_path("/var/log/auth.log")):
        ssh_log = get_host_path("/var/log/auth.log")

    if ssh_log:
        tasks.append(
            asyncio.create_task(
                reliable_tail_log_monitor(
                    bot,
                    ssh_log,
                    "logins",
                    parse_ssh_log_line),
                name="LoginsMonitor"))

    tasks.append(
        asyncio.create_task(
            reliable_tail_log_monitor(
                bot,
                get_host_path("/var/log/fail2ban.log"),
                "bans",
                parse_f2b_log_line),
            name="BansMonitor"))
    return tasks


async def notifications_menu_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "notifications_menu"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    sent = await message.answer(_("notifications_menu_title", lang), reply_markup=get_alerts_menu_keyboard(user_id), parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent.message_id


async def cq_toggle_alert(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "toggle_alert_resources"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    alert_type = callback.data.split('_', 2)[-1]
    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}
    new_state = not ALERTS_CONFIG[user_id].get(alert_type, False)
    ALERTS_CONFIG[user_id][alert_type] = new_state
    save_alerts_config()

    await callback.message.edit_reply_markup(reply_markup=get_alerts_menu_keyboard(user_id))

    map_name = {
        "resources": "notifications_alert_name_res",
        "logins": "notifications_alert_name_logins",
        "bans": "notifications_alert_name_bans",
        "downtime": "notifications_alert_name_downtime"}
    name = _(map_name.get(alert_type, "error"), lang)
    status = _(
        "notifications_status_on",
        lang) if new_state else _(
        "notifications_status_off",
        lang)
    await callback.answer(_("notifications_toggle_alert", lang, alert_name=name, status=status))


async def parse_ssh_log_line(line: str) -> dict | None:
    match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
    if match:
        try:
            user = escape_html(match.group(1))
            ip = escape_html(match.group(2))
            flag = await get_country_flag(ip)
            return {
                "key": "alert_ssh_login_detected",
                "params": {
                    "user": user,
                    "flag": flag,
                    "ip": ip,
                    "time": datetime.now().strftime('%H:%M:%S'),
                    "tz": get_server_timezone_label()}}
        except BaseException:
            return None
    return None


async def parse_f2b_log_line(line: str) -> dict | None:
    match = re.search(r"fail2ban\.actions.* Ban\s+(\S+)", line)
    if match:
        try:
            ip = escape_html(match.group(1).strip())
            flag = await get_country_flag(ip)
            return {
                "key": "alert_f2b_ban_detected",
                "params": {
                    "flag": flag,
                    "ip": ip,
                    "time": datetime.now().strftime('%H:%M:%S'),
                    "tz": get_server_timezone_label()}}
        except BaseException:
            return None
    return None


async def resource_monitor(bot: Bot):
    global RESOURCE_ALERT_STATE, LAST_RESOURCE_ALERT_TIME
    await asyncio.sleep(15)
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            try:
                disk = psutil.disk_usage(get_host_path('/')).percent
            except BaseException:
                disk = 0

            alerts = []
            now = time.time()

            def check(metric, val, thresh, key_high, key_rep, key_norm):
                if val >= thresh:
                    if not RESOURCE_ALERT_STATE[metric]:
                        alerts.append(
                            (key_high, {"usage": val, "threshold": thresh}))
                        RESOURCE_ALERT_STATE[metric] = True
                        LAST_RESOURCE_ALERT_TIME[metric] = now
                    elif now - LAST_RESOURCE_ALERT_TIME[metric] > config.RESOURCE_ALERT_COOLDOWN:
                        alerts.append(
                            (key_rep, {"usage": val, "threshold": thresh}))
                        LAST_RESOURCE_ALERT_TIME[metric] = now
                elif val < thresh and RESOURCE_ALERT_STATE[metric]:
                    alerts.append((key_norm, {"usage": val}))
                    RESOURCE_ALERT_STATE[metric] = False
                    LAST_RESOURCE_ALERT_TIME[metric] = 0

            check(
                "cpu",
                cpu,
                config.CPU_THRESHOLD,
                "alert_cpu_high",
                "alert_cpu_high_repeat",
                "alert_cpu_normal")
            check(
                "ram",
                ram,
                config.RAM_THRESHOLD,
                "alert_ram_high",
                "alert_ram_high_repeat",
                "alert_ram_normal")
            check(
                "disk",
                disk,
                config.DISK_THRESHOLD,
                "alert_disk_high",
                "alert_disk_high_repeat",
                "alert_disk_normal")

            if alerts:
                await send_alert(bot, lambda lang: "\n\n".join([_(k, lang, **p) for k, p in alerts]), "resources")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"ResMonitor error: {e}")
        await asyncio.sleep(config.RESOURCE_CHECK_INTERVAL)


async def reliable_tail_log_monitor(bot, path, alert_type, parser):
    while True:
        if not os.path.exists(path):
            await asyncio.sleep(60)
            continue

        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                f"tail -n 0 -f {path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            async for line in proc.stdout:
                l = line.decode('utf-8', 'ignore').strip()
                if l:
                    data = await parser(l)
                    if data:
                        await send_alert(bot, lambda lang: _(data["key"], lang, **data["params"]), alert_type)

        except asyncio.CancelledError:
            # ВАЖНО: При отмене задачи убиваем процесс tail
            if proc:
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception:
                    pass
            raise

        except Exception as e:
            logging.error(f"Tail monitor error ({path}): {e}")
            if proc:
                try:
                    proc.terminate()
                except BaseException:
                    pass
            await asyncio.sleep(10)
