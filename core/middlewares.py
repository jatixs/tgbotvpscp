# /opt-tg-bot/core/middlewares.py
import time
import logging
from typing import Callable, Dict, Any, Awaitable, Tuple

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery

# Импортируем из i18n
from .i18n import _, get_user_lang

# Время кулдауна в секундах
THROTTLE_TIME = 5

# Словари для хранения времени
# --- ИЗМЕНЕНО: Храним кортеж (время, ключ_действия) ---
user_last_action_info: Dict[int, Tuple[float, str | None]] = {}
# --------------------------------------------------------
user_throttle_warning_time: Dict[int, float] = {}


class SpamThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        current_time = time.time()
        bot: Bot = data['bot']

        # --- ОПРЕДЕЛЯЕМ КЛЮЧ ТЕКУЩЕГО ДЕЙСТВИЯ ---
        current_action_key: str | None = None
        if isinstance(event, Message):
            # Для сообщений используем текст (команда или текст кнопки)
            current_action_key = event.text
        elif isinstance(event, CallbackQuery):
            # Для коллбэков используем callback_data
            current_action_key = event.data
        # ----------------------------------------

        # Получаем информацию о последнем действии
        last_timestamp, last_action_key = user_last_action_info.get(
            user_id, (0, None))
        # Время последнего отправленного предупреждения
        last_warning_time = user_throttle_warning_time.get(user_id, 0)

        # --- ПРОВЕРКА ТРОТТЛИНГА ---
        is_throttled = (
            current_time - last_timestamp < THROTTLE_TIME and
            # Не троттлим, если нет ключа (напр. стикер)
            current_action_key is not None and
            # Троттлим только ПОВТОРНЫЕ одинаковые действия
            current_action_key == last_action_key
        )
        # ---------------------------

        if is_throttled:
            # Троттлинг активен для ПОВТОРНОГО действия
            logging.info(
                f"Троттлинг для user_id: {user_id} (повтор '{current_action_key}'). Разница: {current_time - last_timestamp:.2f}с")
            lang = get_user_lang(user_id)

            # Отправляем сообщение о таймауте, если оно еще не было отправлено
            # *для этого периода*
            if last_warning_time <= last_timestamp:
                try:
                    # Используем новый ключ i18n "throttle_message"
                    timeout_message = _(
                        "throttle_message", lang, seconds=THROTTLE_TIME)
                    if isinstance(event, CallbackQuery):
                        await event.answer(timeout_message, show_alert=True)
                    elif isinstance(event, Message):
                        await bot.send_message(event.chat.id, timeout_message)
                    user_throttle_warning_time[user_id] = current_time
                except Exception as e:
                    logging.warning(
                        f"Не удалось отправить/ответить на предупреждение о троттлинге для {user_id}: {e}")

            # Пытаемся удалить входящее сообщение (если это Message)
            if isinstance(event, Message):
                try:
                    await event.delete()
                except Exception:
                    # Игнорируем ошибки удаления (например, нет прав)
                    pass
            # Отвечаем на CallbackQuery без текста (если предупреждение уже
            # было)
            elif isinstance(event, CallbackQuery) and last_warning_time > last_timestamp:
                try:
                    await event.answer()
                except Exception:
                    pass  # Игнорируем ошибки ответа

            return  # Прерываем обработку события

        # Троттлинг не активен (другое действие или время вышло)
        # Обновляем информацию о последнем *разрешенном* действии
        user_last_action_info[user_id] = (current_time, current_action_key)
        # Сбрасывать user_throttle_warning_time не нужно, проверка
        # `last_warning_time <= last_timestamp` корректна
        return await handler(event, data)  # Передаем управление дальше
