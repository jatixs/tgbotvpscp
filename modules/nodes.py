import time
import asyncio
import logging
import html
import socket
import os
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import LAST_MESSAGE_IDS, NODE_TRAFFIC_MONITORS
from core import nodes_db
from core.keyboards import (
    get_nodes_list_keyboard,
    get_node_management_keyboard,
    get_nodes_delete_keyboard,
    get_back_keyboard,
)
from core.utils import format_uptime

BUTTON_KEY = "btn_nodes"


class AddNodeStates(StatesGroup):
    waiting_for_name = State()


class RenameNodeStates(StatesGroup):
    waiting_for_new_name = State()


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(nodes_handler)
    dp.callback_query(F.data == "nodes_list_refresh")(cq_nodes_list_refresh)
    dp.callback_query(F.data == "node_add_new")(cq_add_node_start)
    dp.message(StateFilter(AddNodeStates.waiting_for_name))(process_node_name)
    dp.callback_query(F.data == "node_delete_menu")(cq_node_delete_menu)
    dp.callback_query(F.data.startswith("node_delete_confirm_"))(cq_node_delete_confirm)
    dp.callback_query(F.data.startswith("node_select_"))(cq_node_select)
    dp.callback_query(F.data.startswith("node_rename_"))(cq_node_rename)
    dp.message(StateFilter(RenameNodeStates.waiting_for_new_name))(process_node_rename)
    dp.callback_query(F.data.startswith("node_stop_traffic_"))(cq_node_stop_traffic)
    dp.callback_query(F.data.startswith("node_cmd_"))(cq_node_command)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    task_monitor = asyncio.create_task(nodes_monitor(bot), name="NodesMonitor")
    task_traffic = asyncio.create_task(
        node_traffic_scheduler(bot), name="NodesTrafficScheduler"
    )
    return [task_monitor, task_traffic]


async def _prepare_nodes_data():
    result = {}
    now = time.time()
    nodes = await nodes_db.get_all_nodes()
    for token, node in nodes.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        if is_restarting:
            icon = "🔵"
        elif now - last_seen < config.NODE_OFFLINE_TIMEOUT:
            icon = "🟢"
        else:
            icon = "🔴"
        result[token] = {"name": node.get("name", "Unknown"), "status_icon": icon}
    return result


