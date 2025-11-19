import time
import asyncio
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
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
    
    # Add flow
    dp.callback_query(F.data == "node_add_new")(cq_add_node_start)
    dp.message(StateFilter(AddNodeStates.waiting_for_name))(process_node_name)
    
    # Delete flow
    dp.callback_query(F.data == "node_delete_menu")(cq_node_delete_menu)
    dp.callback_query(F.data.startswith("node_delete_confirm_"))(cq_node_delete_confirm)
    
    # Management
    dp.callback_query(F.data.startswith("node_select_"))(cq_node_select)
    dp.callback_query(F.data.startswith("node_cmd_"))(cq_node_command)


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
    
    sent_message = await message.answer(
        _("nodes_menu_header", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_nodes_list_refresh(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    prepared_nodes = _prepare_nodes_data()
    keyboard = get_nodes_list_keyboard(prepared_nodes, lang)
    
    try:
        await callback.message.edit_text(
             _("nodes_menu_header", lang),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()

def _prepare_nodes_data():
    result = {}
    now = time.time()
    
    for token, node in NODES.items():
        last_seen = node.get("last_seen", 0)
        is_restarting = node.get("is_restarting", False)
        
        if is_restarting:
            icon = "🔵"
        elif now - last_seen < NODE_OFFLINE_TIMEOUT:
            icon = "🟢"
        else:
            icon = "🔴"
            
        result[token] = {
            "name": node.get("name", "Unknown"),
            "status_icon": icon
        }
    return result

# --- Selection / Management ---

async def cq_node_select(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_", 2)[2]
    
    node = NODES.get(token)
    if not node:
        await callback.answer("Node not found", show_alert=True)
        return

    now = time.time()
    last_seen = node.get("last_seen", 0)
    is_restarting = node.get("is_restarting", False)
    
    if is_restarting:
        await callback.answer(
            _("node_restarting_alert", lang, name=node.get("name")),
            show_alert=True
        )
        return

    if now - last_seen >= NODE_OFFLINE_TIMEOUT:
        stats = node.get("stats", {})
        formatted_time = datetime.fromtimestamp(last_seen).strftime('%Y-%m-%d %H:%M:%S') if last_seen > 0 else "Never"
        
        text = _("node_details_offline", lang,
                 name=node.get("name"),
                 last_seen=formatted_time,
                 ip=node.get("ip", "Unknown"),
                 cpu=stats.get("cpu", "?"),
                 ram=stats.get("ram", "?"),
                 disk=stats.get("disk", "?"))
                 
        back_kb = get_back_keyboard(lang, "nodes_list_refresh")
        
        await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        return

    stats = node.get("stats", {})
    uptime_val = stats.get("uptime", "Unknown")
    
    text = _("node_management_menu", lang,
             name=node.get("name"),
             ip=node.get("ip", "Unknown"),
             uptime=uptime_val)
             
    keyboard = get_node_management_keyboard(token, lang)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# --- Add Node Flow ---

async def cq_add_node_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    # Простое сообщение с просьбой ввести имя
    await callback.message.edit_text(
        "Введите имя для новой ноды (на английском или русском):", 
        reply_markup=get_back_keyboard(lang, "nodes_list_refresh")
    )
    await state.set_state(AddNodeStates.waiting_for_name)
    await callback.answer()

async def process_node_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    name = message.text.strip()
    
    token = create_node(name)
    
    await message.answer(
        _("node_add_success_token", lang, name=name, token=token),
        parse_mode="HTML"
    )
    # Показываем токен и все, пользователь сам вернется в меню
    await state.clear()


# --- Delete Node Flow ---

async def cq_node_delete_menu(callback: types.CallbackQuery):
    """Показывает список нод для удаления."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    prepared_nodes = _prepare_nodes_data() # Используем те же данные (имя и статус не важен, главное имя)
    keyboard = get_nodes_delete_keyboard(prepared_nodes, lang)
    
    await callback.message.edit_text(
        _("node_delete_select", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

async def cq_node_delete_confirm(callback: types.CallbackQuery):
    """Удаляет ноду и обновляет список."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    token = callback.data.split("_", 3)[3] # node_delete_confirm_TOKEN
    
    node = NODES.get(token)
    if node:
        name = node.get("name")
        delete_node(token)
        await callback.answer(
            _("node_deleted", lang, name=name),
            show_alert=False
        )
    
    # Возвращаемся к списку удаления (обновленному)
    await cq_node_delete_menu(callback)


# --- Commands ---

async def cq_node_command(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    prefix = "node_cmd_"
    data = callback.data[len(prefix):]
    
    token = data[:32]
    cmd = data[33:]
    
    node = NODES.get(token)
    if not node:
        await callback.answer("Node error", show_alert=True)
        return

    if cmd == "reboot":
        node["is_restarting"] = True
    
    if "tasks" not in node:
        node["tasks"] = []
    
    node["tasks"].append({"command": cmd, "user_id": user_id})
    
    await callback.answer(
        _("node_cmd_sent", lang, cmd=cmd, name=node.get("name")),
        show_alert=True
    )