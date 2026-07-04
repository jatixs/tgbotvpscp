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
from core.shared_state import LAST_MESSAGE_IDS, NODE_TRAFFIC_MONITORS, ACTIVE_NODE_SPEEDTESTS
from core import nodes_db
from core.keyboards import (
    get_nodes_list_keyboard,
    get_node_management_keyboard,
    get_nodes_delete_keyboard,
    get_back_keyboard,
    get_node_services_keyboard,
    get_node_service_actions_keyboard,
    get_node_billing_keyboard,
    get_master_billing_keyboard,
)
from core.utils import build_node_uptime_report, format_uptime
import aiohttp

BUTTON_KEY = "btn_nodes"
AGENT_START_TIME = time.time()

class AddNodeStates(StatesGroup):
    waiting_for_name = State()


class RenameNodeStates(StatesGroup):
    waiting_for_new_name = State()


class NodeBillingStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_date_shift = State()


class MasterBillingStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_date_shift = State()


def _fmt_billing_amount(amount, currency: str, lang: str) -> str:
    """Format billing amount: None→not-set, 0→free, else '{amount} {currency}'."""
    if amount is None:
        return _("billing_date_not_set", lang)
    try:
        if float(amount) == 0.0:
            return _("billing_free", lang)
    except (TypeError, ValueError):
        pass
    return f"{amount} {currency}"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(nodes_handler)
    dp.message(I18nFilter("btn_billing"))(billing_handler)
    dp.callback_query(F.data == "nodes_list_refresh")(cq_nodes_list_refresh)
    dp.callback_query(F.data == "node_add_new")(cq_add_node_start)
    dp.message(StateFilter(AddNodeStates.waiting_for_name))(process_node_name)
    dp.callback_query(F.data == "node_delete_menu")(cq_node_delete_menu)
    dp.callback_query(F.data.startswith("node_delete_confirm_"))(cq_node_delete_confirm)
    dp.callback_query(F.data.startswith("node_select_"))(cq_node_select)
    dp.callback_query(F.data.startswith("node_rename_"))(cq_node_rename)
    dp.message(StateFilter(RenameNodeStates.waiting_for_new_name))(process_node_rename)
    dp.callback_query(F.data.startswith("node_stop_traffic_"))(cq_node_stop_traffic)
    dp.callback_query(F.data.startswith("node_services_"))(cq_node_services)
    dp.callback_query(F.data.startswith("nsd_"))(cq_node_service_detail)
    dp.callback_query(F.data.startswith("nsa_"))(cq_node_service_action)
    dp.callback_query(F.data.startswith("node_cmd_"))(cq_node_command)
    dp.callback_query(F.data.startswith("node_billing_"))(cq_node_billing)
    dp.callback_query(F.data.startswith("billing_change_amount_"))(cq_billing_change_amount)
    dp.callback_query(F.data.startswith("billing_change_currency_"))(cq_billing_change_currency)
    dp.callback_query(F.data.startswith("billing_set_cur_"))(cq_billing_set_currency)
    dp.callback_query(F.data.startswith("billing_shift_date_"))(cq_billing_shift_date)
    dp.callback_query(F.data.startswith("billing_toggle_reminder_"))(cq_billing_toggle_reminder)
    dp.message(StateFilter(NodeBillingStates.waiting_for_amount))(process_billing_amount)
    dp.message(StateFilter(NodeBillingStates.waiting_for_date_shift))(process_billing_date_shift)
    dp.callback_query(F.data == "master_billing_menu")(cq_master_billing_menu)
    dp.callback_query(F.data == "master_billing_change_amount")(cq_master_billing_change_amount)
    dp.callback_query(F.data == "master_billing_change_currency")(cq_master_billing_change_currency)
    dp.callback_query(F.data.startswith("master_billing_set_cur_"))(cq_master_billing_set_currency)
    dp.callback_query(F.data == "master_billing_shift_date")(cq_master_billing_shift_date)
    dp.callback_query(F.data == "master_billing_toggle_reminder")(cq_master_billing_toggle_reminder)
    dp.message(StateFilter(MasterBillingStates.waiting_for_amount))(process_master_billing_amount)
    dp.message(StateFilter(MasterBillingStates.waiting_for_date_shift))(process_master_billing_date_shift)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    task_monitor = asyncio.create_task(nodes_monitor(bot), name="NodesMonitor")
    task_traffic = asyncio.create_task(
        node_traffic_scheduler(bot), name="NodesTrafficScheduler"
    )
    task_speedtest = asyncio.create_task(
        node_speedtest_progress_task(bot), name="NodesSpeedtestScheduler"
    )
    task_billing = asyncio.create_task(
        billing_reminders_task(bot), name="NodesBillingReminders"
    )
    return [task_monitor, task_traffic, task_speedtest, task_billing]


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


