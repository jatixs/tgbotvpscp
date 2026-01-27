import asyncio
import logging
import psutil
import time
import json
import os
import glob
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from core.i18n import I18nFilter, get_user_lang, get_text
from core import config
from core import shared_state
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.utils import format_traffic
from core.keyboards import get_main_reply_keyboard

BUTTON_KEY = "btn_traffic"
MESSAGE_EDIT_THROTTLE = {}
MIN_UPDATE_INTERVAL = 2.0

# Global state for traffic offset
TRAFFIC_OFFSET = {"rx": 0, "tx": 0}
# Time of last restoration (module load)
STARTUP_TIME = time.time()
# Flag: was it a server reboot (True) or just a bot restart (False)
IS_SERVER_REBOOT = True 


def get_button() -> KeyboardButton:
    return KeyboardButton(text=get_text(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    # Handler for "Network Traffic" button in main menu
    dp.message(I18nFilter(BUTTON_KEY))(traffic_handler)
    
    # Callback handlers for monitoring control
    dp.callback_query(F.data == "stop_traffic")(stop_traffic_handler)
    
    # Technical handlers (stats reset)
    dp.callback_query(F.data == "reset_traffic_stats")(reset_stats_handler)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    load_traffic_state()
    monitor_task = asyncio.create_task(traffic_monitor(bot), name="TrafficMonitor")
    backup_task = asyncio.create_task(periodic_backup_task(), name="TrafficBackup")
    return [monitor_task, backup_task]


def get_current_traffic_total():
    """
    Returns tuple (rx_total, tx_total) considering offset.
    Used here, in WebUI, and selftest.
    """
    counters = psutil.net_io_counters()
    rx_total = TRAFFIC_OFFSET["rx"] + counters.bytes_recv
    tx_total = TRAFFIC_OFFSET["tx"] + counters.bytes_sent
    # Protection against negative values
    return max(0, rx_total), max(0, tx_total)


def load_traffic_state():
    """Loads the last backup and calculates offset at startup."""
    global TRAFFIC_OFFSET, IS_SERVER_REBOOT
    try:
        backups = sorted(glob.glob(os.path.join(config.TRAFFIC_BACKUP_DIR, "traffic_backup_*.json")))
        if not backups:
            logging.info("No traffic backups found. Starting from scratch.")
            IS_SERVER_REBOOT = True
            return

        last_backup_path = backups[-1]
        with open(last_backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        backup_rx = data.get("rx", 0)
        backup_tx = data.get("tx", 0)
        backup_boot_time = data.get("boot_time", 0)
        
        current_boot_time = psutil.boot_time()
        
        # If system boot time matches (means only bot restarted)
        if abs(current_boot_time - backup_boot_time) < 5:
            counters = psutil.net_io_counters()
            TRAFFIC_OFFSET["rx"] = backup_rx - counters.bytes_recv
            TRAFFIC_OFFSET["tx"] = backup_tx - counters.bytes_sent
            
            IS_SERVER_REBOOT = False # Just a bot restart
            logging.info(f"Traffic state restored (Bot restart). Offset updated. Reset button hidden.")
        else:
            # Server was rebooted (system counters reset)
            TRAFFIC_OFFSET["rx"] = backup_rx
            TRAFFIC_OFFSET["tx"] = backup_tx
            
            IS_SERVER_REBOOT = True # Server reboot
            logging.info(f"Traffic state restored (Server reboot). Offset set to last backup values.")

    except Exception as e:
        logging.error(f"Failed to load traffic state: {e}")
        IS_SERVER_REBOOT = True # Treat as clean start on error


def save_backup_file(rx, tx):
    """
    Saves current state to file and rotates backups.
    Called from periodic_backup_task and manually from backups module.
    """
    timestamp = int(time.time())
    filename = f"traffic_backup_{timestamp}.json"
    filepath = os.path.join(config.TRAFFIC_BACKUP_DIR, filename)
    
    data = {
        "timestamp": timestamp,
        "date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
        "rx": rx,
        "tx": tx,
        "boot_time": psutil.boot_time()
    }
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        
        # Rotation: keep last 5
        backups = sorted(glob.glob(os.path.join(config.TRAFFIC_BACKUP_DIR, "traffic_backup_*.json")))
        while len(backups) > 5:
            os.remove(backups[0])
            backups.pop(0)
    except Exception as e:
        logging.error(f"Error saving traffic backup: {e}")


def can_reset_traffic() -> bool:
    """
    Checks if traffic reset button can be shown.
    Returns True only if:
    1. Server reboot occurred (IS_SERVER_REBOOT = True)
    2. Less than 10 minutes passed since start (600 sec)
    """
    return IS_SERVER_REBOOT and (time.time() - STARTUP_TIME) < 600


async def periodic_backup_task():
    """Background task: auto-backup every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        rx, tx = get_current_traffic_total()
        await asyncio.to_thread(save_backup_file, rx, tx)


async def traffic_handler(message: types.Message):
    """Start active traffic monitor."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "traffic"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    
    # Clear old monitor messages
    if user_id in shared_state.TRAFFIC_MESSAGE_IDS:
        msg_id = shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
        shared_state.TRAFFIC_PREV.pop(user_id, None)
        if msg_id:
            try:
                await message.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
    await delete_previous_message(
        user_id,
        list(shared_state.LAST_MESSAGE_IDS.get(user_id, {}).keys()),
        chat_id,
        message.bot,
    )

    try:
        counters = await asyncio.to_thread(psutil.net_io_counters)
        shared_state.TRAFFIC_PREV[user_id] = (counters.bytes_recv, counters.bytes_sent)
        
        row_actions = [InlineKeyboardButton(text=get_text("btn_stop_traffic", lang), callback_data="stop_traffic")]
        
        # Check condition for reset button
        if can_reset_traffic():
            row_actions.append(InlineKeyboardButton(text=get_text("btn_reset_traffic", lang), callback_data="reset_traffic_stats"))
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=[row_actions])
        msg_text = get_text("traffic_start", lang, interval=config.TRAFFIC_INTERVAL)
        sent_message = await message.answer(
            msg_text, reply_markup=keyboard, parse_mode="HTML"
        )
        shared_state.TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
        MESSAGE_EDIT_THROTTLE[sent_message.message_id] = time.time()
    except Exception as e:
        logging.error(f"Error starting traffic monitor for {user_id}: {e}")
        await message.answer(get_text("traffic_start_fail", lang, error=e))


async def stop_traffic_handler(callback: types.CallbackQuery):
    """Stop monitor."""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    lang = get_user_lang(user_id)
    bot = callback.bot
    message_id_to_delete = shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
    shared_state.TRAFFIC_PREV.pop(user_id, None)
    if message_id_to_delete:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
            
            reply_markup = get_main_reply_keyboard(user_id)
            sent_menu_message = await callback.message.answer(
                get_text("traffic_menu_return", lang), reply_markup=reply_markup
            )
            shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})["menu"] = sent_menu_message.message_id
        except Exception as e:
            logging.debug(f"Error stopping traffic (delete msg): {e}")
    else:
        await callback.answer(get_text("traffic_stopped_alert", lang))


