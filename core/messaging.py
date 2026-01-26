import logging
import asyncio
import time
import uuid
from typing import Union, Callable
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .i18n import _, get_user_lang, STRINGS
from . import config
from .shared_state import LAST_MESSAGE_IDS, ALERTS_CONFIG
from . import shared_state


async def delete_previous_message(user_id: int, command, chat_id: int, bot: Bot):
    pass


async def send_support_message(bot: Bot, user_id: int, lang: str):
    try:
        text = _("start_support_message", lang)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_("start_support_button", lang),
                        url="https://yoomoney.ru/to/410011639584793",
                    )
                ]
            ]
        )
        await bot.send_message(
            chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="HTML"
        )
    except Exception as e:
        logging.error(
            f"Не удалось отправить сообщение о поддержке пользователю {user_id}: {e}"
        )


async def send_alert(
    bot: Bot,
    message_or_func: Union[str, Callable[[str], str]],
    alert_type: str,
    node_token: str = None,
    **kwargs,
):
    if not alert_type:
        logging.warning("send_alert вызван без указания alert_type")
        return

    users_to_alert = []
    for uid, cfg in ALERTS_CONFIG.items():
        is_enabled = cfg.get(alert_type, False)

        if node_token:
            override_key = f"node_{node_token}_{alert_type}"
            if override_key in cfg:
                is_enabled = cfg[override_key]

        if is_enabled:
            users_to_alert.append(uid)

    if not users_to_alert:
        return

    try:
        web_text_default = ""
        text_map = {}

        if callable(message_or_func):
            for lang_code in STRINGS.keys():
                try:
                    text_map[lang_code] = message_or_func(lang_code)
                except Exception:
                    pass
            web_text_default = text_map.get(config.DEFAULT_LANGUAGE, "")
            if not web_text_default and text_map:
                web_text_default = list(text_map.values())[0]
        else:
            web_text_default = message_or_func
            if kwargs:
                try:
                    web_text_default = web_text_default.format(**kwargs)
                except Exception:
                    pass
            
        if web_text_default or text_map:
            source = "node" if node_token else "agent"
            shared_state.WEB_NOTIFICATIONS.appendleft(
                {
                    "id": str(uuid.uuid4()),
                    "text": web_text_default,
                    "text_map": text_map,
                    "time": time.time(),
                    "type": alert_type,
                    "source": source, # Добавлено поле source
                }
            )
    except Exception as e:
        logging.error(f"Ошибка сохранения Web-уведомления: {e}")
    for user_id in users_to_alert:
        try:
            lang = get_user_lang(user_id)
            text_to_send = (
                message_or_func(lang) if callable(message_or_func) else message_or_func
            )
            if not text_to_send:
                continue
            await bot.send_message(user_id, text_to_send, parse_mode="HTML")
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Ошибка при отправке алерта пользователю {user_id}: {e}")