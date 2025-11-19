import logging
import asyncio
from typing import Union, Callable
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .i18n import _, get_user_lang
from . import config
from .shared_state import LAST_MESSAGE_IDS, ALERTS_CONFIG

async def delete_previous_message(
        user_id: int,
        command,
        chat_id: int,
        bot: Bot):
    """
    Удаляет предыдущее сообщение бота по команде, чтобы не засорять чат.
    Использует LAST_MESSAGE_IDS для отслеживания ID сообщений.
    """
    cmds_to_delete = [command] if not isinstance(command, list) else command
    for cmd in cmds_to_delete:
        try:
            # Проверяем, есть ли сохраненный ID сообщения для этой команды
            if user_id in LAST_MESSAGE_IDS and cmd in LAST_MESSAGE_IDS[user_id]:
                msg_id = LAST_MESSAGE_IDS[user_id].pop(cmd)
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest as e:
            # Игнорируем ошибки, если сообщение уже удалено или его нельзя удалить
            if "message to delete not found" not in str(
                    e) and "message can't be deleted" not in str(e):
                logging.error(
                    f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")
        except Exception as e:
            logging.error(
                f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")

async def send_support_message(bot: Bot, user_id: int, lang: str):
    """
    Отправляет сообщение о поддержке проекта при первом старте (One-time message).
    """
    try:
        text = _("start_support_message", lang)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=_("start_support_button", lang),
                url="https://yoomoney.ru/to/410011639584793"
            )]
        ])

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(
            f"Не удалось отправить сообщение о поддержке пользователю {user_id}: {e}")

async def send_alert(bot: Bot, message_or_func: Union[str, Callable[[str], str]], alert_type: str):
    """
    Отправляет алерт всем пользователям, подписанным на alert_type.
    Поддерживает мультиязычность через передачу функции-генератора.

    :param bot: Экземпляр бота.
    :param message_or_func: 
        - Либо готовая строка (для совместимости/простых логов).
        - Либо функция (lang -> str), которая возвращает текст на нужном языке.
    :param alert_type: Тип уведомления (resources, logins, bans).
    """
    if not alert_type:
        logging.warning("send_alert вызван без указания alert_type")
        return

    sent_count = 0
    users_to_alert = []
    
    # Собираем список пользователей, у которых включен этот тип уведомлений
    for user_id, config_data in ALERTS_CONFIG.items():
        if config_data.get(alert_type, False):
            users_to_alert.append(user_id)

    if not users_to_alert:
        # Логируем на языке по умолчанию, так как получателей нет
        logging.info(_("alert_no_users_for_type",
                     config.DEFAULT_LANGUAGE, alert_type=alert_type))
        return

    logging.info(_("alert_sending_to_users", config.DEFAULT_LANGUAGE,
                 alert_type=alert_type, count=len(users_to_alert)))

    for user_id in users_to_alert:
        try:
            # --- МУЛЬТИЯЗЫЧНОСТЬ ---
            # Определяем язык конкретного пользователя
            lang = get_user_lang(user_id)
            
            if callable(message_or_func):
                # Если передана функция, вызываем её с языком пользователя
                text_to_send = message_or_func(lang)
            else:
                # Если строка - отправляем как есть
                text_to_send = message_or_func
            
            if not text_to_send:
                continue
            # -----------------------

            await bot.send_message(user_id, text_to_send, parse_mode="HTML")
            sent_count += 1
            # Небольшая задержка, чтобы не спамить API слишком быстро
            await asyncio.sleep(0.1)

        except TelegramBadRequest as e:
            if "chat not found" in str(e) or "bot was blocked by the user" in str(e):
                logging.warning(f"Не удалось отправить алерт пользователю {user_id}: чат не найден или бот заблокирован.")
            else:
                logging.error(f"Неизвестная ошибка TelegramBadRequest при отправке алерта {user_id}: {e}")
        except TelegramRetryAfter as e:
            # Если Telegram просит подождать (Flood Wait)
            logging.warning(f"send_alert: TelegramRetryAfter для {user_id}: Ждем {e.retry_after}с")
            await asyncio.sleep(e.retry_after)
            try:
                # Повторная попытка после ожидания
                if callable(message_or_func):
                    text_to_send = message_or_func(lang)
                else:
                    text_to_send = message_or_func

                await bot.send_message(user_id, text_to_send, parse_mode="HTML")
                sent_count += 1
            except Exception as retry_e:
                logging.error(f"Ошибка при повторной отправке алерта {user_id} после RetryAfter: {retry_e}")
        except Exception as e:
            logging.error(f"Ошибка при отправке алерта пользователю {user_id}: {e}")

    logging.info(_("alert_sent_to_users", config.DEFAULT_LANGUAGE,
                 alert_type=alert_type, count=sent_count))