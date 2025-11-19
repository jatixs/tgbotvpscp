import asyncio
import logging
import psutil
import time
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from core.i18n import I18nFilter, get_user_lang, get_text
from core import config
from core.config import TRAFFIC_INTERVAL
from core import shared_state

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.utils import format_traffic
from core.keyboards import get_main_reply_keyboard

BUTTON_KEY = "btn_traffic"
# Словарь для контроля частоты обновления сообщений (троттлинг)
MESSAGE_EDIT_THROTTLE = {}
# Минимальный интервал (в секундах) между редактированием одного и того же сообщения
MIN_UPDATE_INTERVAL = 2.0

def get_button() -> KeyboardButton:
    return KeyboardButton(text=get_text(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(traffic_handler)
    dp.callback_query(F.data == "stop_traffic")(stop_traffic_handler)

def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    task = asyncio.create_task(traffic_monitor(bot), name="TrafficMonitor")
    return [task]

async def traffic_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "traffic"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    if user_id in shared_state.TRAFFIC_MESSAGE_IDS:
        logging.info(
            f"Мониторинг трафика уже активен для {user_id}. Перезапускаем...")
        message_id_to_delete = shared_state.TRAFFIC_MESSAGE_IDS.pop(
            user_id, None)
        shared_state.TRAFFIC_PREV.pop(user_id, None)
        if message_id_to_delete:
            try:
                await message.bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
            except TelegramBadRequest as e:
                logging.warning(
                    f"Не удалось удалить старое сообщение трафика ({message_id_to_delete}) при перезапуске: {e}")
            except Exception as e:
                logging.error(
                    f"Ошибка при удалении старого сообщения трафика для {user_id} при перезапуске: {e}")

    logging.info(f"Запуск мониторинга трафика для {user_id}")
    await delete_previous_message(user_id, list(shared_state.LAST_MESSAGE_IDS.get(user_id, {}).keys()), chat_id, message.bot)

    def get_initial_counters():
        return psutil.net_io_counters()

    try:
        counters = await asyncio.to_thread(get_initial_counters)
        shared_state.TRAFFIC_PREV[user_id] = (
            counters.bytes_recv, counters.bytes_sent)

        stop_button = InlineKeyboardButton(
            text=get_text("btn_stop_traffic", lang),
            callback_data="stop_traffic"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[stop_button]])

        msg_text = get_text("traffic_start", lang, interval=TRAFFIC_INTERVAL)
        sent_message = await message.answer(msg_text, reply_markup=keyboard, parse_mode="HTML")

        shared_state.TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
        MESSAGE_EDIT_THROTTLE[sent_message.message_id] = time.time()

    except Exception as e:
        logging.error(f"Error starting traffic monitor for {user_id}: {e}")
        await message.answer(get_text("traffic_start_fail", lang, error=e))

async def stop_traffic_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    lang = get_user_lang(user_id)
    bot = callback.bot

    logging.info(f"Остановка мониторинга трафика для {user_id} через кнопку.")

    message_id_to_delete = shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
    shared_state.TRAFFIC_PREV.pop(user_id, None)

    delete_success = False
    if message_id_to_delete:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
            await callback.answer(get_text("traffic_stopped_alert", lang))
            delete_success = True
        except TelegramBadRequest as e:
            logging.warning(
                f"Не удалось удалить сообщение трафика ({message_id_to_delete}) при остановке: {e}")
            await callback.answer(get_text("traffic_stopped_alert", lang))
        except Exception as e:
            logging.error(f"Ошибка при остановке трафика для {user_id}: {e}")
            await callback.answer(get_text("error_unexpected", lang), show_alert=True)
            return
    else:
        logging.warning(
            f"Не найден ID сообщения для остановки трафика у {user_id}")
        await callback.answer(get_text("traffic_stopped_alert", lang))
        delete_success = True

    if delete_success:
        try:
            buttons_map = getattr(
                bot, 'buttons_map', {
                    "user": [], "admin": [], "root": []})
            reply_markup = get_main_reply_keyboard(user_id, buttons_map)
            sent_menu_message = await callback.message.answer(
                get_text("traffic_menu_return", lang),
                reply_markup=reply_markup
            )
            shared_state.LAST_MESSAGE_IDS.setdefault(
                user_id, {})["menu"] = sent_menu_message.message_id

        except AttributeError as ae:
            logging.error(
                f"Не удалось получить buttons_map из bot: {ae}. Не могу отправить главное меню.")
        except Exception as e:
            logging.error(
                f"Не удалось отправить главное меню после остановки трафика: {e}")

async def traffic_monitor(bot: Bot):
    await asyncio.sleep(TRAFFIC_INTERVAL)
    while True:
        current_users = list(shared_state.TRAFFIC_MESSAGE_IDS.keys())
        if not current_users:
            await asyncio.sleep(TRAFFIC_INTERVAL)
            continue

        for user_id in current_users:
            if user_id not in shared_state.TRAFFIC_MESSAGE_IDS:
                continue

            message_id = shared_state.TRAFFIC_MESSAGE_IDS.get(user_id)
            if not message_id:
                logging.warning(
                    f"Traffic monitor: ID сообщения None для user {user_id}, пропускаем.")
                shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                shared_state.TRAFFIC_PREV.pop(user_id, None)
                continue
            
            # Троттлинг: проверяем время последнего обновления
            now = time.time()
            last_update = MESSAGE_EDIT_THROTTLE.get(message_id, 0)
            # Используем большее значение: настройку из конфига или минимальный безопасный интервал
            effective_interval = max(config.TRAFFIC_INTERVAL, MIN_UPDATE_INTERVAL)

            if (now - last_update) < effective_interval:
                continue

            lang = get_user_lang(user_id)

            try:
                def get_traffic_update():
                    counters_now = psutil.net_io_counters()
                    rx_now = counters_now.bytes_recv
                    tx_now = counters_now.bytes_sent
                    prev_rx, prev_tx = shared_state.TRAFFIC_PREV.get(
                        user_id, (rx_now, tx_now))
                    rx_delta = rx_now - prev_rx if rx_now >= prev_rx else rx_now
                    tx_delta = tx_now - prev_tx if tx_now >= prev_tx else tx_now
                    interval = max(effective_interval, 1)
                    rx_speed = rx_delta * 8 / (1024 * 1024) / interval
                    tx_speed = tx_delta * 8 / (1024 * 1024) / interval
                    return rx_now, tx_now, rx_speed, tx_speed

                rx, tx, rx_speed, tx_speed = await asyncio.to_thread(get_traffic_update)
                shared_state.TRAFFIC_PREV[user_id] = (rx, tx)

                stop_button = InlineKeyboardButton(
                    text=get_text("btn_stop_traffic", lang),
                    callback_data="stop_traffic"
                )
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[stop_button]])

                msg_text = (
                    f"{get_text('traffic_update_total', lang)}\n"
                    f"=========================\n"
                    f"{get_text('traffic_rx', lang, value=format_traffic(rx, lang))}\n"
                    f"{get_text('traffic_tx', lang, value=format_traffic(tx, lang))}\n\n"
                    f"{get_text('traffic_update_speed', lang)}\n"
                    f"=========================\n"
                    f"{get_text('traffic_speed_rx', lang, speed=rx_speed)}\n"
                    f"{get_text('traffic_speed_tx', lang, speed=tx_speed)}")

                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text=msg_text,
                    reply_markup=keyboard
                )
                MESSAGE_EDIT_THROTTLE[message_id] = now

            except TelegramRetryAfter as e:
                logging.warning(
                    f"Traffic Monitor: TelegramRetryAfter for {user_id}: Wait {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "message to edit not found" in str(
                        e).lower() or "chat not found" in str(e).lower():
                    logging.warning(
                        f"Traffic Monitor: Message/Chat not found for user {user_id}. Stopping monitor.")
                    shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                    shared_state.TRAFFIC_PREV.pop(user_id, None)
                elif "message is not modified" in str(e).lower():
                    pass
                else:
                    logging.error(
                        f"Traffic Monitor: Unexpected TelegramBadRequest for {user_id}: {e}. Stopping monitor.")
                    shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                    shared_state.TRAFFIC_PREV.pop(user_id, None)
            except Exception as e:
                logging.error(
                    f"Traffic Monitor: Critical error updating for {user_id}: {e}. Stopping monitor.")
                shared_state.TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                shared_state.TRAFFIC_PREV.pop(user_id, None)

        await asyncio.sleep(1)