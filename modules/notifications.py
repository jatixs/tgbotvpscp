import asyncio
import logging
import psutil
import time
import re
import os
import signal
import aiohttp
import html
from datetime import datetime, timedelta, timezone
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core import nodes_db
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import (
    LAST_MESSAGE_IDS,
    ALERTS_CONFIG,
    RESOURCE_ALERT_STATE,
    LAST_RESOURCE_ALERT_TIME,
)
from core.utils import (
    save_alerts_config,
    get_server_timezone_label,
    escape_html,
    get_host_path,
)
from core.keyboards import (
    get_notifications_start_keyboard,
    get_notifications_global_keyboard,
    get_notifications_nodes_list_keyboard,
    get_notifications_node_settings_keyboard,
)

BUTTON_KEY = "btn_notifications"
RECENT_NOTIFIED_LOGINS = {}


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(notifications_menu_handler)
    dp.callback_query(F.data == "back_to_notif_menu")(cq_back_to_notif_menu)
    dp.callback_query(F.data == "notif_menu_global")(cq_notif_menu_global)
    dp.callback_query(F.data == "notif_menu_nodes_list")(cq_notif_menu_nodes_list)
    dp.callback_query(F.data.startswith("notif_select_node_"))(cq_notif_select_node)
    dp.callback_query(F.data.startswith("toggle_alert_"))(cq_toggle_alert)
    dp.callback_query(F.data.startswith("toggle_node_"))(cq_toggle_node_alert)
    dp.callback_query(F.data == "toggle_all_agent")(cq_toggle_all_agent)
    dp.callback_query(F.data == "toggle_all_nodes")(cq_toggle_all_nodes)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    tasks = [asyncio.create_task(resource_monitor(bot), name="ResourceMonitor")]
    ssh_cmd = "journalctl -n 0 -f -o cat _COMM=sshd"
    tasks.append(
        asyncio.create_task(
            reliable_command_monitor(bot, ssh_cmd, "logins", parse_ssh_log_line),
            name="LoginsMonitor_Journal",
        )
    )

    ssh_log = None
    if os.path.exists(get_host_path("/var/log/secure")):
        ssh_log = get_host_path("/var/log/secure")
    elif os.path.exists(get_host_path("/var/log/auth.log")):
        ssh_log = get_host_path("/var/log/auth.log")

    if ssh_log:
        tasks.append(
            asyncio.create_task(
                reliable_tail_log_monitor(bot, ssh_log, "logins", parse_ssh_log_line),
                name="LoginsMonitor_File",
            )
        )

    tasks.append(
        asyncio.create_task(
            reliable_tail_log_monitor(
                bot, get_host_path("/var/log/fail2ban.log"), "bans", parse_f2b_log_line
            ),
            name="BansMonitor",
        )
    )
    return tasks


def get_top_processes_info(metric: str) -> str:
    try:
        attrs = ["pid", "name", "cpu_percent", "memory_percent"]
        procs = []
        for p in psutil.process_iter(attrs):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        info_list = []
        if metric == "cpu":
            sorted_procs = sorted(
                procs, key=lambda p: p["cpu_percent"], reverse=True
            )[:5]
            for p in sorted_procs:
                info_list.append(f"• <b>{p['name']}</b>: {p['cpu_percent']}%")
        elif metric == "ram":
            sorted_procs = sorted(
                procs, key=lambda p: p["memory_percent"], reverse=True
            )[:5]
            for p in sorted_procs:
                info_list.append(f"• <b>{p['name']}</b>: {p['memory_percent']:.1f}%")
        else:
            return ""
        return "\n".join(info_list)
    except Exception as e:
        logging.error(f"Error getting top processes: {e}")
        return "n/a"


