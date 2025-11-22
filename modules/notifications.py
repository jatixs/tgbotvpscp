import asyncio
import logging
import psutil
import time
import re
import os
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import (
    LAST_MESSAGE_IDS,
    ALERTS_CONFIG,
    RESOURCE_ALERT_STATE,
    LAST_RESOURCE_ALERT_TIME)
from core.utils import (
    save_alerts_config,
    get_country_flag,
    get_server_timezone_label,
    escape_html,
    get_host_path)
from core.keyboards import get_alerts_menu_keyboard

BUTTON_KEY = "btn_notifications"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(notifications_menu_handler)
    dp.callback_query(F.data.startswith("toggle_alert_"))(cq_toggle_alert)

def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    task_resources = asyncio.create_task(
        resource_monitor(bot), name="ResourceMonitor")

    ssh_log_file_to_monitor = None
    secure_path = get_host_path("/var/log/secure")
    auth_path = get_host_path("/var/log/auth.log")

    if os.path.exists(secure_path):
        ssh_log_file_to_monitor = secure_path
    elif os.path.exists(auth_path):
        ssh_log_file_to_monitor = auth_path

    task_logins = None
    if ssh_log_file_to_monitor:
        task_logins = asyncio.create_task(
            reliable_tail_log_monitor(
                bot,
                ssh_log_file_to_monitor,
                "logins",
                parse_ssh_log_line), 
            name="LoginsMonitor")
    else:
        logging.warning("Не найден лог SSH. Мониторинг SSH (logins) не запущен.")

    f2b_log_file_to_monitor = get_host_path("/var/log/fail2ban.log")
    task_bans = asyncio.create_task(
        reliable_tail_log_monitor(
            bot,
            f2b_log_file_to_monitor,
            "bans",
            parse_f2b_log_line),
        name="BansMonitor")

    tasks = [task_resources, task_bans]
    if task_logins:
        tasks.append(task_logins)

    return tasks

