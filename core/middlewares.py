# /opt-tg-bot/core/middlewares.py
import time
import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery

# Импортируем из i18n
from .i18n import _, get_user_lang

# Время кулдауна в секундах
THROTTLE_TIME = 5

# Словари для хранения времени
user_last_message_time: Dict[int, float] = {}
# --- ДОБАВЛЕНО: Словарь для времени отправки предупреждения ---
user_throttle_warning_time: Dict[int, float] = {}
# -----------------------------------------------------------

class SpamThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        current_time = time.time()
        # Время последнего *разрешенного* сообщения
        last_allowed_time = user_last_message_time.get(user_id, 0)
        # Время последнего *отправленного предупреждения* о троттлинге
        last_warning_time = user_throttle_warning_time.get(user_id, 0)
        # Получаем экземпляр бота из данных, переданных Aiogram
        bot: Bot = data['bot']

        # --- ИЗМЕНЕНА ЛОГИКА ---
        if current_time - last_allowed_time < THROTTLE_TIME:
            # Троттлинг активен
            logging.info(f"Троттлинг для user_id: {user_id}. Разница: {current_time - last_allowed_time:.2f}с")
            lang = get_user_lang(user_id)

            # Отправляем сообщение о таймауте, *только если* оно еще не было отправлено
            # после последнего разрешенного сообщения.
            if last_warning_time <= last_allowed_time:
                try:
                    # Используем новый ключ i18n "throttle_message"
                    timeout_message = _("throttle_message", lang, seconds=THROTTLE_TIME)
                    if isinstance(event, CallbackQuery):
                        # Для коллбэка отвечаем с текстом и алертом
                        await event.answer(timeout_message, show_alert=True)
                    elif isinstance(event, Message):
                        # Для сообщения отправляем новое сообщение в чат
                        await bot.send_message(event.chat.id, timeout_message)
                    # Обновляем время отправки предупреждения
                    user_throttle_warning_time[user_id] = current_time
                except Exception as e:
                    logging.warning(f"Не удалось отправить/ответить на предупреждение о троттлинге для {user_id}: {e}")

            # Пытаемся удалить входящее сообщение (если это Message)
            if isinstance(event, Message):
                try:
                    await event.delete()
                except Exception:
                    # Игнорируем ошибки удаления (например, нет прав)
                    pass
            # Отвечаем на CallbackQuery без текста (чтобы убрать часики),
            # если предупреждение уже было отправлено ранее.
            elif isinstance(event, CallbackQuery) and last_warning_time > last_allowed_time:
                 try:
                     await event.answer()
                 except Exception:
                     pass # Игнорируем ошибки ответа

            return # Прерываем обработку события

        # Троттлинг не активен
        user_last_message_time[user_id] = current_time # Обновляем время последнего разрешенного сообщения
        # Нет необходимости сбрасывать user_throttle_warning_time,
        # проверка `last_warning_time <= last_allowed_time` сама это обработает
        return await handler(event, data) # Передаем управление дальше
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---