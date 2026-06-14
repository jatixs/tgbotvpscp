import asyncio
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramNetworkError
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS, OPTIMIZE_STATE
from core.utils import escape_html

BUTTON_KEY = "btn_optimize"

OPT_MODULES = [
    {
        "id": 0,
        "key": "opt_cmd_0",
        "script": "apt update && apt full-upgrade -y && apt autoremove --purge -y && apt autoclean -y"
    },
    {
        "id": 1,
        "key": "opt_cmd_1",
        "script": "journalctl --vacuum-time=2d && rm -rf /var/tmp/* /tmp/* /root/.cache/*"
    },
    {
        "id": 2,
        "key": "opt_cmd_2",
        "script": "apt autoremove --purge snapd -y && rm -rf /var/cache/snapd/ && rm -rf ~/snap"
    },
    {
        "id": 3,
        "key": "opt_cmd_3",
        "script": "DEBIAN_FRONTEND=noninteractive apt install preload cpufrequtils zram-tools -y\nsystemctl enable preload && systemctl start preload"
    },
    {
        "id": 4,
        "key": "opt_cmd_4",
        "script": "sed -i '/vm.swappiness/d' /etc/sysctl.conf\nsed -i '/vm.vfs_cache_pressure/d' /etc/sysctl.conf\nsed -i '/net.core.default_qdisc/d' /etc/sysctl.conf\nsed -i '/net.ipv4.tcp_congestion_control/d' /etc/sysctl.conf\necho 'vm.swappiness=10' >> /etc/sysctl.conf\necho 'vm.vfs_cache_pressure=50' >> /etc/sysctl.conf\necho 'net.core.default_qdisc=fq' >> /etc/sysctl.conf\necho 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf\nsysctl -p"
    },
    {
        "id": 5,
        "key": "opt_cmd_5",
        "script": "sed -i '/^UseDNS/d' /etc/ssh/sshd_config\nsed -i 's/#UseDNS yes/UseDNS no/' /etc/ssh/sshd_config\necho 'UseDNS no' >> /etc/ssh/sshd_config\nsystemctl restart ssh"
    },
    {
        "id": 6,
        "key": "opt_cmd_6",
        "script": "if [ -f /etc/nginx/nginx.conf ]; then\n    sed -i 's/worker_processes.*/worker_processes auto;/' /etc/nginx/nginx.conf\n    sed -i 's/worker_connections.*/worker_connections 2048;/' /etc/nginx/nginx.conf\n    systemctl restart nginx\nfi"
    },
    {
        "id": 7,
        "key": "opt_cmd_7",
        "script": "systemctl restart systemd-journald && systemctl daemon-reexec"
    }
]


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(optimize_handler)
    dp.callback_query(F.data.startswith("opt_toggle_"))(optimize_toggle_callback)
    dp.callback_query(F.data == "opt_exec_all")(optimize_exec_all_callback)
    dp.callback_query(F.data == "opt_exec_sel")(optimize_exec_sel_callback)

def get_optimize_keyboard(user_id: int, lang: str) -> InlineKeyboardMarkup:
    # Initialize state if not present (default True for all)
    if user_id not in OPTIMIZE_STATE:
        OPTIMIZE_STATE[user_id] = {m["id"]: True for m in OPT_MODULES}
    
    state = OPTIMIZE_STATE[user_id]
    inline_keyboard = []
    
    for m in OPT_MODULES:
        is_checked = state.get(m["id"], True)
        icon = "✅" if is_checked else "❌"
        text = f"{icon} {_(m['key'], lang)}"
        inline_keyboard.append([InlineKeyboardButton(text=text, callback_data=f"opt_toggle_{m['id']}")])
        
    inline_keyboard.append([
        InlineKeyboardButton(text=str(_("opt_btn_exec_all", lang)), callback_data="opt_exec_all")
    ])
    inline_keyboard.append([
        InlineKeyboardButton(text=str(_("opt_btn_exec_sel", lang)), callback_data="opt_exec_sel")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def optimize_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "optimize"
    
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
        
    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    keyboard = get_optimize_keyboard(user_id, lang)
    sent_message = await message.answer(_("optimize_menu_title", lang), reply_markup=keyboard, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def optimize_toggle_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    
    try:
        mod_id = int(callback.data.split("_")[2])
    except ValueError:
        await callback.answer()
        return
        
    if user_id not in OPTIMIZE_STATE:
        OPTIMIZE_STATE[user_id] = {m["id"]: True for m in OPT_MODULES}
        
    OPTIMIZE_STATE[user_id][mod_id] = not OPTIMIZE_STATE[user_id].get(mod_id, True)
    
    keyboard = get_optimize_keyboard(user_id, lang)
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass
    await callback.answer()

async def optimize_exec_all_callback(callback: types.CallbackQuery):
    await _execute_optimization(callback, [m["id"] for m in OPT_MODULES])
    
async def optimize_exec_sel_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    state = OPTIMIZE_STATE.get(user_id, {})
    selected = [m["id"] for m in OPT_MODULES if state.get(m["id"], True)]
    
    if not selected:
        lang = get_user_lang(user_id)
        # Using a generic fallback since specific string wasn't requested for this
        await callback.answer("Ничего не выбрано!" if lang == "ru" else "Nothing selected!", show_alert=True)
        return
        
    await _execute_optimization(callback, selected)

async def _execute_optimization(callback: types.CallbackQuery, selected_ids: list):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    lang = get_user_lang(user_id)
    command = "optimize"
    
    if not is_allowed(user_id, command):
        await send_access_denied_message(callback.bot, user_id, chat_id, command)
        await callback.answer()
        return

    # Delete the menu message
    try:
        await callback.message.delete()
        LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
    except Exception:
        pass
        
    sent_message = await callback.message.answer(_("optimize_start", lang), parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    
    script_parts = []
    for m in OPT_MODULES:
        if m["id"] in selected_ids:
            script_parts.append(m["script"])
            
    optimization_script = "\n\n".join(script_parts)
    
    process = await asyncio.create_subprocess_exec(
        "bash", "-c", optimization_script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    output = stdout.decode("utf-8", errors="ignore")
    error_output = stderr.decode("utf-8", errors="ignore")
    
    try:
        await callback.bot.delete_message(
            chat_id=chat_id, message_id=sent_message.message_id
        )
        LAST_MESSAGE_IDS.get(user_id, {}).pop(command, None)
    except Exception as e:
        logging.debug(f"Failed to delete optimize start message: {e}")
        
    if process.returncode == 0:
        response_text = _("optimize_success", lang, output=escape_html(output[-1000:]))
    else:
        response_text = _(
            "optimize_fail",
            lang,
            code=process.returncode,
            stdout=escape_html(output[-1000:]),
            stderr=escape_html(error_output[-2000:]),
        )
        
    try:
        sent_message_final = await callback.message.answer(response_text, parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id
    except (TelegramNetworkError, OSError):
        logging.warning("Оптимизация: бот перезагружен системой, ответ не отправлен.")
    except Exception as e:
        logging.error(f"Ошибка отправки отчета оптимизации: {e}")
        
    await callback.answer()