async def notifications_menu_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "notifications_menu"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return

    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    keyboard = get_alerts_menu_keyboard(user_id)
    sent_message = await message.answer(
        _("notifications_menu_title", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_toggle_alert(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "toggle_alert_resources"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return

    try:
        alert_type = callback.data.split('_', 2)[-1]
        if alert_type not in ["resources", "logins", "bans", "downtime"]:
            raise ValueError(f"Неизвестный тип алерта: {alert_type}")
    except Exception as e:
        logging.error(f"Ошибка разбора callback_data: {e}")
        await callback.answer(_("error_internal", lang), show_alert=True)
        return

    if user_id not in ALERTS_CONFIG: ALERTS_CONFIG[user_id] = {}
    new_state = not ALERTS_CONFIG[user_id].get(alert_type, False)
    ALERTS_CONFIG[user_id][alert_type] = new_state
    save_alerts_config()

    logging.info(f"Пользователь {user_id} изменил '{alert_type}' на {new_state}")
    new_keyboard = get_alerts_menu_keyboard(user_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=new_keyboard)
        alert_name_map = {
            "resources": "notifications_alert_name_res",
            "logins": "notifications_alert_name_logins",
            "bans": "notifications_alert_name_bans",
            "downtime": "notifications_alert_name_downtime"
        }
        alert_name = _(alert_name_map.get(alert_type, "error_internal"), lang)
        status_text = _("notifications_status_on", lang) if new_state else _("notifications_status_off", lang)
        await callback.answer(_("notifications_toggle_alert", lang, alert_name=alert_name, status=status_text))
    except Exception:
        await callback.answer()

async def parse_ssh_log_line(line: str) -> dict | None:
    match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
    if match:
        try:
            user = escape_html(match.group(1))
            ip = escape_html(match.group(2))
            flag = await asyncio.to_thread(get_country_flag, ip)
            tz_label = get_server_timezone_label()
            now_time = datetime.now().strftime('%H:%M:%S')
            return {
                "key": "alert_ssh_login_detected",
                "params": {"user": user, "flag": flag, "ip": ip, "time": now_time, "tz": tz_label}
            }
        except Exception: return None
    return None

async def parse_f2b_log_line(line: str) -> dict | None:
    match = re.search(r"fail2ban\.actions.* Ban\s+(\S+)", line)
    if match:
        try:
            ip = escape_html(match.group(1).strip(" \n\t,"))
            flag = await asyncio.to_thread(get_country_flag, ip)
            tz_label = get_server_timezone_label()
            now_time = datetime.now().strftime('%H:%M:%S')
            return {
                "key": "alert_f2b_ban_detected",
                "params": {"flag": flag, "ip": ip, "time": now_time, "tz": tz_label}
            }
        except Exception: return None
    return None

async def resource_monitor(bot: Bot):
    global RESOURCE_ALERT_STATE, LAST_RESOURCE_ALERT_TIME
    logging.info("Монитор ресурсов запущен.")
    await asyncio.sleep(15)

    while True:
        try:
            def check_resources_sync():
                cpu = psutil.cpu_percent(interval=1)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage(get_host_path('/')).percent
                return cpu, ram, disk

            cpu_usage, ram_usage, disk_usage = await asyncio.to_thread(check_resources_sync)
            alerts_data = []
            current_time = time.time()

            if cpu_usage >= config.CPU_THRESHOLD:
                if not RESOURCE_ALERT_STATE["cpu"]:
                    alerts_data.append(("alert_cpu_high", {"usage": cpu_usage, "threshold": config.CPU_THRESHOLD}))
                    RESOURCE_ALERT_STATE["cpu"] = True
                    LAST_RESOURCE_ALERT_TIME["cpu"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["cpu"] > config.RESOURCE_ALERT_COOLDOWN:
                    alerts_data.append(("alert_cpu_high_repeat", {"usage": cpu_usage, "threshold": config.CPU_THRESHOLD}))
                    LAST_RESOURCE_ALERT_TIME["cpu"] = current_time
            elif cpu_usage < config.CPU_THRESHOLD and RESOURCE_ALERT_STATE["cpu"]:
                alerts_data.append(("alert_cpu_normal", {"usage": cpu_usage}))
                RESOURCE_ALERT_STATE["cpu"] = False
                LAST_RESOURCE_ALERT_TIME["cpu"] = 0

            if ram_usage >= config.RAM_THRESHOLD:
                if not RESOURCE_ALERT_STATE["ram"]:
                    alerts_data.append(("alert_ram_high", {"usage": ram_usage, "threshold": config.RAM_THRESHOLD}))
                    RESOURCE_ALERT_STATE["ram"] = True
                    LAST_RESOURCE_ALERT_TIME["ram"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["ram"] > config.RESOURCE_ALERT_COOLDOWN:
                    alerts_data.append(("alert_ram_high_repeat", {"usage": ram_usage, "threshold": config.RAM_THRESHOLD}))
                    LAST_RESOURCE_ALERT_TIME["ram"] = current_time
            elif ram_usage < config.RAM_THRESHOLD and RESOURCE_ALERT_STATE["ram"]:
                alerts_data.append(("alert_ram_normal", {"usage": ram_usage}))
                RESOURCE_ALERT_STATE["ram"] = False
                LAST_RESOURCE_ALERT_TIME["ram"] = 0

            if disk_usage >= config.DISK_THRESHOLD:
                if not RESOURCE_ALERT_STATE["disk"]:
                    alerts_data.append(("alert_disk_high", {"usage": disk_usage, "threshold": config.DISK_THRESHOLD}))
                    RESOURCE_ALERT_STATE["disk"] = True
                    LAST_RESOURCE_ALERT_TIME["disk"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["disk"] > config.RESOURCE_ALERT_COOLDOWN:
                    alerts_data.append(("alert_disk_high_repeat", {"usage": disk_usage, "threshold": config.DISK_THRESHOLD}))
                    LAST_RESOURCE_ALERT_TIME["disk"] = current_time
            elif disk_usage < config.DISK_THRESHOLD and RESOURCE_ALERT_STATE["disk"]:
                alerts_data.append(("alert_disk_normal", {"usage": disk_usage}))
                RESOURCE_ALERT_STATE["disk"] = False
                LAST_RESOURCE_ALERT_TIME["disk"] = 0

            if alerts_data:
                def alert_text_generator(lang):
                    return "\n\n".join([_(key, lang, **params) for key, params in alerts_data])
                await send_alert(bot, alert_text_generator, "resources")

        except Exception as e:
            logging.error(f"Ошибка в мониторе ресурсов: {e}")
        await asyncio.sleep(config.RESOURCE_CHECK_INTERVAL)

def prepare_log_alert_func(alert_data_dict):
    if not alert_data_dict: return None
    key = alert_data_dict.get("key")
    params = alert_data_dict.get("params", {})
    return lambda lang: _(key, lang, **params)

async def _read_stdout(process, alert_type, parse_function, close_event):
    try:
        async for line in process.stdout:
            try:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    alert_data = await parse_function(line_str)
                    if alert_data:
                        await send_alert(process.bot_ref, prepare_log_alert_func(alert_data), alert_type)
            except Exception: pass
    except Exception: pass
    finally: close_event.set()

async def _read_stderr(process, alert_type, close_event):
    try:
        async for line in process.stderr: pass
    except Exception: pass
    finally: close_event.set()

async def reliable_tail_log_monitor(bot: Bot, log_file_path: str, alert_type: str, parse_function: callable):
    process = None
    stdout_closed = asyncio.Event()
    stderr_closed = asyncio.Event()
    stdout_task = None
    stderr_task = None

    try:
        while True:
            stdout_closed.clear(); stderr_closed.clear()
            process = None; stdout_task = None; stderr_task = None

            if not await asyncio.to_thread(os.path.exists, log_file_path):
                await asyncio.sleep(60); continue

            try:
                process = await asyncio.create_subprocess_shell(
                    f"tail -n 0 -f {log_file_path}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                process.bot_ref = bot
                stdout_task = asyncio.create_task(_read_stdout(process, alert_type, parse_function, stdout_closed))
                stderr_task = asyncio.create_task(_read_stderr(process, alert_type, stderr_closed))

                await process.wait()
                try: await asyncio.wait_for(asyncio.gather(stdout_closed.wait(), stderr_closed.wait()), timeout=2.0)
                except asyncio.TimeoutError: pass

            except Exception: await asyncio.sleep(60)
            finally:
                if stdout_task: stdout_task.cancel()
                if stderr_task: stderr_task.cancel()
                if process and process.returncode is None:
                    try: process.terminate()
                    except: pass
                await asyncio.sleep(5)
    except asyncio.CancelledError: pass