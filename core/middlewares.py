import time
import logging
from typing import Callable, Dict, Any, Awaitable, Tuple

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery


from .i18n import _, get_user_lang

from .utils import anonymize_user


THROTTLE_TIME = 5


user_last_action_info: Dict[int, Tuple[float, str | None]] = {}

user_throttle_warning_time: Dict[int, float] = {}


class SpamThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        username = event.from_user.username
        current_time = time.time()
        bot: Bot = data['bot']

        user_log_str = anonymize_user(user_id, username)

        current_action_key: str | None = None
        if isinstance(event, Message):

            current_action_key = event.text
        elif isinstance(event, CallbackQuery):

            current_action_key = event.data

        last_timestamp, last_action_key = user_last_action_info.get(
            user_id, (0, None))

        last_warning_time = user_throttle_warning_time.get(user_id, 0)

        is_throttled = (
            current_time - last_timestamp < THROTTLE_TIME and

            current_action_key is not None and

            current_action_key == last_action_key
        )

        if is_throttled:

            # ИСПРАВЛЕНО: Объединена разорванная f-строка
            logging.info(
                f"Throttling active for {user_log_str}. Action: '{current_action_key}'. "
                f"Diff: {current_time - last_timestamp:.2f}s"
            )

            lang = get_user_lang(user_id)

            if last_warning_time <= last_timestamp:
                try:

                    timeout_message = _(
                        "throttle_message", lang, seconds=THROTTLE_TIME)
                    if isinstance(event, CallbackQuery):
                        await event.answer(timeout_message, show_alert=True)
                    elif isinstance(event, Message):
                        await bot.send_message(event.chat.id, timeout_message)
                    user_throttle_warning_time[user_id] = current_time
                except Exception as e:
                    logging.warning(
                        f"Failed to send throttling warning to {user_log_str}: {e}")

            if isinstance(event, Message):
                try:
                    await event.delete()
                except Exception:

                    pass

            elif isinstance(event, CallbackQuery) and last_warning_time > last_timestamp:
                try:
                    await event.answer()
                except Exception:
                    pass

            return

        user_last_action_info[user_id] = (current_time, current_action_key)

        return await handler(event, data)