async def notifications_menu_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "notifications_menu"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    
    # Use new Start Menu (Global / Nodes)
    sent = await message.answer(
        _("notif_menu_title", lang),
        reply_markup=get_notifications_start_keyboard(user_id),
        parse_mode="HTML",
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent.message_id


async def cq_back_to_notif_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    await callback.message.edit_text(
        _("notif_menu_title", lang),
        reply_markup=get_notifications_start_keyboard(user_id),
        parse_mode="HTML"
    )
    await callback.answer()


async def cq_notif_menu_global(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    await callback.message.edit_text(
        _("notif_global_title", lang),
        reply_markup=get_notifications_global_keyboard(user_id),
        parse_mode="HTML"
    )
    await callback.answer()


async def cq_notif_menu_nodes_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    nodes = await nodes_db.get_all_nodes()
    await callback.message.edit_text(
        _("notif_nodes_list_title", lang),
        reply_markup=get_notifications_nodes_list_keyboard(nodes, lang),
        parse_mode="HTML"
    )
    await callback.answer()


async def cq_notif_select_node(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.replace("notif_select_node_", "")
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    node_name = html.escape(node.get("name", "Unknown"))
    await callback.message.edit_text(
        _("notif_node_settings_title", lang, name=node_name),
        reply_markup=get_notifications_node_settings_keyboard(token, node_name, user_id),
        parse_mode="HTML"
    )
    await callback.answer()


async def cq_toggle_all_agent(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}
    
    agent_keys = ["resources", "logins", "bans"]
    
    # Check if all are enabled
    all_enabled = all(ALERTS_CONFIG[user_id].get(k, False) for k in agent_keys)
    new_state = not all_enabled # If all on -> turn off. If any off -> turn all on.
    
    for k in agent_keys:
        ALERTS_CONFIG[user_id][k] = new_state
        
    save_alerts_config()
    
    await callback.message.edit_reply_markup(
        reply_markup=get_notifications_global_keyboard(user_id)
    )
    
    status_text = _("notifications_status_on", lang) if new_state else _("notifications_status_off", lang)
    await callback.answer(_("notif_all_agent_switched", lang, status=status_text))


async def cq_toggle_all_nodes(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}
        
    node_keys = ["downtime", "node_resources", "node_logins"]
    
    all_enabled = all(ALERTS_CONFIG[user_id].get(k, False) for k in node_keys)
    new_state = not all_enabled
    
    for k in node_keys:
        ALERTS_CONFIG[user_id][k] = new_state
        
    save_alerts_config()
    
    await callback.message.edit_reply_markup(
        reply_markup=get_notifications_global_keyboard(user_id)
    )
    
    status_text = _("notifications_status_on", lang) if new_state else _("notifications_status_off", lang)
    await callback.answer(_("notif_all_nodes_switched", lang, status=status_text))


async def cq_toggle_alert(callback: types.CallbackQuery):
    """Toggles Global Settings"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(user_id, "toggle_alert_resources"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return
    
    alert_type = callback.data.replace("toggle_alert_", "")
    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}
        
    # Toggle logic
    new_state = not ALERTS_CONFIG[user_id].get(alert_type, False)
    ALERTS_CONFIG[user_id][alert_type] = new_state
    save_alerts_config()
    
    # Refresh Global Menu
    await callback.message.edit_reply_markup(
        reply_markup=get_notifications_global_keyboard(user_id)
    )
    
    map_name = {
        "resources": "notifications_alert_name_res",
        "logins": "notifications_alert_name_logins",
        "bans": "notifications_alert_name_bans",
        "downtime": "notifications_alert_name_downtime",
        "node_resources": "notifications_alert_name_res",
        "node_logins": "notifications_alert_name_logins",
    }
    name = _(map_name.get(alert_type, alert_type), lang)
    status = (
        _("notifications_status_on", lang)
        if new_state
        else _("notifications_status_off", lang)
    )
    await callback.answer(
        _("notifications_toggle_alert", lang, alert_name=name, status=status)
    )


async def cq_toggle_node_alert(callback: types.CallbackQuery):
    """Toggles Specific Node Override"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Format: toggle_node_{token}_{type}
    data = callback.data.replace("toggle_node_", "")
    
    if "_downtime" in data:
        token = data.replace("_downtime", "")
        alert_type = "downtime"
    elif "_node_resources" in data:
        token = data.replace("_node_resources", "")
        alert_type = "node_resources"
    elif "_node_logins" in data:
        token = data.replace("_node_logins", "")
        alert_type = "node_logins"
    else:
        # Fallback
        token, alert_type = data.split("_", 1)
        
    node = await nodes_db.get_node_by_token(token)
    node_name = html.escape(node.get("name", "Unknown")) if node else "Unknown"

    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}

    user_conf = ALERTS_CONFIG[user_id]
    
    override_key = f"node_{token}_{alert_type}"
    
    # Current effective state
    global_key = alert_type
    global_val = user_conf.get(global_key, False)
    
    # Logic: 
    # If override exists: toggle it.
    # If not exists: create override that is INVERSE of global (to effective toggle)
    # Actually simpler: UI shows current effective. User wants to Toggle.
    
    current_val = global_val
    if override_key in user_conf:
        current_val = user_conf[override_key]
        
    new_val = not current_val
    user_conf[override_key] = new_val
    
    save_alerts_config()
    
    await callback.message.edit_reply_markup(
        reply_markup=get_notifications_node_settings_keyboard(token, node_name, user_id)
    )
    
    await callback.answer(
        _("notif_override_on", lang, name=node_name)
    )


async def get_ip_data(ip: str):
    """
    Получает флаг страны и смещение часового пояса (в секундах) для IP.
    """
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠", None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{ip}?fields=status,countryCode,offset",
                timeout=2,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        country_code = data.get("countryCode")
                        flag = "❓"
                        if country_code and len(country_code) == 2:
                            flag = "".join(
                                (
                                    chr(ord(char.upper()) - 65 + 127462)
                                    for char in country_code
                                )
                            )
                        offset = data.get("offset")
                        return flag, offset
    except Exception as e:
        logging.warning(f"Error getting IP data for {ip}: {e}")
    
    return "❓", None


async def parse_ssh_log_line(line: str) -> dict | None:
    now = time.time()
    sshd_match = re.search(r"Accepted\s+(\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)

    user, ip, method_key = None, None, "auth_method_unknown"

    if sshd_match:
        method_raw = sshd_match.group(1).lower()
        user = escape_html(sshd_match.group(2))
        ip = escape_html(sshd_match.group(3))
        if "publickey" in method_raw:
            method_key = "auth_method_key"
        elif "password" in method_raw:
            method_key = "auth_method_password"

    if user and ip:
        last_time = RECENT_NOTIFIED_LOGINS.get((user, ip), 0)
        if now - last_time < 10:
            return None

        RECENT_NOTIFIED_LOGINS[(user, ip)] = now

        if len(RECENT_NOTIFIED_LOGINS) > 100:
            RECENT_NOTIFIED_LOGINS.clear()

        try:
            flag, offset = await get_ip_data(ip)
            s_now = datetime.now()
            s_tz_label = get_server_timezone_label() 
            
            time_str = f"{s_now.strftime('%H:%M:%S')}{s_tz_label}"         
            if offset is not None:
                try:
                    utc_now = datetime.now(timezone.utc)
                    ip_dt = utc_now + timedelta(seconds=offset)
                    
                    off_h = int(offset / 3600)
                    sign = "+" if off_h >= 0 else ""
                    ip_tz_label = f"GMT{sign}{off_h}"
                    
                    time_str += f" / 📍 {ip_dt.strftime('%H:%M')} ({ip_tz_label})"
                except Exception:
                    pass

            return {
                "key": "alert_ssh_login_detected",
                "params": {
                    "user": user,
                    "flag": flag,
                    "ip": ip,
                    "time": time_str,
                    "tz": "",  
                    "method_key": method_key,
                },
            }
        except Exception as e:
            logging.debug(f"SSH log parse error: {e}")
            return None
    return None


async def parse_f2b_log_line(line: str) -> dict | None:
    match = re.search("fail2ban\\.actions.* Ban\\s+(\\S+)", line)
    if match:
        try:
            ip = escape_html(match.group(1).strip())            
            flag, offset = await get_ip_data(ip)            
            s_now = datetime.now()
            s_tz_label = get_server_timezone_label()
            time_str = f"⏰ Время: {s_now.strftime('%H:%M:%S')}{s_tz_label}"
            if offset is not None:
                try:
                    utc_now = datetime.now(timezone.utc)
                    ip_dt = utc_now + timedelta(seconds=offset)
                    
                    off_h = int(offset / 3600)
                    sign = "+" if off_h >= 0 else ""
                    ip_tz_label = f"GMT{sign}{off_h}"
                    
                    time_str += f" / 📍 {ip_dt.strftime('%H:%M')} ({ip_tz_label})"
                except Exception:
                    pass

            return {
                "key": "alert_f2b_ban_detected",
                "params": {
                    "flag": flag,
                    "ip": ip,
                    "time": time_str,
                    "tz": "",
                },
            }
        except Exception as e:
            logging.debug(f"F2B log parse error: {e}")
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
                disk = psutil.disk_usage(get_host_path("/")).percent
            except Exception as e:
                logging.debug(f"Disk usage check failed: {e}")
                disk = 0
            alerts = []
            now = time.time()

            def check(metric, val, thresh, key_high, key_rep, key_norm):
                if val >= thresh:
                    proc_info = ""
                    if metric in ["cpu", "ram"]:
                        proc_info = get_top_processes_info(metric)
                    if not RESOURCE_ALERT_STATE[metric]:
                        alerts.append(
                            (
                                key_high,
                                {
                                    "usage": val,
                                    "threshold": thresh,
                                    "processes": proc_info,
                                },
                            )
                        )
                        RESOURCE_ALERT_STATE[metric] = True
                        LAST_RESOURCE_ALERT_TIME[metric] = now
                    elif (
                        now - LAST_RESOURCE_ALERT_TIME[metric]
                        > config.RESOURCE_ALERT_COOLDOWN
                    ):
                        alerts.append(
                            (
                                key_rep,
                                {
                                    "usage": val,
                                    "threshold": thresh,
                                    "processes": proc_info,
                                },
                            )
                        )
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
                "alert_cpu_normal",
            )
            check(
                "ram",
                ram,
                config.RAM_THRESHOLD,
                "alert_ram_high",
                "alert_ram_high_repeat",
                "alert_ram_normal",
            )
            if disk >= config.DISK_THRESHOLD:
                if not RESOURCE_ALERT_STATE["disk"]:
                    alerts.append(
                        (
                            "alert_disk_high",
                            {
                                "usage": disk,
                                "threshold": config.DISK_THRESHOLD,
                                "processes": "",
                            },
                        )
                    )
                    RESOURCE_ALERT_STATE["disk"] = True
                    LAST_RESOURCE_ALERT_TIME["disk"] = now
                elif (
                    now - LAST_RESOURCE_ALERT_TIME["disk"]
                    > config.RESOURCE_ALERT_COOLDOWN
                ):
                    alerts.append(
                        (
                            "alert_disk_high_repeat",
                            {
                                "usage": disk,
                                "threshold": config.DISK_THRESHOLD,
                                "processes": "",
                            },
                        )
                    )
                    LAST_RESOURCE_ALERT_TIME["disk"] = now
            elif disk < config.DISK_THRESHOLD and RESOURCE_ALERT_STATE["disk"]:
                alerts.append(("alert_disk_normal", {"usage": disk}))
                RESOURCE_ALERT_STATE["disk"] = False
                LAST_RESOURCE_ALERT_TIME["disk"] = 0
            if alerts:
                # Агентские ресурсы (Agent)
                await send_alert(
                    bot,
                    lambda lang: "\n\n".join([_(k, lang, **p) for k, p in alerts]),
                    "resources",
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"ResMonitor error: {e}")
        await asyncio.sleep(config.RESOURCE_CHECK_INTERVAL)


async def reliable_command_monitor(bot, cmd, alert_type, parser):
    while True:
        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            async for line in proc.stdout:
                l = line.decode("utf-8", "ignore").strip()
                if l:
                    data = await parser(l)
                    if data:

                        def msg_gen(lang):
                            params = data["params"].copy()
                            if "method_key" in params:
                                m_key = params.pop("method_key")
                                params["method"] = _(m_key, lang)
                            if "method" not in params:
                                params["method"] = ""
                            return _(data["key"], lang, **params)

                        await send_alert(
                            bot,
                            msg_gen,
                            alert_type,
                        )
        except asyncio.CancelledError:
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception as e:
                    logging.error(f"Error killing process group: {e}")
            raise
        except Exception as e:
            logging.error(f"Command monitor error ({cmd}): {e}")
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    pass
            await asyncio.sleep(10)


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
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            async for line in proc.stdout:
                l = line.decode("utf-8", "ignore").strip()
                if l:
                    data = await parser(l)
                    if data:

                        def msg_gen(lang):
                            params = data["params"].copy()
                            if "method_key" in params:
                                m_key = params.pop("method_key")
                                params["method"] = _(m_key, lang)
                            if "method" not in params:
                                params["method"] = ""
                            return _(data["key"], lang, **params)

                        await send_alert(
                            bot,
                            msg_gen,
                            alert_type,
                        )
        except asyncio.CancelledError:
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception as e:
                    logging.error(f"Error killing tail process group: {e}")
            raise
        except Exception as e:
            logging.error(f"Tail monitor error ({path}): {e}")
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception as e_kill:
                    logging.debug(f"Failed to kill tail process in except: {e_kill}")
            await asyncio.sleep(10)