async def nodes_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "nodes"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    prepared_nodes = await _prepare_nodes_data()
    keyboard = get_nodes_list_keyboard(prepared_nodes, lang)
    sent_message = await message.answer(
        _("nodes_menu_header", lang), reply_markup=keyboard, parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def cq_nodes_list_refresh(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    prepared_nodes = await _prepare_nodes_data()
    keyboard = get_nodes_list_keyboard(prepared_nodes, lang)
    try:
        await callback.message.edit_text(
            _("nodes_menu_header", lang), reply_markup=keyboard, parse_mode="HTML"
        )
    except Exception as e:
        logging.debug(f"cq_nodes_list_refresh edit error: {e}")
    await callback.answer()


async def cq_node_select(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_", 2)[2]
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    now = time.time()
    last_seen = node.get("last_seen", 0)
    is_restarting = node.get("is_restarting", False)
    node_name = html.escape(node.get("name", "Unknown"))
    if is_restarting:
        await callback.answer(
            _("node_restarting_alert", lang, name=node_name), show_alert=True
        )
        return
    if now - last_seen >= config.NODE_OFFLINE_TIMEOUT:
        stats = node.get("stats", {})
        fmt_time = (
            datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S")
            if last_seen > 0
            else "Never"
        )
        text = _(
            "node_details_offline",
            lang,
            name=node_name,
            last_seen=fmt_time,
            ip=node.get("ip", "?"),
            cpu=stats.get("cpu", "?"),
            ram=stats.get("ram", "?"),
            disk=stats.get("disk", "?"),
        )
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard(lang, "nodes_list_refresh"),
            parse_mode="HTML",
        )
        return
    stats = node.get("stats", {})
    raw_uptime = stats.get("uptime", 0)
    formatted_uptime = format_uptime(raw_uptime, lang)
    text = _(
        "node_management_menu",
        lang,
        name=node_name,
        ip=node.get("ip", "?"),
        uptime=formatted_uptime,
    )
    keyboard = get_node_management_keyboard(token, lang, user_id)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def cq_add_node_start(callback: types.CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        "Введите имя новой ноды:",
        reply_markup=get_back_keyboard(lang, "nodes_list_refresh"),
    )
    await state.set_state(AddNodeStates.waiting_for_name)
    await callback.answer()


async def process_node_name(message: types.Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    name = message.text.strip()
    token = await nodes_db.create_node(name)

    configured_domain = os.environ.get("WEB_DOMAIN")
    host_address = None
    if configured_domain:
        host_address = configured_domain
    else:
        ext_ip = None
        try:
            proc = await asyncio.create_subprocess_shell(
                "curl -4 -s --max-time 2 ifconfig.me",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr_data = await proc.communicate()
            if stdout:
                ext_ip = stdout.decode().strip()
        except Exception as e:
            logging.error(f"Error detecting external IP: {e}")

        host_address = ext_ip
        if ext_ip:
            try:
                loop = asyncio.get_running_loop()
                hostname, aliases, ips = await loop.run_in_executor(None, socket.gethostbyaddr, ext_ip)
                if hostname:
                    host_address = hostname
            except Exception:
                pass

    if not host_address:
        host_address = "YOUR_SERVER_IP"

    protocol = "https" if (configured_domain and "https" in config.AGENT_BASE_URL if hasattr(config, 'AGENT_BASE_URL') else False) else "http"
    port_str = f":{config.WEB_SERVER_PORT}"
    if configured_domain and config.WEB_SERVER_PORT in [80, 443]:
         port_str = ""
         if config.WEB_SERVER_PORT == 443: protocol = "https"

    if configured_domain:  
         agent_url = f"https://{configured_domain}" 
    else:
         agent_url = f"http://{host_address}:{config.WEB_SERVER_PORT}"

    deploy_cmd = f"bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh) --agent={agent_url} --token={token}"
    safe_command = html.escape(deploy_cmd)

    await message.answer(
        _("node_add_success_token", lang, name=html.escape(name), token=token, command=safe_command),
        parse_mode="HTML",
    )
    await state.clear()


async def cq_node_rename(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("access_denied_no_rights", lang), show_alert=True)
        return
    token = callback.data.replace("node_rename_", "")
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    await state.update_data(rename_token=token)
    await state.set_state(RenameNodeStates.waiting_for_new_name)
    back_kb = get_back_keyboard(lang, f"node_select_{token}")
    node_name = html.escape(node.get("name", "Unknown"))
    await callback.message.answer(
        _("node_rename_prompt", lang, name=node_name),
        parse_mode="HTML",
        reply_markup=back_kb,
    )
    await callback.answer()


async def process_node_rename(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await state.clear()
        await message.answer(_("access_denied_no_rights", lang))
        return
    data = await state.get_data()
    token = data.get("rename_token")
    if not token:
        await state.clear()
        await message.answer("Error: Token not found in state.")
        return
    new_name = message.text.strip()
    if not new_name:
        return
    success = await nodes_db.update_node_name(token, new_name)
    if success:
        await message.answer(
            _("node_rename_success", lang, name=html.escape(new_name)),
            parse_mode="HTML",
        )
    else:
        await message.answer("Error updating node name.")
    await state.clear()
    node = await nodes_db.get_node_by_token(token)
    if node:
        stats = node.get("stats", {})
        raw_uptime = stats.get("uptime", 0)
        formatted_uptime = format_uptime(raw_uptime, lang)
        node_name = html.escape(node.get("name", "Unknown"))
        text = _(
            "node_management_menu",
            lang,
            name=node_name,
            ip=node.get("ip", "?"),
            uptime=formatted_uptime,
        )
        keyboard = get_node_management_keyboard(token, lang, user_id)
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def cq_node_delete_menu(callback: types.CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    nodes_data = await _prepare_nodes_data()
    keyboard = get_nodes_delete_keyboard(nodes_data, lang)
    await callback.message.edit_text(
        _("node_delete_select", lang), reply_markup=keyboard, parse_mode="HTML"
    )
    await callback.answer()


async def cq_node_delete_confirm(callback: types.CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    token = callback.data.split("_", 3)[3]
    await nodes_db.delete_node(token)
    await callback.answer(_("node_deleted", lang, name="Node"), show_alert=False)
    await cq_node_delete_menu(callback)


async def cq_node_command(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    data = callback.data[9:]
    token = data[:32]
    cmd = data[33:]
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Error: Node not found", show_alert=True)
        return
    if cmd == "reboot":
        await nodes_db.update_node_extra(token, "is_restarting", True)
    if cmd == "traffic":
        stop_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_("btn_stop_traffic", lang),
                        callback_data=f"node_stop_traffic_{token}",
                    )
                ]
            ]
        )
        if user_id in NODE_TRAFFIC_MONITORS:
            if NODE_TRAFFIC_MONITORS[user_id]["token"] != token:
                del NODE_TRAFFIC_MONITORS[user_id]
        sent_msg = await callback.message.answer(
            _("traffic_start", lang, interval=config.TRAFFIC_INTERVAL),
            reply_markup=stop_kb,
            parse_mode="HTML",
        )
        NODE_TRAFFIC_MONITORS[user_id] = {
            "token": token,
            "message_id": sent_msg.message_id,
            "last_update": 0,
        }
        await nodes_db.update_node_task(token, {"command": cmd, "user_id": user_id})
        await callback.answer()
        return
    await nodes_db.update_node_task(token, {"command": cmd, "user_id": user_id})
    cmd_map = {
        "selftest": "btn_selftest",
        "uptime": "btn_uptime",
        "traffic": "btn_traffic",
        "top": "btn_top",
        "speedtest": "btn_speedtest",
        "reboot": "btn_reboot",
    }
    cmd_name = _(cmd_map.get(cmd, cmd), lang)
    node_name = html.escape(node.get("name", "Unknown"))
    await callback.answer(
        _("node_cmd_sent", lang, cmd=cmd_name, name=node_name), show_alert=False
    )


async def cq_node_stop_traffic(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.replace("node_stop_traffic_", "")
    node = await nodes_db.get_node_by_token(token)
    node_name = html.escape(node.get("name", "Unknown")) if node else "Unknown"
    if user_id in NODE_TRAFFIC_MONITORS:
        del NODE_TRAFFIC_MONITORS[user_id]
        try:
            await callback.message.delete()
            if node:
                stats = node.get("stats", {})
                raw_uptime = stats.get("uptime", 0)
                formatted_uptime = format_uptime(raw_uptime, lang)
                text = _(
                    "node_management_menu",
                    lang,
                    name=node_name,
                    ip=node.get("ip", "?"),
                    uptime=formatted_uptime,
                )
                keyboard = get_node_management_keyboard(token, lang, user_id)
                await callback.message.answer(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
        except Exception as e:
            logging.debug(f"cq_node_stop_traffic delete/answer error: {e}")
    await callback.answer(
        _("node_traffic_stopped_alert", lang, name=node_name), show_alert=False
    )


async def node_traffic_scheduler(bot: Bot):
    while True:
        try:
            await asyncio.sleep(config.TRAFFIC_INTERVAL)
            if not NODE_TRAFFIC_MONITORS:
                continue
            for user_id, monitor_data in list(NODE_TRAFFIC_MONITORS.items()):
                token = monitor_data.get("token")
                node = await nodes_db.get_node_by_token(token)
                if not node:
                    if user_id in NODE_TRAFFIC_MONITORS:
                        del NODE_TRAFFIC_MONITORS[user_id]
                    continue
                await nodes_db.update_node_task(
                    token, {"command": "traffic", "user_id": user_id}
                )
        except Exception as e:
            logging.error(f"Error in node_traffic_scheduler: {e}")
            await asyncio.sleep(5)


async def nodes_monitor(bot: Bot):
    logging.info("Nodes Monitor started.")
    await asyncio.sleep(10)
    while True:
        try:
            now = time.time()
            nodes = await nodes_db.get_all_nodes()
            for token, node in nodes.items():
                name = html.escape(node.get("name", "Unknown"))
                last_seen = node.get("last_seen", 0)
                is_restarting = node.get("is_restarting", False)
                alerts = node.get(
                    "alerts",
                    {
                        "cpu": {"active": False, "last_time": 0},
                        "ram": {"active": False, "last_time": 0},
                        "disk": {"active": False, "last_time": 0},
                    },
                )
                is_offline_alert_sent = node.get("is_offline_alert_sent", False)
                is_dead = (
                    now - last_seen >= config.NODE_OFFLINE_TIMEOUT and last_seen > 0
                )
                if is_dead and (not is_offline_alert_sent) and (not is_restarting):
                    await send_alert(
                        bot,
                        lambda lang: _(
                            "alert_node_down",
                            lang,
                            name=name,
                            last_seen=datetime.fromtimestamp(last_seen).strftime(
                                "%H:%M:%S"
                            ),
                        ),
                        "downtime",
                        node_token=token,
                    )
                    await nodes_db.update_node_extra(
                        token, "is_offline_alert_sent", True
                    )
                elif not is_dead and is_offline_alert_sent:
                    await send_alert(
                        bot,
                        lambda lang: _("alert_node_up", lang, name=name),
                        "downtime",
                        node_token=token,
                    )
                    await nodes_db.update_node_extra(
                        token, "is_offline_alert_sent", False
                    )
                if not is_dead and is_restarting:
                    await nodes_db.update_node_extra(token, "is_restarting", False)
                if not is_dead and last_seen > 0:
                    stats = node.get("stats", {})

                    async def check(metric, current, threshold, key_high, key_norm):
                        state = alerts.get(metric, {"active": False, "last_time": 0})
                        updated = False
                        if current >= threshold:
                            if (
                                not state["active"]
                                or now - state["last_time"]
                                > config.RESOURCE_ALERT_COOLDOWN
                            ):
                                p_info = stats.get(f"process_{metric}", "n/a")
                                await send_alert(
                                    bot,
                                    lambda lang: _(
                                        key_high,
                                        lang,
                                        name=name,
                                        usage=current,
                                        threshold=threshold,
                                        processes=p_info,
                                    ),
                                    "node_resources",
                                    node_token=token,
                                    processes=p_info,
                                )
                                state["active"] = True
                                state["last_time"] = now
                                updated = True
                        elif current < threshold and state["active"]:
                            await send_alert(
                                bot,
                                lambda lang: _(
                                    key_norm, lang, name=name, usage=current
                                ),
                                "node_resources",
                                node_token=token,
                            )
                            state["active"] = False
                            state["last_time"] = 0
                            updated = True
                        alerts[metric] = state
                        return updated

                    u1 = await check(
                        "cpu",
                        stats.get("cpu", 0),
                        config.CPU_THRESHOLD,
                        "alert_node_cpu_high",
                        "alert_node_cpu_normal",
                    )
                    u2 = await check(
                        "ram",
                        stats.get("ram", 0),
                        config.RAM_THRESHOLD,
                        "alert_node_ram_high",
                        "alert_node_ram_normal",
                    )
                    u3 = await check(
                        "disk",
                        stats.get("disk", 0),
                        config.DISK_THRESHOLD,
                        "alert_node_disk_high",
                        "alert_node_disk_normal",
                    )
                    if u1 or u2 or u3:
                        await nodes_db.update_node_extra(token, "alerts", alerts)
        except Exception as e:
            logging.error(f"Error in nodes_monitor: {e}", exc_info=True)
        await asyncio.sleep(20)
