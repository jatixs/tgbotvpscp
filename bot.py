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


# --- Регистрация базовых хэндлеров (Start/Menu) ---
@dp.message(Command("start", "menu"))
@dp.message(F.text == "🔙 Назад в меню")
async def start_or_menu_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "start" if message.text == "/start" else "menu"
    await state.clear()
    
    if not auth.is_allowed(user_id, command):
        await auth.send_access_denied_message(bot, user_id, chat_id, command)
        return
        
    # Сохраняем карту кнопок в объект бота, чтобы хэндлеры модулей
    # (как traffic_handler) могли ее достать
    bot.buttons_map = buttons_map
        
    await messaging.delete_previous_message(
        user_id, 
        ["start", "menu", "manage_users", "reboot_confirm", "generate_vless", 
         "adduser", "notifications_menu", "traffic", "get_id", "fall2ban",
         "sshlog", "logs", "restart", "selftest", "speedtest", "top",
         "update", "uptime", "updatexray"], 
        chat_id,
        bot
    )
    if str(user_id) not in shared_state.USER_NAMES:
       await auth.refresh_user_names(bot)
       
    sent_message = await message.answer(
        "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu.",
        reply_markup=keyboards.get_main_reply_keyboard(user_id, buttons_map)
    )
    shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    # Эта логика теперь живет здесь, в главном файле
    try:
        await callback.message.delete() # Просто удаляем сообщение с inline-кнопками
    except TelegramBadRequest as e:
        if "message to delete not found" not in str(e):
            logging.warning(f"Не удалось удалить сообщение при back_to_menu: {e}")
            
    await start_or_menu_handler(callback.message, state) # и вызываем обычное меню
    await callback.answer()


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
        logging.warning("Установка обработчиков сигналов не поддерживается на этой платформе.")

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