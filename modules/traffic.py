# /opt/tg-bot/modules/traffic.py
import asyncio
import logging
import psutil
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, ReplyKeyboardRemove
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import (
    LAST_MESSAGE_IDS, TRAFFIC_MESSAGE_IDS, TRAFFIC_PREV
)
from core.utils import format_traffic
# --- ИЗМЕНЕНО: Импортируем get_main_reply_keyboard ---
from core.keyboards import get_main_reply_keyboard
# ----------------------------------------------------

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_traffic"
# --------------------------------

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(traffic_handler)
    # --------------------------------------

def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    """Возвращает фоновую задачу для запуска в main()"""
    task = asyncio.create_task(traffic_monitor(bot), name="TrafficMonitor")
    return [task]

async def traffic_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "traffic" # Имя команды оставляем
    if not is_allowed(user_id, command):
         await send_access_denied_message(message.bot, user_id, chat_id, command)
         return

    # Список всех команд для очистки LAST_MESSAGE_IDS (оставляем как есть)
    all_commands_to_delete = list(shared_state.LAST_MESSAGE_IDS.get(user_id, {}).keys())

    if user_id in TRAFFIC_MESSAGE_IDS:
        logging.info(f"Остановка мониторинга трафика для {user_id}")
        try:
            message_id = TRAFFIC_MESSAGE_IDS.pop(user_id)
            await message.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, KeyError) as e:
            logging.warning(f"Не удалось удалить сообщение трафика при остановке: {e}")
        
        TRAFFIC_PREV.pop(user_id, None)
        # Удаляем все предыдущие сообщения бота
        await delete_previous_message(user_id, all_commands_to_delete, chat_id, message.bot)
        
        # --- ИЗМЕНЕНО: Используем i18n ---
        sent_message = await message.answer(_("traffic_stop", lang), reply_markup=ReplyKeyboardRemove())
        
        # Отправляем новое сообщение с главным меню
        await message.answer(
            _("traffic_menu_return", lang),
            # Передаем user_id и buttons_map в get_main_reply_keyboard
            reply_markup=get_main_reply_keyboard(user_id, message.bot.buttons_map)
        )
        # --------------------------------
        
        # Не сохраняем ID для 'traffic stop'
        # LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id 

    else:
        logging.info(f"Запуск мониторинга трафика для {user_id}")
        # Удаляем все предыдущие сообщения бота
        await delete_previous_message(user_id, all_commands_to_delete, chat_id, message.bot)

        def get_initial_counters():
            return psutil.net_io_counters()

        try:
            counters = await asyncio.to_thread(get_initial_counters)
            TRAFFIC_PREV[user_id] = (counters.bytes_recv, counters.bytes_sent)
            # --- ИЗМЕНЕНО: Используем i18n ---
            msg_text = _("traffic_start", lang)
            # --------------------------------
            sent_message = await message.answer(msg_text, parse_mode="HTML")
            TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
            # Не сохраняем ID стартового сообщения трафика в LAST_MESSAGE_IDS
        except Exception as e:
            logging.error(f"Error starting traffic monitor for {user_id}: {e}")
            # --- ИЗМЕНЕНО: Используем i18n ---
            await message.answer(_("traffic_start_fail", lang, error=e))
            # --------------------------------

async def traffic_monitor(bot: Bot):
    await asyncio.sleep(TRAFFIC_INTERVAL)
    while True:
        current_users = list(TRAFFIC_MESSAGE_IDS.keys())
        if not current_users:
            await asyncio.sleep(TRAFFIC_INTERVAL)
            continue

        for user_id in current_users:
            if user_id not in TRAFFIC_MESSAGE_IDS: continue
            message_id = TRAFFIC_MESSAGE_IDS.get(user_id)
            if not message_id:
                logging.warning(f"Traffic monitor: Missing message ID for user {user_id}")
                TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                continue
                
            # --- ИЗМЕНЕНО: Получаем язык пользователя для обновления ---
            lang = get_user_lang(user_id)
            # --------------------------------------------------------

            try:
                def get_traffic_update():
                    counters_now = psutil.net_io_counters()
                    rx_now = counters_now.bytes_recv
                    tx_now = counters_now.bytes_sent
                    prev_rx, prev_tx = TRAFFIC_PREV.get(user_id, (rx_now, tx_now))
                    rx_delta = max(0, rx_now - prev_rx)
                    tx_delta = max(0, tx_now - prev_tx)
                    rx_speed = rx_delta * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                    tx_speed = tx_delta * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                    return rx_now, tx_now, rx_speed, tx_speed

                rx, tx, rx_speed, tx_speed = await asyncio.to_thread(get_traffic_update)
                TRAFFIC_PREV[user_id] = (rx, tx)

                # --- ИЗМЕНЕНО: Формируем текст с i18n ---
                msg_text = (f"{_('traffic_update_total', lang)}\n"
                            f"=========================\n"
                            f"{_('traffic_rx', lang, value=format_traffic(rx))}\n"
                            f"{_('traffic_tx', lang, value=format_traffic(tx))}\n\n"
                            f"{_('traffic_update_speed', lang)}\n"
                            f"=========================\n"
                            f"{_('traffic_speed_rx', lang, speed=rx_speed)}\n"
                            f"{_('traffic_speed_tx', lang, speed=tx_speed)}")
                # ---------------------------------------

                await bot.edit_message_text(chat_id=user_id, message_id=message_id, text=msg_text)

            except TelegramRetryAfter as e:
                logging.warning(f"Traffic Monitor: TelegramRetryAfter for {user_id}: Wait {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e): pass
                elif "message to edit not found" in str(e) or "chat not found" in str(e):
                    logging.warning(f"Traffic Monitor: Message/Chat not found for user {user_id}. Stopping monitor.")
                    TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                    TRAFFIC_PREV.pop(user_id, None)
                else:
                    logging.error(f"Traffic Monitor: Unexpected TelegramBadRequest for {user_id}: {e}")
                    TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                    TRAFFIC_PREV.pop(user_id, None)
            except Exception as e:
                logging.error(f"Traffic Monitor: Critical error updating for {user_id}: {e}")
                TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                TRAFFIC_PREV.pop(user_id, None)

        await asyncio.sleep(TRAFFIC_INTERVAL)