async def billing_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await send_access_denied_message(message.bot, user_id, message.chat.id, "billing")
        return
    await delete_previous_message(user_id, "billing", message.chat.id, message.bot)
    
    from core.config import get_bot_config
    master_billing = await get_bot_config("master_billing", {})
    
    amount = master_billing.get("amount")
    next_date_iso = master_billing.get("next_payment_date")
    currency = master_billing.get("currency", "$")
    
    if next_date_iso:
        import datetime
        dt = datetime.datetime.fromisoformat(next_date_iso)
        date_str = dt.strftime("%d.%m.%Y")
    else:
        date_str = _("billing_date_not_set", lang)
        
    amount_str = _fmt_billing_amount(amount, currency, lang)
    master_name = _("master_server_name", lang)
    
    text = _("billing_menu_text", lang, name=master_name, amount=amount_str, date=date_str)
    
    keyboard = get_master_billing_keyboard(master_billing, lang)
    sent_message = await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})["billing"] = sent_message.message_id


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
            uptime_report=build_node_uptime_report(node, lang, config.NODE_OFFLINE_TIMEOUT),
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
    if cmd == "uptime":
        avail = node.get("availability", {})
        total_downtime = float(avail.get("total_downtime_seconds", 0))
        
        inline_kb = []
        if total_downtime > 0 and user_id == config.ADMIN_USER_ID:
            inline_kb.append([InlineKeyboardButton(text=_("btn_reset_uptime", lang), callback_data=f"node_cmd_{token}_resetuptime")])
        inline_kb.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data=f"node_select_{token}", style="primary")])
        
        await callback.message.edit_text(
            build_node_uptime_report(node, lang, config.NODE_OFFLINE_TIMEOUT),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_kb),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    if cmd == "resetuptime":
        if user_id != config.ADMIN_USER_ID:
            await callback.answer(_("access_denied_generic", lang), show_alert=True)
            return
        await nodes_db.reset_node_availability(token)
        await callback.answer(_("uptime_reset_success", lang), show_alert=True)
        # Re-fetch node to get updated counters
        node = await nodes_db.get_node_by_token(token)
        inline_kb = [[InlineKeyboardButton(text=_("btn_back", lang), callback_data=f"node_select_{token}", style="primary")]]
        await callback.message.edit_text(
            build_node_uptime_report(node, lang, config.NODE_OFFLINE_TIMEOUT),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_kb),
            parse_mode="HTML",
        )
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
        "update": "btn_node_update_system",
        "reboot": "btn_reboot",
    }
    cmd_name = _(cmd_map.get(cmd, cmd), lang)
    node_name = html.escape(node.get("name", "Unknown"))
    
    if cmd == "speedtest":
        msg = await callback.message.answer(
            _("speedtest_progress_node", lang, name=node_name, elapsed=0),
            parse_mode="HTML"
        )
        ACTIVE_NODE_SPEEDTESTS[f"{token}_{user_id}"] = {
            "chat_id": msg.chat.id,
            "message_id": msg.message_id,
            "start_time": time.time(),
            "node_name": node_name,
        }

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


