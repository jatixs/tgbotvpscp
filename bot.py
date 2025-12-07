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
import psutil

if os.path.isdir("/proc_host"):
    psutil.PROCFS_PATH = "/proc_host"

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

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

        # Примечание: Мы собираем кнопки в buttons_map для совместимости,
        # но отображение теперь контролируется через keyboards.py и CATEGORY_MAP
        if hasattr(module, 'get_button'):
            btn = module.get_button()
            button_level = "user"
            if root_only: button_level = "root"
            elif admin_only: button_level = "admin"
            buttons_map[button_level].append(btn)

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
        is_start_command and user_id not in i18n.shared_state.USER_SETTINGS)

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

    await messaging.delete_previous_message(user_id, list(shared_state.LAST_MESSAGE_IDS.get(user_id, {}).keys()), chat_id, bot)

    if is_first_start:
        await messaging.send_support_message(bot, user_id, lang)
        i18n.set_user_lang(user_id, lang)

    if str(user_id) not in shared_state.USER_NAMES:
        await auth.refresh_user_names(bot)

    menu_text = _("main_menu_welcome", user_id)
    # Используем новое меню категорий
    reply_markup = keyboards.get_main_reply_keyboard(user_id)

    try:
        sent_message = await bot.send_message(chat_id, menu_text, reply_markup=reply_markup)
        shared_state.LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Failed to send main menu to user {user_id}: {e}")


@dp.message(Command("start", "menu"))
@dp.message(I18nFilter("btn_back_to_menu"))
async def start_or_menu_handler_message(
        message: types.Message,
        state: FSMContext):
    is_start_command = message.text == "/start"
    await show_main_menu(message.from_user.id, message.chat.id, state, is_start_command=is_start_command)


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(
        callback: types.CallbackQuery,
        state: FSMContext):
    await show_main_menu(callback.from_user.id, callback.message.chat.id, state, callback.message.message_id, is_start_command=False)
    await callback.answer()


# --- ОБРАБОТЧИКИ КАТЕГОРИЙ (НОВОЕ) ---
@dp.message(I18nFilter("cat_monitoring"))
async def cat_monitoring_handler(message: types.Message):
    await _show_subcategory(message, "cat_monitoring")

@dp.message(I18nFilter("cat_management"))
async def cat_management_handler(message: types.Message):
    await _show_subcategory(message, "cat_management")

@dp.message(I18nFilter("cat_security"))
async def cat_security_handler(message: types.Message):
    await _show_subcategory(message, "cat_security")

@dp.message(I18nFilter("cat_tools"))
async def cat_tools_handler(message: types.Message):
    await _show_subcategory(message, "cat_tools")

@dp.message(I18nFilter("cat_settings"))
async def cat_settings_handler(message: types.Message):
    await _show_subcategory(message, "cat_settings")

async def _show_subcategory(message: types.Message, category_key: str):
    user_id = message.from_user.id
    lang = i18n.get_user_lang(user_id)
    
    if not auth.is_allowed(user_id, "menu"):
        return

    # Получаем клавиатуру подкатегории
    markup = keyboards.get_subcategory_keyboard(category_key, user_id)
    cat_name = _(category_key, lang)
    text = _("cat_choose_action", lang, category=cat_name)
    
    sent = await message.answer(text, reply_markup=markup, parse_mode="HTML")
    shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})["subcategory"] = sent.message_id


# --- НАСТРОЙКИ МЕНЮ (INLINE) ---
@dp.message(I18nFilter("btn_configure_menu"))
async def configure_menu_handler(message: types.Message):
    user_id = message.from_user.id
    lang = i18n.get_user_lang(user_id)
    
    if not auth.is_allowed(user_id, "manage_users"): # Ограничение: только админы могут менять конфиг
         await message.answer(_("access_denied_no_rights", lang))
         return

    text = _("main_menu_settings_text", lang)
    markup = keyboards.get_keyboard_settings_inline(lang)
    
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("toggle_kb_"))
async def toggle_kb_config(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = i18n.get_user_lang(user_id)
    
    if not auth.is_allowed(user_id, "manage_users"):
         await callback.answer(_("access_denied_no_rights", lang), show_alert=True)
         return

    config_key = callback.data.replace("toggle_kb_", "")
    
    # Переключаем состояние в конфиге
    current_val = config.KEYBOARD_CONFIG.get(config_key, True)
    config.KEYBOARD_CONFIG[config_key] = not current_val
    config.save_keyboard_config(config.KEYBOARD_CONFIG)
    
    # Обновляем клавиатуру, чтобы показать новые галочки/крестики
    new_markup = keyboards.get_keyboard_settings_inline(lang)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_markup)
    except TelegramBadRequest:
        pass # Игнорируем, если изменений не было (хотя они должны быть)
    
    await callback.answer()

