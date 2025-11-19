from core.middlewares import SpamThrottleMiddleware
from modules import (
    selftest, traffic, uptime, notifications, users, vless,
    speedtest, top, xray, sshlog, fail2ban, logs, update, reboot, restart,
    optimize, nodes
)
from core.i18n import _, I18nFilter, get_language_keyboard
from core import i18n
from core import config, shared_state, auth, utils, keyboards, messaging
from core import nodes_db, server
import asyncio
import logging
import signal
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

ENABLE_SELFTEST = True
ENABLE_UPTIME = True
ENABLE_SPEEDTEST = True
ENABLE_TRAFFIC = True
ENABLE_TOP = True
ENABLE_SSHLOG = True
ENABLE_FAIL2BAN = True
ENABLE_LOGS = True
ENABLE_VLESS = True
ENABLE_XRAY = True
ENABLE_UPDATE = True
ENABLE_RESTART = True
ENABLE_REBOOT = True
ENABLE_NOTIFICATIONS = True
ENABLE_USERS = True
ENABLE_OPTIMIZE = True

config.setup_logging(config.BOT_LOG_DIR, "bot")

bot = Bot(token=config.TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.message.middleware(SpamThrottleMiddleware())
dp.callback_query.middleware(SpamThrottleMiddleware())

buttons_map = {
    "user": [],
    "admin": [],
    "root": []
}
background_tasks = set()

def register_module(module, admin_only=False, root_only=False):
    try:
        if hasattr(module, 'register_handlers'):
            module.register_handlers(dp)
        else:
            logging.warning(
                f"Module '{module.__name__}' has no register_handlers().")

        button_level = "user"
        if root_only:
            button_level = "root"
        elif admin_only:
            button_level = "admin"

        if hasattr(module, 'get_button'):
            buttons_map[button_level].append(module.get_button())
        else:
            logging.warning(
                f"Module '{module.__name__}' has no get_button() and won't be added to ReplyKeyboard.")

        if hasattr(module, 'start_background_tasks'):
            tasks = module.start_background_tasks(bot)
            for task in tasks:
                background_tasks.add(task)

        logging.info(f"Module '{module.__name__}' successfully registered.")

    except Exception as e:
        logging.error(
            f"Error registering module '{module.__name__}': {e}",
            exc_info=True)

async def show_main_menu(
        user_id: int,
        chat_id: int,
        state: FSMContext,
        message_id_to_delete: int = None,
        is_start_command: bool = False):
    command = "menu"
    await state.clear()

    lang = i18n.get_user_lang(user_id)
    is_first_start = (
        is_start_command and
        user_id not in i18n.shared_state.USER_SETTINGS
    )

    if not auth.is_allowed(user_id, command):
        if is_first_start:
            await messaging.send_support_message(bot, user_id, lang)

        if lang == config.DEFAULT_LANGUAGE and user_id not in i18n.shared_state.USER_SETTINGS:
            await bot.send_message(chat_id, _("language_select", 'ru'), reply_markup=get_language_keyboard())
            await auth.send_access_denied_message(bot, user_id, chat_id, command)
            return

        await auth.send_access_denied_message(bot, user_id, chat_id, command)
        return

    bot.buttons_map = buttons_map

    if message_id_to_delete:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
        except TelegramBadRequest:
            pass

    await messaging.delete_previous_message(
        user_id, list(shared_state.LAST_MESSAGE_IDS.get(user_id, {}).keys()), chat_id, bot
    )

    if is_first_start:
        await messaging.send_support_message(bot, user_id, lang)
        i18n.set_user_lang(user_id, lang)

    if str(user_id) not in shared_state.USER_NAMES:
        await auth.refresh_user_names(bot)

    menu_text = _("main_menu_welcome", user_id)
    reply_markup = keyboards.get_main_reply_keyboard(user_id, bot.buttons_map)

    try:
        sent_message = await bot.send_message(chat_id, menu_text, reply_markup=reply_markup)
        shared_state.LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(
            f"Failed to send main menu to user {user_id}: {e}")


@dp.message(Command("start", "menu"))
@dp.message(I18nFilter("btn_back_to_menu"))
async def start_or_menu_handler_message(
        message: types.Message,
        state: FSMContext):
    is_start_command = message.text == "/start"
    await show_main_menu(
        message.from_user.id,
        message.chat.id,
        state,
        is_start_command=is_start_command
    )


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(
        callback: types.CallbackQuery,
        state: FSMContext):
    await show_main_menu(
        callback.from_user.id,
        callback.message.chat.id,
        state,
        callback.message.message_id,
        is_start_command=False
    )
    await callback.answer()


@dp.message(I18nFilter("btn_language"))
async def language_handler(message: types.Message):
    user_id = message.from_user.id
    if not auth.is_allowed(user_id, "start"):
        await auth.send_access_denied_message(bot, user_id, message.chat.id, "start")
        return

    await message.answer(
        _("language_select", user_id),
        reply_markup=get_language_keyboard()
    )


@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(
        callback: types.CallbackQuery,
        state: FSMContext):
    user_id = callback.from_user.id
    lang = callback.data.split('_')[-1]

    if lang not in i18n.STRINGS:
        lang = config.DEFAULT_LANGUAGE

    i18n.set_user_lang(user_id, lang)
    await callback.answer(_("language_selected", lang))
    await show_main_menu(user_id, callback.message.chat.id, state, callback.message.message_id)


def load_modules():
    logging.info("Loading modules and registering handlers...")

    buttons_map["user"].append(
        KeyboardButton(
            text=_(
                "btn_language",
                config.DEFAULT_LANGUAGE)))

    if ENABLE_SELFTEST:
        register_module(selftest)
    if ENABLE_UPTIME:
        register_module(uptime)
    if ENABLE_TRAFFIC:
        register_module(traffic)
    if ENABLE_NOTIFICATIONS:
        register_module(notifications)

    if ENABLE_USERS:
        register_module(users, admin_only=True)
    if ENABLE_SPEEDTEST:
        register_module(speedtest, admin_only=True)
    if ENABLE_TOP:
        register_module(top, admin_only=True)
    if ENABLE_VLESS:
        register_module(vless, admin_only=True)
    if ENABLE_XRAY:
        register_module(xray, admin_only=True)

    if ENABLE_SSHLOG:
        register_module(sshlog, root_only=True)
    if ENABLE_FAIL2BAN:
        register_module(fail2ban, root_only=True)
    if ENABLE_LOGS:
        register_module(logs, root_only=True)
    if ENABLE_UPDATE:
        register_module(update, root_only=True)
    if ENABLE_RESTART:
        register_module(restart, root_only=True)
    if ENABLE_REBOOT:
        register_module(reboot, root_only=True)
    if ENABLE_OPTIMIZE:
        register_module(optimize, root_only=True)

    # Регистрируем модуль Nodes
    register_module(nodes, admin_only=True)

    logging.info("All modules loaded.")


async def shutdown(dispatcher: Dispatcher, bot_instance: Bot, web_runner=None):
    logging.info("Shutdown signal received. Stopping...")
    
    if web_runner:
        logging.info("Stopping Agent Web Server...")
        await web_runner.cleanup()

    try:
        await dispatcher.stop_polling()
        logging.info("Polling stopped.")
    except Exception as e:
        logging.error(f"Error stopping polling: {e}")

    cancelled_tasks = []
    for task in list(background_tasks):
        if task and not task.done():
            task.cancel()
            cancelled_tasks.append(task)
    if cancelled_tasks:
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)
    
    session = getattr(bot_instance, 'session', None)
    if session:
        await session.close()
    
    nodes_db.save_nodes()
    logging.info("Bot stopped gracefully.")


