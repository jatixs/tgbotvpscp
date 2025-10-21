# /opt/tg-bot/core/messaging.py
import logging
import asyncio
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from .shared_state import LAST_MESSAGE_IDS, ALERTS_CONFIG


async def delete_previous_message(
        user_id: int,
        command,
        chat_id: int,
        bot: Bot):
    cmds_to_delete = [command] if not isinstance(command, list) else command
    for cmd in cmds_to_delete:
        try:
            if user_id in LAST_MESSAGE_IDS and cmd in LAST_MESSAGE_IDS[user_id]:
                msg_id = LAST_MESSAGE_IDS[user_id].pop(cmd)
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest as e:
            if "message to delete not found" not in str(
                    e) and "message can't be deleted" not in str(e):
                logging.error(
                    f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")
        except Exception as e:
            logging.error(
                f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")


async def send_alert(bot: Bot, message: str, alert_type: str):
    if not alert_type:
        logging.warning("send_alert вызван без указания alert_type")
        return

    sent_count = 0
    users_to_alert = []
    for user_id, config in ALERTS_CONFIG.items():
        if config.get(alert_type, False):
            users_to_alert.append(user_id)

    if not users_to_alert:
        logging.info(
            f"Нет пользователей с включенными уведомлениями типа '{alert_type}'.")
        return

    logging.info(
        f"Отправка алерта типа '{alert_type}' {len(users_to_alert)} пользователям...")
    for user_id in users_to_alert:
        try:
            await bot.send_message(user_id, message, parse_mode="HTML")
            sent_count += 1
            await asyncio.sleep(0.1)
        except TelegramBadRequest as e:
            if "chat not found" in str(
                    e) or "bot was blocked by the user" in str(e):
                logging.warning(
                    f"Не удалось отправить алерт пользователю {user_id}: чат не найден или бот заблокирован.")
            else:
                logging.error(
                    f"Неизвестная ошибка TelegramBadRequest при отправке алерта {user_id}: {e}")
        except Exception as e:
            logging.error(
                f"Ошибка при отправке алерта пользователю {user_id}: {e}")

    logging.info(
        f"Алерт типа '{alert_type}' отправлен {sent_count} пользователям.")