async def traffic_monitor(bot: Bot):
    """Background cycle for updating monitor messages."""
    await asyncio.sleep(config.TRAFFIC_INTERVAL)
    while True:
        current_users = list(shared_state.TRAFFIC_MESSAGE_IDS.keys())
        if not current_users:
            await asyncio.sleep(config.TRAFFIC_INTERVAL)
            continue
            
        try:
            counters_now = psutil.net_io_counters()
            rx_total, tx_total = get_current_traffic_total()
        except Exception:
            await asyncio.sleep(1)
            continue

        for user_id in current_users:
            if user_id not in shared_state.TRAFFIC_MESSAGE_IDS:
                continue
            message_id = shared_state.TRAFFIC_MESSAGE_IDS.get(user_id)
            if not message_id:
                continue
            
            now = time.time()
            last_update = MESSAGE_EDIT_THROTTLE.get(message_id, 0)
            effective_interval = max(config.TRAFFIC_INTERVAL, MIN_UPDATE_INTERVAL)
            if now - last_update < effective_interval:
                continue
            
            lang = get_user_lang(user_id)
            try:
                rx_now = counters_now.bytes_recv
                tx_now = counters_now.bytes_sent
                prev_rx, prev_tx = shared_state.TRAFFIC_PREV.get(user_id, (rx_now, tx_now))
                
                rx_delta = rx_now - prev_rx if rx_now >= prev_rx else rx_now
                tx_delta = tx_now - prev_tx if tx_now >= prev_tx else tx_now
                interval = max(effective_interval, 1)
                rx_speed = rx_delta * 8 / (1024 * 1024) / interval
                tx_speed = tx_delta * 8 / (1024 * 1024) / interval
                
                shared_state.TRAFFIC_PREV[user_id] = (rx_now, tx_now)
                
                row_actions = [InlineKeyboardButton(text=get_text("btn_stop_traffic", lang), callback_data="stop_traffic")]
                
                # Check condition for reset button in live-mode
                if can_reset_traffic():
                    row_actions.append(InlineKeyboardButton(text=get_text("btn_reset_traffic", lang), callback_data="reset_traffic_stats"))
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[row_actions])

                msg_text = f"{get_text('traffic_update_total', lang)}\n=========================\n"
                msg_text += f"{get_text('traffic_rx', lang, value=format_traffic(rx_total, lang))}\n"
                msg_text += f"{get_text('traffic_tx', lang, value=format_traffic(tx_total, lang))}\n\n"
                msg_text += f"{get_text('traffic_update_speed', lang)}\n=========================\n"
                msg_text += f"{get_text('traffic_speed_rx', lang, speed=rx_speed)}\n{get_text('traffic_speed_tx', lang, speed=tx_speed)}"

                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=msg_text,
                    reply_markup=keyboard,
                )
                MESSAGE_EDIT_THROTTLE[message_id] = now
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    continue
                shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
            except Exception as e:
                logging.error(f"Traffic monitor generic error: {e}")
                shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
        await asyncio.sleep(1)


async def reset_stats_handler(callback: types.CallbackQuery):
    """Statistics reset: deletes backup files and resets offset."""
    # Additional server-side check before execution
    if not can_reset_traffic():
        await callback.answer("Reset not allowed or time expired", show_alert=True)
        return
        
    global TRAFFIC_OFFSET
    TRAFFIC_OFFSET["rx"] = 0
    TRAFFIC_OFFSET["tx"] = 0
    
    try:
        files = glob.glob(os.path.join(config.TRAFFIC_BACKUP_DIR, "traffic_backup_*.json"))
        for f in files:
            os.remove(f)
    except Exception:
        pass
    
    await callback.answer(get_text("traffic_reset_done", get_user_lang(callback.from_user.id)))