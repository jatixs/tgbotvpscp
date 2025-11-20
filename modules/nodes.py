# /opt-tg-bot/modules/nodes.py
import time
import asyncio
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import LAST_MESSAGE_IDS, NODES, NODE_TRAFFIC_MONITORS
from core.nodes_db import create_node, delete_node
from core.keyboards import get_nodes_list_keyboard, get_node_management_keyboard, get_nodes_delete_keyboard, get_back_keyboard
from core.config import NODE_OFFLINE_TIMEOUT, TRAFFIC_INTERVAL

BUTTON_KEY = "btn_nodes"

class AddNodeStates(StatesGroup):
    waiting_for_name = State()

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
    
    # Обработчик для остановки трафика
    dp.callback_query(F.data.startswith("node_stop_traffic_"))(cq_node_stop_traffic)
    
    dp.callback_query(F.data.startswith("node_cmd_"))(cq_node_command)

def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    task_monitor = asyncio.create_task(nodes_monitor(bot), name="NodesMonitor")
    task_traffic = asyncio.create_task(node_traffic_scheduler(bot), name="NodesTrafficScheduler")
    return [task_monitor, task_traffic]

async def nodes_handler(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "nodes"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return

    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    prepared_nodes = _prepare_nodes_data()
    keyboard = get_nodes_list_keyboard(prepared_nodes, lang)
    sent_message = await message.answer(_("nodes_menu_header", lang), reply_markup=keyboard, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_nodes_list_refresh(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    prepared_nodes = _prepare_nodes_data()
    keyboard = get_nodes_list_keyboard(prepared_nodes, lang)
    try:
        await callback.message.edit_text(_("nodes_menu_header", lang), reply_markup=keyboard, parse_mode="HTML")
    except Exception: pass
    await callback.answer()

def _prepare_nodes_data():
    result = {}
    now = time.time()
    for token, node in NODES.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        if is_restarting: icon = "🔵"
        elif now - last_seen < NODE_OFFLINE_TIMEOUT: icon = "🟢"
        else: icon = "🔴"
        result[token] = {"name": node.get("name", "Unknown"), "status_icon": icon}
    return result

async def cq_node_select(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_", 2)[2]
    node = NODES.get(token)
    if not node: await callback.answer("Node not found", show_alert=True); return

    now = time.time()
    last_seen = node.get("last_seen", 0)
    is_restarting = node.get("is_restarting", False)

    if is_restarting:
        await callback.answer(_("node_restarting_alert", lang, name=node.get("name")), show_alert=True)
        return
    if now - last_seen >= NODE_OFFLINE_TIMEOUT:
        stats = node.get("stats", {})
        fmt_time = datetime.fromtimestamp(last_seen).strftime('%Y-%m-%d %H:%M:%S') if last_seen > 0 else "Never"
        text = _("node_details_offline", lang, name=node.get("name"), last_seen=fmt_time, ip=node.get("ip", "?"), cpu=stats.get("cpu", "?"), ram=stats.get("ram", "?"), disk=stats.get("disk", "?"))
        await callback.message.edit_text(text, reply_markup=get_back_keyboard(lang, "nodes_list_refresh"), parse_mode="HTML")
        return

    stats = node.get("stats", {})
    text = _("node_management_menu", lang, name=node.get("name"), ip=node.get("ip", "?"), uptime=stats.get("uptime", "?"))
    keyboard = get_node_management_keyboard(token, lang)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

async def cq_add_node_start(callback: types.CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text("Введите имя новой ноды:", reply_markup=get_back_keyboard(lang, "nodes_list_refresh"))
    await state.set_state(AddNodeStates.waiting_for_name)
    await callback.answer()

async def process_node_name(message: types.Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    name = message.text.strip()
    token = create_node(name)
    await message.answer(_("node_add_success_token", lang, name=name, token=token), parse_mode="HTML")
    await state.clear()

async def cq_node_delete_menu(callback: types.CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    keyboard = get_nodes_delete_keyboard(_prepare_nodes_data(), lang)
    await callback.message.edit_text(_("node_delete_select", lang), reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

async def cq_node_delete_confirm(callback: types.CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    token = callback.data.split("_", 3)[3]
    if token in NODES:
        delete_node(token)
        await callback.answer(_("node_deleted", lang, name="Node"), show_alert=False)
    await cq_node_delete_menu(callback)

async def cq_node_command(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    data = callback.data[9:] # remove node_cmd_
    token = data[:32]
    cmd = data[33:] # _command
    
    node = NODES.get(token)
    if not node: await callback.answer("Error", show_alert=True); return
    if cmd == "reboot": node["is_restarting"] = True
    
    # --- ЛОГИКА ТРАФИКА ---
    if cmd == "traffic":
        # Если это трафик - запускаем режим мониторинга
        # 1. Отправляем сообщение-заглушку с кнопкой "Стоп"
        stop_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("btn_stop_traffic", lang), callback_data=f"node_stop_traffic_{token}")]
        ])
        
        # Проверяем, не запущен ли уже монитор
        if user_id in NODE_TRAFFIC_MONITORS:
            # Если запущен для этой же ноды - просто обновим сообщение
            if NODE_TRAFFIC_MONITORS[user_id]["token"] == token:
                 pass # Уже работает
            else:
                 # Если для другой - остановим старый
                 del NODE_TRAFFIC_MONITORS[user_id]

        sent_msg = await callback.message.answer(
            _("traffic_start", lang, interval=config.TRAFFIC_INTERVAL), 
            reply_markup=stop_kb, 
            parse_mode="HTML"
        )
        
        # Сохраняем состояние
        NODE_TRAFFIC_MONITORS[user_id] = {
            "token": token,
            "message_id": sent_msg.message_id,
            "last_update": 0
        }
        
        # Отправляем первую команду немедленно
        if "tasks" not in node: node["tasks"] = []
        node["tasks"].append({"command": cmd, "user_id": user_id})
        
        await callback.answer()
        return
    # ----------------------

    if "tasks" not in node: node["tasks"] = []
    node["tasks"].append({"command": cmd, "user_id": user_id})
    
    cmd_map = {
        "selftest": "btn_selftest",
        "uptime": "btn_uptime",
        "traffic": "btn_traffic",
        "top": "btn_top",
        "speedtest": "btn_speedtest",
        "reboot": "btn_reboot"
    }
    btn_key = cmd_map.get(cmd)
    cmd_name = _(btn_key, lang) if btn_key else cmd
    await callback.answer(_("node_cmd_sent", lang, cmd=cmd_name, name=node.get("name")), show_alert=False)

async def cq_node_stop_traffic(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Получаем токен и имя ноды для уведомления
    token = callback.data.replace("node_stop_traffic_", "")
    node = NODES.get(token)
    node_name = node.get("name", "Unknown") if node else "Unknown"
    
    # Текст уведомления с именем ноды
    alert_text = _("node_traffic_stopped_alert", lang, name=node_name)

    if user_id in NODE_TRAFFIC_MONITORS:
        del NODE_TRAFFIC_MONITORS[user_id]
        try:
            await callback.message.delete()
            # Возвращаем меню управления этой нодой, если токен есть в callback
            if node:
                stats = node.get("stats", {})
                text = _("node_management_menu", lang, name=node.get("name"), ip=node.get("ip", "?"), uptime=stats.get("uptime", "?"))
                keyboard = get_node_management_keyboard(token, lang)
                await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

        except TelegramBadRequest:
            pass
    
    # Отправляем "тостер" уведомление (show_alert=False)
    await callback.answer(alert_text, show_alert=False)

async def node_traffic_scheduler(bot: Bot):
    """Периодически отправляет команды трафика на ноды для активных мониторов."""
    while True:
        try:
            await asyncio.sleep(config.TRAFFIC_INTERVAL)
            
            if not NODE_TRAFFIC_MONITORS:
                continue

            # Копируем, чтобы не сломать итерацию при удалении
            for user_id, monitor_data in list(NODE_TRAFFIC_MONITORS.items()):
                token = monitor_data.get("token")
                node = NODES.get(token)
                
                # Если нода удалена или не существует - убираем монитор
                if not node:
                    try:
                        del NODE_TRAFFIC_MONITORS[user_id]
                    except KeyError: pass
                    continue
                
                # Добавляем задачу в очередь ноды
                if "tasks" not in node: node["tasks"] = []
                node["tasks"].append({"command": "traffic", "user_id": user_id})
                
        except Exception as e:
            logging.error(f"Error in node_traffic_scheduler: {e}")
            await asyncio.sleep(5)

async def nodes_monitor(bot: Bot):
    """Следит за статусом нод и шлет алерты, если включено уведомление 'downtime'."""
    logging.info("Nodes Monitor started.")
    await asyncio.sleep(10) 
    
    while True:
        try:
            now = time.time()
            for token, node in list(NODES.items()):
                name = node.get("name", "Unknown")
                last_seen = node.get("last_seen", 0)
                is_restarting = node.get("is_restarting", False)
                
                is_dead = (now - last_seen >= NODE_OFFLINE_TIMEOUT) and (last_seen > 0)
                was_dead = node.get("is_offline_alert_sent", False)
                
                if is_dead and not was_dead and not is_restarting:
                    def msg_down_gen(lang):
                        fmt_time = datetime.fromtimestamp(last_seen).strftime('%H:%M:%S')
                        return _("alert_node_down", lang, name=name, last_seen=fmt_time)
                    await send_alert(bot, msg_down_gen, "downtime")
                    node["is_offline_alert_sent"] = True
                    logging.warning(f"Node {name} is DOWN. Alert sent.")
                    
                elif not is_dead and was_dead:
                    def msg_up_gen(lang):
                        return _("alert_node_up", lang, name=name)
                    await send_alert(bot, msg_up_gen, "downtime")
                    node["is_offline_alert_sent"] = False
                    logging.info(f"Node {name} recovered. Alert sent.")
                    
                if not is_dead and is_restarting:
                     node["is_restarting"] = False

        except Exception as e:
            logging.error(f"Error in nodes_monitor: {e}", exc_info=True)
        
        await asyncio.sleep(20)