async def main():
    loop = asyncio.get_event_loop()
    web_runner = None
    
    try:
        logging.info(f"Bot starting in mode: {config.INSTALL_MODE.upper()}")
        
        # Загрузка данных
        await asyncio.to_thread(auth.load_users)
        await asyncio.to_thread(utils.load_alerts_config)
        await asyncio.to_thread(i18n.load_user_settings)
        await asyncio.to_thread(nodes_db.load_nodes)
        
        await auth.refresh_user_names(bot)
        await utils.initial_reboot_check(bot)
        await utils.initial_restart_check(bot)
        
        load_modules()

        # Запуск веб-сервера (передаем бота для отправки ответов пользователю)
        logging.info("Starting Agent Web Server...")
        web_runner = await server.start_web_server(bot)
        if not web_runner:
            logging.warning("Web Server NOT started (error). Bot will run without receiving reports.")

        try:
            signals = (signal.SIGINT, signal.SIGTERM)
            for s in signals:
                loop.add_signal_handler(
                    s, 
                    lambda s=s: asyncio.create_task(shutdown(dp, bot, web_runner))
                )
        except NotImplementedError:
            pass

        logging.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except (KeyboardInterrupt, SystemExit):
        logging.info("Exit from main.")
    except Exception as e:
        logging.critical(f"Critical error in main: {e}", exc_info=True)
    finally:
        if web_runner:
             await web_runner.cleanup()
        await shutdown(dp, bot, web_runner)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass