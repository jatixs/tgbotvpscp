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
    pass


async def send_support_message(bot: Bot, user_id: int, lang: str):
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


async def send_alert(
        bot: Bot, message_or_func: Union[str, Callable[[str], str]], alert_type: str):
    if not alert_type:
        logging.warning("send_alert вызван без указания alert_type")
        return

    sent_count = 0
    users_to_alert = []

    for user_id, config_data in ALERTS_CONFIG.items():
        if config_data.get(alert_type, False):
            users_to_alert.append(user_id)

    if not users_to_alert:
        logging.info(_("alert_no_users_for_type",
                     config.DEFAULT_LANGUAGE, alert_type=alert_type))
        return

    logging.info(_("alert_sending_to_users", config.DEFAULT_LANGUAGE,
                 alert_type=alert_type, count=len(users_to_alert)))

    for user_id in users_to_alert:
        try:
            lang = get_user_lang(user_id)

            if callable(message_or_func):
                text_to_send = message_or_func(lang)
            else:
                text_to_send = message_or_func

            if not text_to_send:
                continue

            await bot.send_message(user_id, text_to_send, parse_mode="HTML")
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
        except TelegramRetryAfter as e:
            logging.warning(
                f"send_alert: TelegramRetryAfter для {user_id}: Ждем {e.retry_after}с")
            await asyncio.sleep(e.retry_after)
            try:
                if callable(message_or_func):
                    text_to_send = message_or_func(lang)
                else:
                    text_to_send = message_or_func

                await bot.send_message(user_id, text_to_send, parse_mode="HTML")
                sent_count += 1
            except Exception as retry_e:
                logging.error(
                    f"Ошибка при повторной отправке алерта {user_id} после RetryAfter: {retry_e}")
        except Exception as e:
            logging.error(
                f"Ошибка при отправке алерта пользователю {user_id}: {e}")

    logging.info(_("alert_sent_to_users", config.DEFAULT_LANGUAGE,
                 alert_type=alert_type, count=sent_count))