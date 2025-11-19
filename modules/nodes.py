# /opt-tg-bot/modules/nodes.py
import time
import asyncio
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import LAST_MESSAGE_IDS, NODES
from core.nodes_db import create_node, delete_node
from core.keyboards import get_nodes_list_keyboard, get_node_management_keyboard, get_nodes_delete_keyboard, get_back_keyboard
from core.config import NODE_OFFLINE_TIMEOUT

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
    dp.callback_query(F.data.startswith("node_cmd_"))(cq_node_command)

# --- НОВОЕ: Фоновая задача для мониторинга статуса нод ---
def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    task = asyncio.create_task(nodes_monitor(bot), name="NodesMonitor")
    return [task]
# ---------------------------------------------------------

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
    if "tasks" not in node: node["tasks"] = []
    node["tasks"].append({"command": cmd, "user_id": user_id})
    await callback.answer(_("node_cmd_sent", lang, cmd=cmd, name=node.get("name")), show_alert=True)

# --- МОНИТОР ДАУНТАЙМА ---
async def nodes_monitor(bot: Bot):
    """Следит за статусом нод и шлет алерты, если включено уведомление 'downtime'."""
    logging.info("Nodes Monitor started.")
    await asyncio.sleep(10) # Даем время на инициализацию
    
    while True:
        try:
            now = time.time()
            # Копируем, чтобы избежать ошибок изменения размера словаря во время итерации
            for token, node in list(NODES.items()):
                name = node.get("name", "Unknown")
                last_seen = node.get("last_seen", 0)
                is_restarting = node.get("is_restarting", False)
                
                # Определяем текущий статус "мертва ли нода"
                # Нода мертва, если таймаут вышел И она вообще хоть раз выходила на связь (last_seen > 0)
                is_dead = (now - last_seen >= NODE_OFFLINE_TIMEOUT) and (last_seen > 0)
                
                # Проверяем, отправляли ли мы уже алерт о падении
                was_dead = node.get("is_offline_alert_sent", False)
                
                # СЦЕНАРИЙ 1: Нода упала (и это не перезагрузка, и алерт еще не слали)
                if is_dead and not was_dead and not is_restarting:
                    
                    # Формируем функцию генерации сообщения (для i18n)
                    def msg_down_gen(lang):
                        fmt_time = datetime.fromtimestamp(last_seen).strftime('%H:%M:%S')
                        return _("alert_node_down", lang, name=name, last_seen=fmt_time)
                    
                    # Отправляем алерт с типом 'downtime'
                    await send_alert(bot, msg_down_gen, "downtime")
                    
                    # Ставим флаг, что алерт отправлен
                    node["is_offline_alert_sent"] = True
                    logging.warning(f"Node {name} is DOWN. Alert sent.")
                    
                # СЦЕНАРИЙ 2: Нода ожила (была мертва, теперь alive)
                elif not is_dead and was_dead:
                    
                    # Формируем функцию для сообщения о восстановлении
                    def msg_up_gen(lang):
                        return _("alert_node_up", lang, name=name)
                        
                    await send_alert(bot, msg_up_gen, "downtime")
                    
                    # Сбрасываем флаг
                    node["is_offline_alert_sent"] = False
                    logging.info(f"Node {name} recovered. Alert sent.")
                    
                # СЦЕНАРИЙ 3: Если нода была помечена как перезагружающаяся, но вышла на связь
                if not is_dead and is_restarting:
                     # Снимаем флаг перезагрузки тихо (или можно тоже алерт отправить, если хочется)
                     node["is_restarting"] = False

        except Exception as e:
            logging.error(f"Error in nodes_monitor: {e}", exc_info=True)
        
        await asyncio.sleep(20) # Проверка каждые 20 секунд