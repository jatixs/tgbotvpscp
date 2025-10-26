# /opt-tg-bot/core/middlewares.py
import time
import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

# Импортируем из i18n
from .i18n import _, get_user_lang

# Время кулдауна в секундах
THROTTLE_TIME = 5

# Словарь для хранения времени последнего сообщения от пользователя
user_last_message_time: Dict[int, float] = {}

class SpamThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        current_time = time.time()
        last_time = user_last_message_time.get(user_id, 0)

        if current_time - last_time < THROTTLE_TIME:
            # Слишком часто
            logging.info(f"Троттлинг для user_id: {user_id}. Разница: {current_time - last_time:.2f}с")
            # Получаем язык пользователя для ответа
            lang = get_user_lang(user_id)
            if isinstance(event, Message):
                # Для текстовых сообщений можно просто ничего не делать или
                # удалить
                # await event.delete() # Опционально
                pass # Игнорируем сообщение
            elif isinstance(event, CallbackQuery):
                # Отвечаем на callback, чтобы убрать "часики"
                try:
                    # Можно добавить текст, но пока просто убираем часики
                    # text=_("Подождите немного перед следующим нажатием.", lang)
                    await event.answer()
                except Exception as e:
                    logging.warning(f"Не удалось ответить на callback при троттлинге: {e}")
            return # Прерываем обработку

        # Если время прошло, обновляем время и продолжаем
        user_last_message_time[user_id] = current_time
        return await handler(event, data)
