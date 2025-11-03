# /opt/tg-bot/core/messaging.py
import logging
import asyncio
from aiogram import Bot
# --- ИЗМЕНЕНО: Добавлены импорты ---
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# ---------------------------------

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from .i18n import _, get_user_lang
from . import config  # Нужен для DEFAULT_LANGUAGE
# ----------------------------------------

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


# --- НОВАЯ ФУНКЦИЯ ---
async def send_support_message(bot: Bot, user_id: int, lang: str):
    """
    Отправляет сообщение о поддержке проекта при первом старте.
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
            parse_mode="HTML"  # Важно для ссылки в тексте
        )
    except Exception as e:
        logging.error(
            f"Не удалось отправить сообщение о поддержке пользователю {user_id}: {e}")
# --- КОНЕЦ НОВОЙ ФУНКЦИИ ---


async def send_alert(bot: Bot, message: str, alert_type: str):
    if not alert_type:
        logging.warning("send_alert вызван без указания alert_type")
        return

    sent_count = 0
    users_to_alert = []
    for user_id, config_data in ALERTS_CONFIG.items(
    ):  # Переименовано во избежание конфликта
        if config_data.get(alert_type, False):
            users_to_alert.append(user_id)

    if not users_to_alert:
        # --- ИЗМЕНЕНО: Используем i18n (язык по умолчанию для логов) ---
        logging.info(_("alert_no_users_for_type",
                     config.DEFAULT_LANGUAGE, alert_type=alert_type))
        # -------------------------------------------------------------
        return

    # --- ИЗМЕНЕНО: Используем i18n (язык по умолчанию для логов) ---
    logging.info(_("alert_sending_to_users", config.DEFAULT_LANGUAGE,
                 alert_type=alert_type, count=len(users_to_alert)))
    # -------------------------------------------------------------

    for user_id in users_to_alert:
        try:
            # --- ИЗМЕНЕНО: Получаем язык пользователя и переводим сообщение ---
            # (Предполагается, что `message` изначально на языке по умолчанию)
            # Если `message` уже содержит ключ i18n, нужно будет переделать логику
            # Но сейчас алерты генерируются с уже готовым текстом на языке по умолчанию.
            # Мы просто отправляем этот текст. Для полноценного перевода алертов
            # нужно передавать ключ и параметры, а не готовый текст.
            # Пока оставим отправку оригинального сообщения.
            # lang = get_user_lang(user_id)
            # translated_message = _(key_from_message, lang, **params_from_message) # Примерно так
            # await bot.send_message(user_id, translated_message,
            # parse_mode="HTML")

            # ВРЕМЕННО: Отправляем оригинальное сообщение (которое на языке по
            # умолчанию)
            await bot.send_message(user_id, message, parse_mode="HTML")
            # ----------------------------------------------------------------------

            sent_count += 1
            await asyncio.sleep(0.1)  # Задержка остается
        except TelegramBadRequest as e:
            if "chat not found" in str(
                    e) or "bot was blocked by the user" in str(e):
                logging.warning(
                    f"Не удалось отправить алерт пользователю {user_id}: чат не найден или бот заблокирован.")
            else:
                logging.error(
                    f"Неизвестная ошибка TelegramBadRequest при отправке алерта {user_id}: {e}")
        except TelegramRetryAfter as e:  # Добавлена обработка RetryAfter
            logging.warning(
                f"send_alert: TelegramRetryAfter для {user_id}: Ждем {e.retry_after}с")
            await asyncio.sleep(e.retry_after)
            # Повторная попытка (опционально, можно просто пропустить)
            try:
                await bot.send_message(user_id, message, parse_mode="HTML")
                sent_count += 1
            except Exception as retry_e:
                logging.error(
                    f"Ошибка при повторной отправке алерта {user_id} после RetryAfter: {retry_e}")
        except Exception as e:
            logging.error(
                f"Ошибка при отправке алерта пользователю {user_id}: {e}")

    # --- ИЗМЕНЕНО: Используем i18n (язык по умолчанию для логов) ---
    logging.info(_("alert_sent_to_users", config.DEFAULT_LANGUAGE,
                 alert_type=alert_type, count=sent_count))
    # -------------------------------------------------------------