async def cq_node_services(callback: types.CallbackQuery):
    """Show services list for a node"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.replace("node_services_", "")
    
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    node_name = html.escape(node.get("name", "Unknown"))
    
    # Check if node is online
    now = time.time()
    last_seen = node.get("last_seen", 0)
    if now - last_seen >= config.NODE_OFFLINE_TIMEOUT:
        await callback.message.edit_text(
            _("node_services_empty", lang, name=node_name),
            reply_markup=get_back_keyboard(lang, f"node_select_{token}"),
            parse_mode="HTML",
        )
        return
    
    services = node.get("services", [])
    if not services:
        await callback.message.edit_text(
            _("node_services_empty", lang, name=node_name),
            reply_markup=get_back_keyboard(lang, f"node_select_{token}"),
            parse_mode="HTML",
        )
        return
    
    keyboard = get_node_services_keyboard(token, services, lang)
    await callback.message.edit_text(
        _("node_services_menu", lang, name=node_name),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


async def cq_node_service_detail(callback: types.CallbackQuery):
    """Show service details with action buttons"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Parse: nsd_{token}_{service_name}
    parts = callback.data.split("_", 2)
    if len(parts) < 3:
        await callback.answer("Invalid data", show_alert=True)
        return
    
    token = parts[1]
    service_name = parts[2]
    
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    node_name = html.escape(node.get("name", "Unknown"))
    services = node.get("services", [])
    
    # Find the service
    service_info = None
    for svc in services:
        if svc.get("name") == service_name:
            service_info = svc
            break
    
    if not service_info:
        await callback.answer("Service not found", show_alert=True)
        return
    
    status = service_info.get("status", "unknown")
    svc_type = service_info.get("type", "systemd")
    status_text = "🟢 Running" if status == "running" else "🔴 Stopped"
    type_icon = "🐳 Docker" if svc_type == "docker" else "⚙️ Systemd"
    
    keyboard = get_node_service_actions_keyboard(token, service_name, status, lang, svc_type)
    await callback.message.edit_text(
        _("node_service_detail", lang, 
          service=service_name, 
          status=status_text,
          type=type_icon,
          node=node_name),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


async def cq_node_service_action(callback: types.CallbackQuery):
    """Execute service action (start/stop/restart)"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Only admins can manage services
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("access_denied_no_rights", lang), show_alert=True)
        return
    
    # Parse: nsa_{token}_{service}_{t}_{action} (t: d=docker, s=systemd)
    parts = callback.data.split("_")
    if len(parts) < 5:
        await callback.answer("Invalid data", show_alert=True)
        return
    
    token = parts[1]
    service_name = parts[2]
    t = parts[3]  # d=docker, s=systemd
    action = parts[4]
    svc_type = "docker" if t == "d" else "systemd"
    
    if action not in ["start", "stop", "restart"]:
        await callback.answer("Invalid action", show_alert=True)
        return
    
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    node_name = html.escape(node.get("name", "Unknown"))
    
    # Send task to node with service type
    await nodes_db.update_node_task(token, {
        "command": "service_action",
        "service": service_name,
        "action": action,
        "type": svc_type,
        "user_id": user_id
    })
    
    action_text = {
        "start": _("service_action_start", lang),
        "stop": _("service_action_stop", lang),
        "restart": _("service_action_restart", lang),
    }.get(action, action)
    
    await callback.answer(
        _("services_action_started", lang, action=action_text, name=service_name),
        show_alert=False
    )
    
    # Return to services list after short delay
    await asyncio.sleep(1)
    await cq_node_services(callback)


async def node_speedtest_progress_task(bot: Bot):
    from aiogram.exceptions import TelegramRetryAfter
    while True:
        try:
            await asyncio.sleep(3)
            if not ACTIVE_NODE_SPEEDTESTS:
                continue
            now = time.time()
            for key, data in list(ACTIVE_NODE_SPEEDTESTS.items()):
                elapsed = int(now - data["start_time"])
                if elapsed > 150:  # Timeout 2.5 mins
                    ACTIVE_NODE_SPEEDTESTS.pop(key, None)
                    continue
                node_name_disp = data.get("node_name", "Node")
                # Determine lang from key (format: token_user_id)
                try:
                    user_id_from_key = int(key.split("_")[-1])
                    lang_for_notif = get_user_lang(user_id_from_key)
                except Exception:
                    lang_for_notif = "ru"
                try:
                    phase_cycle = (
                        "speedtest_progress_ping",
                        "speedtest_progress_downloading",
                        "speedtest_progress_uploading",
                    )
                    phase_index = min(len(phase_cycle) - 1, elapsed // 7)
                    await bot.edit_message_text(
                        _(
                            phase_cycle[phase_index],
                            lang_for_notif,
                            name=node_name_disp,
                            elapsed=elapsed,
                        ),
                        chat_id=data["chat_id"],
                        message_id=data["message_id"],
                        parse_mode="HTML"
                    )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception:
                    pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"node_speedtest_progress_task error: {e}")
            await asyncio.sleep(5)


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
    grace_period = config.NODE_OFFLINE_TIMEOUT + 15
    await asyncio.sleep(10)
    while True:
        try:
            now = time.time()
            is_startup_grace = (now - AGENT_START_TIME) < grace_period
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
                if is_dead:
                    await nodes_db.mark_node_offline(token, last_seen)
                if is_startup_grace:
                    if not is_dead and is_offline_alert_sent:
                        await nodes_db.update_node_extra(token, "is_offline_alert_sent", False)
                    continue
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


async def cq_node_services(callback: types.CallbackQuery):
    """Show node services menu"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.replace("node_services_", "")
    
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    node_name = html.escape(node.get("name", "Unknown"))
    services = node.get("services", [])
    
    if not services:
        # Request services from node
        await nodes_db.update_node_task(token, {"command": "services_list", "user_id": user_id})
        await callback.answer(_("node_services_loading", lang), show_alert=False)
        
        # Wait a bit and try to get services
        await asyncio.sleep(2)
        node = await nodes_db.get_node_by_token(token)
        services = node.get("services", [])
    
    if not services:
        await callback.message.edit_text(
            _("node_services_empty", lang, name=node_name),
            reply_markup=get_back_keyboard(lang, f"node_select_{token}"),
            parse_mode="HTML",
        )
        return
    
    keyboard = get_node_services_keyboard(token, services, lang)
    await callback.message.edit_text(
        _("node_services_menu", lang, name=node_name),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


async def cq_node_service_detail(callback: types.CallbackQuery):
    """Show service details with actions"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Parse: nsd_{token}_{service}
    parts = callback.data.split("_", 2)
    if len(parts) < 3:
        await callback.answer("Invalid data", show_alert=True)
        return
    
    token = parts[1]
    service_name = parts[2]
    
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    services = node.get("services", [])
    service = next((s for s in services if s.get("name") == service_name), None)
    
    if not service:
        await callback.answer("Service not found", show_alert=True)
        return
    
    status = service.get("status", "unknown")
    svc_type = service.get("type", "systemd")
    status_text = _("web_services_status_running", lang) if status == "running" else _("web_services_status_stopped", lang)
    status_icon = "🟢" if status == "running" else "🔴"
    type_icon = "🐳 Docker" if svc_type == "docker" else "⚙️ Systemd"
    
    text = _(
        "node_service_detail",
        lang,
        service=service_name,
        status=f"{status_icon} {status_text}",
        type=type_icon,
        node=html.escape(node.get("name", "Unknown")),
    )
    
    keyboard = get_node_service_actions_keyboard(token, service_name, status, lang, svc_type)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


async def cq_node_service_action(callback: types.CallbackQuery):
    """Execute service action (start/stop/restart)"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Parse: nsa_{token}_{service}_{t}_{action} (t: d=docker, s=systemd)
    parts = callback.data.split("_")
    if len(parts) < 5:
        await callback.answer("Invalid data", show_alert=True)
        return
    
    token = parts[1]
    service_name = parts[2]
    t = parts[3]  # d=docker, s=systemd
    action = parts[4]
    svc_type = "docker" if t == "d" else "systemd"
    
    if action not in ["start", "stop", "restart"]:
        await callback.answer("Invalid action", show_alert=True)
        return
    
    node = await nodes_db.get_node_by_token(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    # Send service action task to node with type
    await nodes_db.update_node_task(token, {
        "command": "service_action",
        "service": service_name,
        "action": action,
        "type": svc_type,
        "user_id": user_id,
    })
    
    action_name = _(f"service_action_{action}", lang)
    await callback.answer(
        _("services_action_started", lang, action=action_name, name=service_name),
        show_alert=False,
    )
    
    # Wait a bit then refresh services list
    await asyncio.sleep(3)
    await cq_node_services(callback)


async def cq_node_billing(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("access_denied_generic", get_user_lang(user_id)), show_alert=True)
        return
    token = callback.data.split("_")[2]
    try:
        node = await nodes_db.get_node_by_token(token)
    except Exception:
        await callback.answer("Database schema is outdated. Please restart the bot.", show_alert=True)
        return
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return
    
    lang = get_user_lang(user_id)
    keyboard = get_node_billing_keyboard(token, node, lang)
    
    provider = node.get("provider_name") or "Unknown"
    amount = node.get("billing_amount")
    currency = node.get("currency") or "$"
    date = node.get("next_payment_date")
    date_str = date.strftime("%d.%m.%Y") if date else _("billing_date_not_set", lang)
    
    amount_str = _fmt_billing_amount(amount, currency, lang)
    node_name = node.get("name", "Unknown")
    text = _("billing_menu_text_node", lang, name=node_name, provider=provider, amount=amount_str, date=date_str)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

async def cq_billing_change_amount(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_")[3]
    await state.set_state(NodeBillingStates.waiting_for_amount)
    msg = await callback.message.answer(_("billing_prompt_amount", lang))
    await state.update_data(billing_token=token, menu_msg_id=callback.message.message_id, prompt_msg_id=msg.message_id)
    await callback.answer()

async def process_billing_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    data = await state.get_data()
    token = data.get("billing_token")
    if not token:
        await state.clear()
        return
        
    try: await message.delete()
    except: pass
    
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except: pass

    import asyncio
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        temp = await message.answer("Invalid format. Please enter a number.")
        async def del_temp(m):
            await asyncio.sleep(3)
            try: await m.delete()
            except: pass
        asyncio.create_task(del_temp(temp))
        return
    
    t_hash = nodes_db._get_token_hash(token)
    node_obj = await nodes_db.Node.get_or_none(token_hash=t_hash)
    if node_obj:
        from tortoise.exceptions import OperationalError
        try:
            node_obj.billing_amount = amount
            await node_obj.save(update_fields=["billing_amount"])
            
            menu_msg_id = data.get("menu_msg_id")
            if menu_msg_id:
                currency = getattr(node_obj, "billing_currency", "$")
                amount_str = _fmt_billing_amount(amount, currency, lang)
                date_val = getattr(node_obj, "next_payment_date", None)
                date_str = date_val.strftime("%d.%m.%Y") if date_val else _("billing_date_not_set", lang)
                
                provider = getattr(node_obj, "provider_name") or "Unknown"
                clean_text = _("billing_menu_text_node", lang, name=node_obj.name, provider=provider, amount=amount_str, date=date_str)
                toast_text = clean_text + "\n\n✅ <b>Данные обновлены!</b>"
                
                from core.keyboards import get_node_billing_keyboard
                keyboard = get_node_billing_keyboard(token, dict(node_obj), lang)

                await message.bot.edit_message_text(toast_text, chat_id=message.chat.id, message_id=menu_msg_id, reply_markup=keyboard, parse_mode="HTML")
                
                async def remove_toast(cid, mid, txt, kb):
                    await asyncio.sleep(3)
                    try: await message.bot.edit_message_text(txt, chat_id=cid, message_id=mid, reply_markup=kb, parse_mode="HTML")
                    except: pass
                asyncio.create_task(remove_toast(message.chat.id, menu_msg_id, clean_text, keyboard))
        except OperationalError:
            pass
    await state.clear()

async def cq_billing_shift_date(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_")[3]
    await state.set_state(NodeBillingStates.waiting_for_date_shift)
    msg = await callback.message.answer(_("billing_prompt_date_shift", lang))
    await state.update_data(billing_token=token, menu_msg_id=callback.message.message_id, prompt_msg_id=msg.message_id)
    await callback.answer()

async def process_billing_date_shift(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    data = await state.get_data()
    token = data.get("billing_token")
    if not token:
        await state.clear()
        return
        
    try: await message.delete()
    except: pass
    
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except: pass

    import datetime
    import asyncio
    text = message.text.strip()
    target_date = None
    days = None
    
    if "." in text:
        parts = text.split(".")
        if len(parts) >= 2:
            try:
                day = int(parts[0])
                month = int(parts[1])
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                year = now_utc.year
                if len(parts) == 3:
                    if len(parts[2]) == 2:
                        year = 2000 + int(parts[2])
                    else:
                        year = int(parts[2])
                target_date = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
            except ValueError:
                pass
                
    if target_date is None:
        try:
            days = int(text)
        except ValueError:
            temp = await message.answer("Неверный формат. Введите число дней или дату (ДД.ММ.ГГГГ).")
            async def del_temp(m):
                await asyncio.sleep(3)
                try: await m.delete()
                except: pass
            asyncio.create_task(del_temp(temp))
            return

    today = datetime.datetime.now(datetime.timezone.utc).date()
    if target_date is not None and target_date.date() < today:
        temp = await message.answer(_("billing_date_past_error", lang))
        async def del_temp_date(m):
            await asyncio.sleep(3)
            try: await m.delete()
            except: pass
        asyncio.create_task(del_temp_date(temp))
        return
            
    t_hash = nodes_db._get_token_hash(token)
    node_obj = await nodes_db.Node.get_or_none(token_hash=t_hash)
    if node_obj:
        from tortoise.exceptions import OperationalError
        try:
            if target_date:
                new_date = target_date
            else:
                current_date = getattr(node_obj, "next_payment_date", None) or datetime.datetime.now(datetime.timezone.utc)
                new_date = current_date + datetime.timedelta(days=days)
                if new_date.date() < today:
                    temp = await message.answer(_("billing_date_past_error", lang))
                    async def del_temp_r(m):
                        await asyncio.sleep(3)
                        try: await m.delete()
                        except: pass
                    asyncio.create_task(del_temp_r(temp))
                    await state.clear()
                    return
            node_obj.next_payment_date = new_date
            await node_obj.save(update_fields=["next_payment_date"])
            
            menu_msg_id = data.get("menu_msg_id")
            if menu_msg_id:
                amount_val = getattr(node_obj, "billing_amount", None)
                currency = getattr(node_obj, "billing_currency", "$")
                amount_str = _fmt_billing_amount(amount_val, currency, lang)
                date_str = node_obj.next_payment_date.strftime("%d.%m.%Y")
                
                provider = getattr(node_obj, "provider_name") or "Unknown"
                clean_text = _("billing_menu_text_node", lang, name=node_obj.name, provider=provider, amount=amount_str, date=date_str)
                toast_text = clean_text + "\n\n✅ <b>Данные сохранены!</b>"
                
                from core.keyboards import get_node_billing_keyboard
                keyboard = get_node_billing_keyboard(token, dict(node_obj), lang)

                await message.bot.edit_message_text(toast_text, chat_id=message.chat.id, message_id=menu_msg_id, reply_markup=keyboard, parse_mode="HTML")
                
                async def remove_toast(cid, mid, txt, kb):
                    await asyncio.sleep(3)
                    try: await message.bot.edit_message_text(txt, chat_id=cid, message_id=mid, reply_markup=kb, parse_mode="HTML")
                    except: pass
                asyncio.create_task(remove_toast(message.chat.id, menu_msg_id, clean_text, keyboard))
        except OperationalError:
            pass
    await state.clear()

async def cq_billing_toggle_reminder(callback: types.CallbackQuery):
    token = callback.data.split("_")[3]
    t_hash = nodes_db._get_token_hash(token)
    node_obj = await nodes_db.Node.get_or_none(token_hash=t_hash)
    if node_obj:
        from tortoise.exceptions import OperationalError
        try:
            current = getattr(node_obj, "reminder_enabled", False)
            node_obj.reminder_enabled = not current
            await node_obj.save(update_fields=["reminder_enabled"])
            
            from core.keyboards import get_notifications_node_settings_keyboard
            await callback.message.edit_reply_markup(
                reply_markup=get_notifications_node_settings_keyboard(
                    token, dict(node_obj), callback.from_user.id
                )
            )
            await callback.answer()
        except OperationalError:
            await callback.answer("Database schema is outdated. Please run aerich upgrade.", show_alert=True)
    else:
        await callback.answer("Node not found")


# --- MASTER BILLING HANDLERS ---

async def cq_master_billing_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    from core.config import get_bot_config
    master_billing = await get_bot_config("master_billing", {})
    
    amount = master_billing.get("amount")
    next_date_iso = master_billing.get("next_payment_date")
    currency = master_billing.get("currency", "$")
    
    if next_date_iso:
        import datetime
        dt = datetime.datetime.fromisoformat(next_date_iso)
        date_str = dt.strftime("%d.%m.%Y")
    else:
        date_str = _("billing_date_not_set", lang)
        
    amount_str = _fmt_billing_amount(amount, currency, lang)
    master_name = _("master_server_name", lang)
    
    text = _("billing_menu_text", lang, name=master_name, amount=amount_str, date=date_str)
    
    keyboard = get_master_billing_keyboard(master_billing, lang)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        pass
    await callback.answer()


async def cq_master_billing_change_amount(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    await state.set_state(MasterBillingStates.waiting_for_amount)
    msg = await callback.message.answer(_("billing_prompt_amount", lang))
    await state.update_data(menu_msg_id=callback.message.message_id, prompt_msg_id=msg.message_id)
    await callback.answer()

async def process_master_billing_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    data = await state.get_data()
    
    try: await message.delete()
    except: pass
    
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except: pass

    import asyncio
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        temp = await message.answer("Invalid format. Please enter a number.")
        async def del_temp(m):
            await asyncio.sleep(3)
            try: await m.delete()
            except: pass
        asyncio.create_task(del_temp(temp))
        return
    
    from core.config import get_bot_config, set_bot_config
    master_billing = await get_bot_config("master_billing", {})
    master_billing["amount"] = amount
    await set_bot_config("master_billing", master_billing)
    
    menu_msg_id = data.get("menu_msg_id")
    if menu_msg_id:
        currency = master_billing.get("currency", "$")
        amount_str = _fmt_billing_amount(amount, currency, lang)
        
        next_date_iso = master_billing.get("next_payment_date")
        if next_date_iso:
            import datetime
            dt = datetime.datetime.fromisoformat(next_date_iso)
            date_str = dt.strftime("%d.%m.%Y")
        else:
            date_str = _("billing_date_not_set", lang)
            
        master_name = _("master_server_name", lang)
        clean_text = _("billing_menu_text", lang, name=master_name, amount=amount_str, date=date_str)
        toast_text = clean_text + "\n\n✅ <b>Данные обновлены!</b>"
        
        from core.keyboards import get_master_billing_keyboard
        keyboard = get_master_billing_keyboard(master_billing, lang)
        
        try:
            await message.bot.edit_message_text(toast_text, chat_id=message.chat.id, message_id=menu_msg_id, reply_markup=keyboard, parse_mode="HTML")
            
            async def remove_toast(cid, mid, txt, kb):
                await asyncio.sleep(3)
                try: await message.bot.edit_message_text(txt, chat_id=cid, message_id=mid, reply_markup=kb, parse_mode="HTML")
                except: pass
            asyncio.create_task(remove_toast(message.chat.id, menu_msg_id, clean_text, keyboard))
        except Exception:
            pass
            
    await state.clear()

async def cq_master_billing_shift_date(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    await state.set_state(MasterBillingStates.waiting_for_date_shift)
    msg = await callback.message.answer(_("billing_prompt_date_shift", lang))
    await state.update_data(menu_msg_id=callback.message.message_id, prompt_msg_id=msg.message_id)
    await callback.answer()

async def process_master_billing_date_shift(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    data = await state.get_data()
    
    try: await message.delete()
    except: pass
    
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        try: await message.bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except: pass

    import datetime
    import asyncio
    text = message.text.strip()
    target_date = None
    days = None
    
    if "." in text:
        parts = text.split(".")
        if len(parts) >= 2:
            try:
                day = int(parts[0])
                month = int(parts[1])
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                year = now_utc.year
                if len(parts) == 3:
                    if len(parts[2]) == 2:
                        year = 2000 + int(parts[2])
                    else:
                        year = int(parts[2])
                target_date = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
            except ValueError:
                pass
                
    if target_date is None:
        try:
            days = int(text)
        except ValueError:
            temp = await message.answer("Неверный формат. Введите число дней или дату (ДД.ММ.ГГГГ).")
            async def del_temp(m):
                await asyncio.sleep(3)
                try: await m.delete()
                except: pass
            asyncio.create_task(del_temp(temp))
            return

    today = datetime.datetime.now(datetime.timezone.utc).date()
    if target_date is not None and target_date.date() < today:
        temp = await message.answer(_("billing_date_past_error", lang))
        async def del_temp_date(m):
            await asyncio.sleep(3)
            try: await m.delete()
            except: pass
        asyncio.create_task(del_temp_date(temp))
        return
    
    from core.config import get_bot_config, set_bot_config
    
    master_billing = await get_bot_config("master_billing", {})
    
    if target_date:
        new_date = target_date
    else:
        next_date_iso = master_billing.get("next_payment_date")
        if next_date_iso:
            current_date = datetime.datetime.fromisoformat(next_date_iso)
        else:
            current_date = datetime.datetime.now(datetime.timezone.utc)
        
        new_date = current_date + datetime.timedelta(days=days)
        if new_date.date() < today:
            temp = await message.answer(_("billing_date_past_error", lang))
            async def del_temp_r(m):
                await asyncio.sleep(3)
                try: await m.delete()
                except: pass
            asyncio.create_task(del_temp_r(temp))
            await state.clear()
            return
        
    master_billing["next_payment_date"] = new_date.isoformat()
    await set_bot_config("master_billing", master_billing)
    
    menu_msg_id = data.get("menu_msg_id")
    if menu_msg_id:
        amount_val = master_billing.get("amount")
        currency = master_billing.get("currency", "$")
        amount_str = _fmt_billing_amount(amount_val, currency, lang)
        date_str = new_date.strftime("%d.%m.%Y")
        master_name = _("master_server_name", lang)
        
        clean_text = _("billing_menu_text", lang, name=master_name, amount=amount_str, date=date_str)
        toast_text = clean_text + "\n\n✅ <b>Данные сохранены!</b>"
        
        from core.keyboards import get_master_billing_keyboard
        keyboard = get_master_billing_keyboard(master_billing, lang)
        
        try:
            await message.bot.edit_message_text(toast_text, chat_id=message.chat.id, message_id=menu_msg_id, reply_markup=keyboard, parse_mode="HTML")
            
            async def remove_toast(cid, mid, txt, kb):
                await asyncio.sleep(3)
                try: await message.bot.edit_message_text(txt, chat_id=cid, message_id=mid, reply_markup=kb, parse_mode="HTML")
                except: pass
            asyncio.create_task(remove_toast(message.chat.id, menu_msg_id, clean_text, keyboard))
        except Exception:
            pass

    await state.clear()

async def cq_master_billing_toggle_reminder(callback: types.CallbackQuery):
    from core.config import get_bot_config, set_bot_config
    master_billing = await get_bot_config("master_billing", {})
    current = master_billing.get("reminder_enabled", False)
    master_billing["reminder_enabled"] = not current
    await set_bot_config("master_billing", master_billing)
    
    from core.keyboards import get_notifications_global_keyboard
    await callback.message.edit_reply_markup(
        reply_markup=get_notifications_global_keyboard(callback.from_user.id, not current)
    )
    await callback.answer()


async def billing_reminders_task(bot: Bot):
    await asyncio.sleep(10)
    import datetime
    from core.config import get_bot_config, set_bot_config
    while True:
        try:
            # Check master server billing
            try:
                master_billing = await get_bot_config("master_billing", {})
                if master_billing.get("reminder_enabled", False):
                    next_date_iso = master_billing.get("next_payment_date")
                    if next_date_iso:
                        next_date = datetime.datetime.fromisoformat(next_date_iso)
                        now = datetime.datetime.now(datetime.timezone.utc)
                        time_left = next_date - now
                        if datetime.timedelta(days=0) < time_left <= datetime.timedelta(days=3):
                            # Ensure we don't spam. Check last notified
                            last_notified = master_billing.get("last_notified")
                            should_notify = True
                            if last_notified:
                                ln_dt = datetime.datetime.fromisoformat(last_notified)
                                if now - ln_dt < datetime.timedelta(hours=24):
                                    should_notify = False
                            
                            if should_notify:
                                amount = master_billing.get("amount", 0.0)
                                currency = master_billing.get("currency", "$")
                                master_name = _("master_server_name", config.DEFAULT_LANGUAGE)
                                text = (
                                    f"⚠️ Напоминание об оплате! Сервер: 💻 {master_name}.\n"
                                    f"К оплате: {amount} {currency} до {next_date.strftime('%d.%m.%Y')}."
                                )
                                await bot.send_message(config.ADMIN_USER_ID, text)
                                master_billing["last_notified"] = now.isoformat()
                                await set_bot_config("master_billing", master_billing)
            except Exception as e:
                logging.error(f"Master Billing reminders task error: {e}")

            # Check nodes billing
            nodes = await nodes_db.Node.all()
            for node_obj in nodes:
                provider_name = getattr(node_obj, "provider_name", None)
                ip = getattr(node_obj, "ip", None)
                reminder_enabled = getattr(node_obj, "reminder_enabled", False)
                next_payment_date = getattr(node_obj, "next_payment_date", None)
                
                if not provider_name and ip and ip != "Unknown":
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(f"http://ip-api.com/json/{ip}") as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    isp = data.get("isp") or data.get("org")
                                    if isp:
                                        node_obj.provider_name = isp
                                        node_obj.is_cloud = True
                                        await node_obj.save(update_fields=["provider_name", "is_cloud"])
                                        provider_name = isp
                    except Exception as e:
                        logging.error(f"Error detecting provider for {ip}: {e}")
                
                if reminder_enabled and next_payment_date:
                    import datetime
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if next_payment_date.tzinfo is None:
                        payment_date = next_payment_date.replace(tzinfo=datetime.timezone.utc)
                    else:
                        payment_date = next_payment_date
                    delta = payment_date - now
                    if datetime.timedelta(0) < delta <= datetime.timedelta(days=3):
                        lang = get_user_lang(config.ADMIN_USER_ID)
                        date_str = payment_date.strftime("%d.%m.%Y")
                        node_name = getattr(node_obj, "name", "Unknown")
                        billing_amount = getattr(node_obj, "billing_amount", 0.0)
                        currency = getattr(node_obj, "currency", "$")
                        amount_str = f"{billing_amount} {currency}" if billing_amount else _("billing_date_not_set", lang)
                        node_title = f"{node_name} ({provider_name})"
                        text = _("billing_menu_text", lang, name=node_title, amount=amount_str, date=date_str)
                        await bot.send_message(config.ADMIN_USER_ID, text)
                        node_obj.reminder_enabled = False
                        await node_obj.save(update_fields=["reminder_enabled"])
        except Exception as e:
            logging.error(f"Billing reminders task error: {e}")
        
        await asyncio.sleep(86400)

async def cq_billing_change_currency(callback: types.CallbackQuery, state: FSMContext):
    from core.keyboards import get_billing_currency_keyboard
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_")[3]
    keyboard = get_billing_currency_keyboard(token, is_master=False, lang=lang)
    await callback.message.edit_text(_("billing_change_currency", lang), reply_markup=keyboard)
    await callback.answer()

async def cq_master_billing_change_currency(callback: types.CallbackQuery, state: FSMContext):
    from core.keyboards import get_billing_currency_keyboard
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    keyboard = get_billing_currency_keyboard(token="", is_master=True, lang=lang)
    await callback.message.edit_text(_("billing_change_currency", lang), reply_markup=keyboard)
    await callback.answer()

async def cq_billing_set_currency(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    parts = callback.data.split("_")
    token = parts[3]
    currency = parts[4]
    
    t_hash = nodes_db._get_token_hash(token)
    node_obj = await nodes_db.Node.get_or_none(token_hash=t_hash)
    if node_obj:
        node_obj.currency = currency
        await node_obj.save(update_fields=["currency"])
        await callback.answer(_("billing_currency_success", lang, currency=currency))
        node = await nodes_db.get_node_by_token(token)
        if node:
            keyboard = get_node_billing_keyboard(token, node, lang)
            provider = node.get("provider_name") or "Unknown"
            amount = node.get("billing_amount")
            date = node.get("next_payment_date")
            date_str = date.strftime("%d.%m.%Y") if date else _("billing_date_not_set", lang)
            amount_str = _fmt_billing_amount(amount, currency, lang)
            node_name = node.get("name", "Unknown")
            text = _("billing_menu_text_node", lang, name=node_name, provider=provider, amount=amount_str, date=date_str)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            return
    await callback.answer()

async def cq_master_billing_set_currency(callback: types.CallbackQuery, state: FSMContext):
    from core.config import get_bot_config, set_bot_config
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    parts = callback.data.split("_")
    currency = parts[4]
    
    mb = await get_bot_config("master_billing") or {}
    mb["currency"] = currency
    await set_bot_config("master_billing", mb)
    
    await callback.answer(_("billing_currency_success", lang, currency=currency))
    
    keyboard = get_master_billing_keyboard(mb, lang)
    amount = mb.get("amount") or 0.0
    date = mb.get("next_payment_date")
    if date:
        try:
            import datetime
            date_obj = datetime.datetime.fromisoformat(date)
            date_str = date_obj.strftime("%d.%m.%Y")
        except:
            date_str = date
    else:
        date_str = _("billing_date_not_set", lang)
    amount_str = _fmt_billing_amount(amount, currency, lang)
    master_name = _("master_server_name", lang)
    text = _("billing_menu_text", lang, name=master_name, amount=amount_str, date=date_str)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

