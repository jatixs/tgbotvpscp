# /opt-tg-bot/bot.py
from modules import (
    selftest, traffic, uptime, notifications, users, vless,
    speedtest, top, xray, sshlog, fail2ban, logs, update, reboot, restart,
    optimize  # <-- ДОБАВЛЕНО
)
from core.shared_state import BUTTONS_MAP  # <--- ИЗМЕНЕНИЕ: Импортируем карту
from core import config, shared_state, auth, utils, keyboards, messaging
import asyncio
import logging
import signal
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import KeyboardButton  # Импорт остается
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# --- ПЕРЕКЛЮЧАТЕЛИ МОДУЛЕЙ ---
ENABLE_SELFTEST = True
ENABLE_UPTIME = True
ENABLE_SPEEDTEST = True  # Admin
ENABLE_TRAFFIC = True
ENABLE_TOP = True       # Admin
ENABLE_SSHLOG = True    # Root
ENABLE_FAIL2BAN = True  # Root
ENABLE_LOGS = True      # Root
ENABLE_VLESS = True     # Admin
ENABLE_XRAY = True      # Admin
ENABLE_UPDATE = True    # Root
ENABLE_RESTART = True   # Root
ENABLE_REBOOT = True    # Root
ENABLE_NOTIFICATIONS = True
ENABLE_USERS = True     # Admin
ENABLE_OPTIMIZE = True  # <-- ДОБАВЛЕНО
# ------------------------------

# Импорт основного ядра

# Импорт модулей

# Настройка логирования
config.setup_logging()