@dp.callback_query(F.data == "close_kb_settings")
async def close_kb_settings(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()


# --- ЯЗЫКОВЫЕ НАСТРОЙКИ ---
@dp.message(I18nFilter("btn_language"))
async def language_handler(message: types.Message):
    user_id = message.from_user.id
    if not auth.is_allowed(user_id, "start"):
        await auth.send_access_denied_message(bot, user_id, message.chat.id, "start")
        return
    await message.answer(_("language_select", user_id), reply_markup=get_language_keyboard())


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
    logging.info("Loading modules...")
    buttons_map["user"].append(
        KeyboardButton(
            text=_(
                "btn_language",
                config.DEFAULT_LANGUAGE)))

    # Регистрируем модули. 
    # ВАЖНО: Мы регистрируем их ВСЕГДА, чтобы хэндлеры работали.
    # Скрытие кнопок теперь происходит визуально в keyboards.py, а не здесь.
    
    register_module(selftest)
    register_module(uptime)
    register_module(traffic)
    register_module(notifications)
    
    # Админские модули
    register_module(users, admin_only=True)
    register_module(speedtest, admin_only=True)
    register_module(top, admin_only=True)
    register_module(vless, admin_only=True)
    register_module(xray, admin_only=True)
    register_module(nodes, admin_only=True)
        
    # Root модули
    register_module(sshlog, root_only=True)
    register_module(fail2ban, root_only=True)
    register_module(logs, root_only=True)
    register_module(update, root_only=True)
    register_module(restart, root_only=True)
    register_module(reboot, root_only=True)
    register_module(optimize, root_only=True)

    logging.info("All modules loaded.")


async def shutdown(dispatcher: Dispatcher, bot_instance: Bot, web_runner=None):
    logging.info("Shutdown signal received.")
    if web_runner:
        await web_runner.cleanup()

    await server.cleanup_server()

    try:
        await dispatcher.stop_polling()
    except Exception:
        pass
    cancelled_tasks = []
    for task in list(background_tasks):
        if task and not task.done():
            task.cancel()
            cancelled_tasks.append(task)
    if cancelled_tasks:
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)
    if getattr(bot_instance, 'session', None):
        await bot_instance.session.close()
    logging.info("Bot stopped.")


async def main():
    loop = asyncio.get_event_loop()
    web_runner = None
    try:
        logging.info(f"Bot starting in mode: {config.INSTALL_MODE.upper()}")

        await nodes_db.init_db()

        await asyncio.to_thread(auth.load_users)
        await asyncio.to_thread(utils.load_alerts_config)
        await asyncio.to_thread(i18n.load_user_settings)
        # Config уже загружен при импорте

        await auth.refresh_user_names(bot)
        await utils.initial_reboot_check(bot)
        await utils.initial_restart_check(bot)

        load_modules()

        logging.info("Starting Agent Web Server...")
        web_runner = await server.start_web_server(bot)
        if not web_runner:
            logging.warning("Web Server NOT started.")

        try:
            for s in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    s, lambda s=s: asyncio.create_task(
                        shutdown(
                            dp, bot, web_runner)))
        except NotImplementedError:
            pass

        logging.info("Starting polling...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Exit main.")
    except Exception as e:
        logging.critical(f"Critical error: {e}", exc_info=True)
    finally:
        if web_runner:
            await web_runner.cleanup()
        await shutdown(dp, bot, web_runner)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass