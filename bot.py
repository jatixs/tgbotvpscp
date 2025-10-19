# /opt/tg-bot/bot.py
import asyncio
import logging
import signal
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# --- ПЕРЕКЛЮЧАТЕЛИ МОДУЛЕЙ ---
ENABLE_SELFTEST = True
ENABLE_TRAFFIC = True
ENABLE_UPTIME = True
ENABLE_NOTIFICATIONS = True
ENABLE_USERS = True
ENABLE_VLESS = True
ENABLE_SPEEDTEST = True
ENABLE_TOP = True
ENABLE_XRAY = True
ENABLE_SSHLOG = True
ENABLE_FAIL2BAN = True
ENABLE_LOGS = True
ENABLE_UPDATE = True
ENABLE_REBOOT = True
ENABLE_RESTART = True
# ------------------------------

# Импорт основного ядра
from core import config, shared_state, auth, utils, keyboards, messaging

# Импорт модулей
from modules import (
    selftest, traffic, uptime, notifications, users, vless,
    speedtest, top, xray, sshlog, fail2ban, logs, update, reboot, restart
)

# Настройка логирования
config.setup_logging()

# --- Инициализация ---
bot = Bot(token=config.TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Карта для кнопок главного меню
buttons_map = {
    "user": [],
    "admin": [],
    "root": []
}
# Набор фоновых задач
background_tasks = set()

def register_module(module, admin_only=False, root_only=False):
    """Помощник для регистрации модуля."""
    try:
        # 1. Регистрация хэндлеров
        module.register_handlers(dp)

        # 2. Определение уровня кнопки
        button_level = "user"
        if root_only:
            button_level = "root"
        elif admin_only:
            button_level = "admin"

        # 3. Добавление кнопки в карту
        buttons_map[button_level].append(module.get_button())

        # 4. Регистрация фоновых задач (если есть)
        if hasattr(module, 'start_background_tasks'):
            tasks = module.start_background_tasks(bot) # Ожидаем список
            for task in tasks:
                background_tasks.add(task)

        logging.info(f"Модуль '{module.__name__}' успешно загружен.")

    except Exception as e:
        logging.error(f"Ошибка при загрузке модуля '{module.__name__}': {e}", exc_info=True)


# --- (ИСПРАВЛЕНИЕ) Регистрация базовых хэндлеров (Start/Menu) ---

async def show_main_menu(user_id: int, chat_id: int, state: FSMContext):
    """Вспомогательная функция для отображения главного меню."""
    command = "menu" # Предполагаем команду 'menu' при внутреннем вызове
    await state.clear()

    # Проверка прав доступа для пользователя, инициировавшего действие
    if not auth.is_allowed(user_id, command):
        await auth.send_access_denied_message(bot, user_id, chat_id, command)
        return

    # Убедимся, что карта кнопок доступна боту
    bot.buttons_map = buttons_map

    # Очищаем предыдущие сообщения, связанные с этим ПОЛЬЗОВАТЕЛЕМ
    await messaging.delete_previous_message(
        user_id,
        ["start", "menu", "manage_users", "reboot_confirm", "generate_vless",
         "adduser", "notifications_menu", "traffic", "get_id", "fall2ban",
         "sshlog", "logs", "restart", "selftest", "speedtest", "top",
         "update", "uptime", "updatexray"],
        chat_id,
        bot
    )

    # Убедимся, что имя пользователя загружено/обновлено при необходимости
    if str(user_id) not in shared_state.USER_NAMES:
       await auth.refresh_user_names(bot) # Передаем экземпляр bot

    # Готовим текст и клавиатуру меню
    menu_text = "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu."
    # Используем bot.buttons_map, который был заполнен при запуске
    reply_markup = keyboards.get_main_reply_keyboard(user_id, bot.buttons_map)

    # Отправляем НОВОЕ сообщение с меню
    try:
        sent_message = await bot.send_message(
            chat_id,
            menu_text,
            reply_markup=reply_markup
        )
        # Сохраняем ID нового сообщения меню
        shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Не удалось отправить главное меню пользователю {user_id}: {e}")


@dp.message(Command("start", "menu"))
@dp.message(F.text == "🔙 Назад в меню") # Этот текст приходит от ReplyKeyboard
async def start_or_menu_handler_message(message: types.Message, state: FSMContext):
    """Обработчик ТОЛЬКО для прямых сообщений (/start, /menu, кнопка 'Назад в меню')."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    # Вызываем вспомогательную функцию
    await show_main_menu(user_id, chat_id, state)


@dp.callback_query(F.data == "back_to_menu") # Этот callback приходит от InlineKeyboard
async def back_to_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для инлайн-кнопки 'Назад в меню'."""
    # Получаем ID пользователя, НАЖАВШЕГО кнопку
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    # Удаляем сообщение с инлайн-клавиатурой
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        # Игнорируем ошибку, если сообщение уже удалено
        if "message to delete not found" not in str(e).lower():
            logging.warning(f"Не удалось удалить сообщение при back_to_menu: {e}")

    # Вызываем вспомогательную функцию с ПРАВИЛЬНЫМ user_id
    await show_main_menu(user_id, chat_id, state)
    # Отвечаем на callback-запрос, чтобы убрать "часики" на кнопке
    await callback.answer()

# --- КОНЕЦ ИСПРАВЛЕНИЯ ---


# --- [!!!] ГЛАВНАЯ ЛОГИКА ЗАГРУЗКИ МОДУЛЕЙ ---
def load_modules():
    logging.info("Загрузка модулей...")

    # User
    if ENABLE_SELFTEST: register_module(selftest)
    if ENABLE_TRAFFIC: register_module(traffic)
    if ENABLE_UPTIME: register_module(uptime)
    if ENABLE_NOTIFICATIONS: register_module(notifications)

    # Admin
    if ENABLE_USERS: register_module(users, admin_only=True)
    if ENABLE_VLESS: register_module(vless, admin_only=True)
    if ENABLE_SPEEDTEST: register_module(speedtest, admin_only=True)
    if ENABLE_TOP: register_module(top, admin_only=True)
    if ENABLE_XRAY: register_module(xray, admin_only=True)

    # Root
    if ENABLE_SSHLOG: register_module(sshlog, root_only=True)
    if ENABLE_FAIL2BAN: register_module(fail2ban, root_only=True)
    if ENABLE_LOGS: register_module(logs, root_only=True)
    if ENABLE_UPDATE: register_module(update, root_only=True)
    if ENABLE_REBOOT: register_module(reboot, root_only=True)
    if ENABLE_RESTART: register_module(restart, root_only=True)

    logging.info("--- Карта кнопок ---")
    logging.info(f"User: {[btn.text for btn in buttons_map['user']]}")
    logging.info(f"Admin: {[btn.text for btn in buttons_map['admin']]}")
    logging.info(f"Root: {[btn.text for btn in buttons_map['root']]}")
    logging.info("---------------------")


# --- Логика запуска и остановки ---
async def shutdown(dispatcher: Dispatcher, bot_instance: Bot):
    logging.info("Получен сигнал завершения. Остановка polling...")
    try:
        await dispatcher.stop_polling()
        logging.info("Polling остановлен.")
    except Exception as e:
        logging.error(f"Ошибка при остановке polling: {e}")

    logging.info("Начинаю отмену фоновых задач...")
    for task in list(background_tasks):
        if task and not task.done():
            task.cancel()

    logging.info("Ожидание завершения фоновых задач (с таймаутом)...")
    results = await asyncio.gather(*background_tasks, return_exceptions=True)
    background_tasks.clear()

    for i, result in enumerate(results):
         if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
             logging.error(f"Ошибка при завершении фоновой задачи (индекс {i}): {result}")
    logging.info("Фоновые задачи обработаны.")

    session_to_close = getattr(bot_instance, 'session', None)
    underlying_session = getattr(session_to_close, 'session', None)

    if underlying_session and not underlying_session.closed:
        logging.info("Закрытие сессии бота...")
        await session_to_close.close()
        logging.info("Сессия бота закрыта.")
    elif session_to_close:
         logging.info("Сессия бота уже была закрыта.")
    else:
         logging.info("Сессия бота не была инициализирована.")

async def main():
    loop = asyncio.get_event_loop()
    try:
        signals = (signal.SIGINT, signal.SIGTERM)
        for s in signals:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(dp, bot)))
        logging.info("Обработчики сигналов SIGINT и SIGTERM установлены.")
    except NotImplementedError:
        logging.warning("Установка обработчиков сигналов не поддерживается.")

    try:
        logging.info(f"Бот запускается в режиме: {config.INSTALL_MODE.upper()}")

        # Загрузка пользователей и конфигов (теперь это функции из auth/utils)
        await asyncio.to_thread(auth.load_users)
        await asyncio.to_thread(utils.load_alerts_config)
        await auth.refresh_user_names(bot)

        # Проверки перезапуска (передаем bot)
        await utils.initial_reboot_check(bot)
        await utils.initial_restart_check(bot)

        # [!!!] Загружаем модули, хэндлеры, кнопки и фоновые задачи
        load_modules()

        logging.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except (KeyboardInterrupt, SystemExit):
        logging.info("Получен KeyboardInterrupt/SystemExit в блоке try функции main.")
    except Exception as e:
        logging.critical(f"Критическая ошибка в главном цикле бота: {e}", exc_info=True)

    finally:
        session_to_check = getattr(bot, 'session', None)
        underlying_session_to_check = getattr(session_to_check, 'session', None)
        session_closed_attr = getattr(underlying_session_to_check, 'closed', True)

        if not session_closed_attr:
             logging.warning("Polling завершился неожиданно или shutdown не сработал полностью. Повторная попытка очистки...")
             await shutdown(dp, bot)

        logging.info("Функция main бота завершена.")


if __name__ == "__main__":
    try:
        logging.info("Запуск asyncio.run(main())...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную (KeyboardInterrupt в __main__).")
    except Exception as e:
        logging.critical(f"Непредвиденное завершение вне цикла asyncio: {e}", exc_info=True)
    finally:
         logging.info("Скрипт bot.py завершает работу.")