# --- Инициализация ---
bot = Bot(token=config.TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# <--- ИЗМЕНЕНИЕ: Блок 'buttons_map = { ... }' УДАЛЕН ОТСЮДА ---
# Набор фоновых задач
background_tasks = set()

# --- Регистрация модулей ---
# (ИЗМЕНЕНИЕ) Функция register_module теперь снова добавляет кнопки в карту


def register_module(module, admin_only=False, root_only=False):
    """Регистрирует обработчики, фоновые задачи и кнопку модуля."""
    try:
        # 1. Регистрация хэндлеров
        module.register_handlers(dp)

        # 2. Определение уровня кнопки
        button_level = "user"
        if root_only:
            button_level = "root"
        elif admin_only:
            button_level = "admin"

        # 3. Добавление кнопки в карту (если модуль предоставляет get_button)
        if hasattr(module, 'get_button'):
            # <--- ИЗМЕНЕНИЕ: Используем BUTTONS_MAP
            BUTTONS_MAP[button_level].append(module.get_button())
        else:
            logging.warning(
                f"Модуль '{module.__name__}' не имеет функции get_button() и не будет добавлен в ReplyKeyboard.")

        # 4. Регистрация фоновых задач (если есть)
        if hasattr(module, 'start_background_tasks'):
            tasks = module.start_background_tasks(bot)  # Ожидаем список
            for task in tasks:
                background_tasks.add(task)

        logging.info(f"Модуль '{module.__name__}' успешно зарегистрирован.")

    except Exception as e:
        logging.error(
            f"Ошибка при регистрации модуля '{module.__name__}': {e}",
            exc_info=True)


# --- Регистрация базовых хэндлеров ---
# Возвращаем версию, которая была после исправления ошибки ID пользователя

async def show_main_menu(
        user_id: int,
        chat_id: int,
        state: FSMContext,
        message_id_to_delete: int = None):
    """Вспомогательная функция для отображения главного меню."""
    command = "menu"
    await state.clear()

    if not auth.is_allowed(user_id, command):
        await auth.send_access_denied_message(bot, user_id, chat_id, command)
        return

    # <--- ИЗМЕНЕНИЕ: Строка 'bot.buttons_map = buttons_map' УДАЛЕНА ---

    if message_id_to_delete:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
        except TelegramBadRequest:
            pass

    # Очищаем ВСЕ предыдущие сообщения
    await messaging.delete_previous_message(
        user_id, list(shared_state.LAST_MESSAGE_IDS.get(user_id, {}).keys()), chat_id, bot
    )

    if str(user_id) not in shared_state.USER_NAMES:
        await auth.refresh_user_names(bot)

    # Используем get_main_reply_keyboard с простой картой кнопок
    menu_text = "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu."
    reply_markup = keyboards.get_main_reply_keyboard(
        user_id, BUTTONS_MAP)  # <--- ИЗМЕНЕНИЕ: Используем BUTTONS_MAP

    try:
        sent_message = await bot.send_message(chat_id, menu_text, reply_markup=reply_markup)
        shared_state.LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(
            f"Не удалось отправить главное меню пользователю {user_id}: {e}")


@dp.message(Command("start", "menu"))
# Текстовая кнопка все еще нужна, т.к. модули могут ее использовать
@dp.message(F.text == "🔙 Назад в меню")
async def start_or_menu_handler_message(
        message: types.Message,
        state: FSMContext):
    """Обработчик для /start, /menu и текстовой кнопки 'Назад в меню'."""
    await show_main_menu(message.from_user.id, message.chat.id, state)


# Инлайн кнопка все еще нужна для InlineKeyboard (например, в Users,
# Notifications)
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(
        callback: types.CallbackQuery,
        state: FSMContext):
    """Обработчик для инлайн-кнопки 'Назад в главное меню'."""
    await show_main_menu(callback.from_user.id, callback.message.chat.id, state, callback.message.message_id)
    await callback.answer()

# --- Удаляем обработчики подменю ---


# --- [!!!] ГЛАВНАЯ ЛОГИКА ЗАГРУЗКИ МОДУЛЕЙ ---
def load_modules():
    logging.info("Загрузка модулей и регистрация обработчиков...")

    # --- Регистрируем ВСЕ модули ---
    # Порядок регистрации не важен для обработчиков, но важен для кнопок, если
    # бы мы их добавляли здесь
    if ENABLE_SELFTEST:
        register_module(selftest)
    if ENABLE_UPTIME:
        register_module(uptime)
    if ENABLE_TRAFFIC:
        register_module(traffic)
    if ENABLE_NOTIFICATIONS:
        register_module(notifications)  # Эта кнопка будет добавлена

    if ENABLE_USERS:
        register_module(users, admin_only=True)  # Эта кнопка будет добавлена
    if ENABLE_SPEEDTEST:
        # Эта кнопка будет добавлена
        register_module(speedtest, admin_only=True)
    if ENABLE_TOP:
        register_module(top, admin_only=True)  # Эта кнопка будет добавлена
    if ENABLE_VLESS:
        register_module(vless, admin_only=True)  # Эта кнопка будет добавлена
    if ENABLE_XRAY:
        register_module(xray, admin_only=True)  # Эта кнопка будет добавлена

    if ENABLE_SSHLOG:
        register_module(sshlog, root_only=True)  # Эта кнопка будет добавлена
    if ENABLE_FAIL2BAN:
        register_module(fail2ban, root_only=True)  # Эта кнопка будет добавлена
    if ENABLE_LOGS:
        register_module(logs, root_only=True)  # Эта кнопка будет добавлена
    if ENABLE_UPDATE:
        register_module(update, root_only=True)  # Эта кнопка будет добавлена
    if ENABLE_RESTART:
        register_module(restart, root_only=True)  # Эта кнопка будет добавлена
    if ENABLE_REBOOT:
        register_module(reboot, root_only=True)  # Эта кнопка будет добавлена
    if ENABLE_OPTIMIZE:
        register_module(optimize, root_only=True)  # <-- ДОБАВЛЕНО

    logging.info("--- Карта кнопок ---")
    # <--- ИЗМЕНЕНИЕ
    logging.info(f"User: {[btn.text for btn in BUTTONS_MAP['user']]}")
    # <--- ИЗМЕНЕНИЕ
    logging.info(f"Admin: {[btn.text for btn in BUTTONS_MAP['admin']]}")
    # <--- ИЗМЕНЕНИЕ
    logging.info(f"Root: {[btn.text for btn in BUTTONS_MAP['root']]}")
    logging.info("---------------------")


# --- Логика запуска и остановки (без изменений) ---
async def shutdown(dispatcher: Dispatcher, bot_instance: Bot):
    logging.info("Получен сигнал завершения. Остановка polling...")
    try:
        await dispatcher.stop_polling()
        logging.info("Polling остановлен.")
    except Exception as e:
        logging.error(f"Ошибка при остановке polling: {e}")
    logging.info("Начинаю отмену фоновых задач...")
    cancelled_tasks = []
    for task in list(background_tasks):
        if task and not task.done():
            task.cancel()
            cancelled_tasks.append(task)
    if cancelled_tasks:
        logging.info(
            f"Ожидание завершения {len(cancelled_tasks)} фоновых задач...")
        results = await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        background_tasks.clear()
        for i, result in enumerate(results):
            if isinstance(
                    result,
                    Exception) and not isinstance(
                    result,
                    asyncio.CancelledError):
                task_name = cancelled_tasks[i].get_name() if hasattr(
                    cancelled_tasks[i], 'get_name') else f"индекс {i}"
                logging.error(
                    f"Ошибка при завершении фоновой задачи {task_name}: {result}")
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
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(
                    shutdown(
                        dp, bot)))
        logging.info("Обработчики сигналов SIGINT и SIGTERM установлены.")
    except NotImplementedError:
        logging.warning("Установка обработчиков сигналов не поддерживается.")
    try:
        logging.info(
            f"Бот запускается в режиме: {config.INSTALL_MODE.upper()}")
        await asyncio.to_thread(auth.load_users)
        await asyncio.to_thread(utils.load_alerts_config)
        await auth.refresh_user_names(bot)
        await utils.initial_reboot_check(bot)
        await utils.initial_restart_check(bot)
        load_modules()  # Загружаем модули, регистрируем хэндлеры и кнопки
        logging.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Получен KeyboardInterrupt/SystemExit в main.")
    except Exception as e:
        logging.critical(
            f"Критическая ошибка в главном цикле бота: {e}",
            exc_info=True)
    finally:
        session_to_check = getattr(bot, 'session', None)
        underlying_session_to_check = getattr(
            session_to_check, 'session', None)
        session_closed_attr = getattr(
            underlying_session_to_check, 'closed', True)
        if not session_closed_attr:
            logging.warning("Повторная попытка очистки...")
            await shutdown(dp, bot)
        logging.info("Функция main бота завершена.")

if __name__ == "__main__":
    try:
        logging.info("Запуск asyncio.run(main())...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную (KeyboardInterrupt в __main__).")
    except Exception as e:
        logging.critical(
            f"Непредвиденное завершение вне цикла asyncio: {e}",
            exc_info=True)
    finally:
        logging.info("Скрипт bot.py завершает работу.")
