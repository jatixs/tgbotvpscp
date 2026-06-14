from core.middlewares import SpamThrottleMiddleware, AutoDeleteMessageMiddleware, CallbackTTLMiddleware
from core.orchestrator import ModuleOrchestrator, ModuleTier
from core.i18n import _, I18nFilter, get_language_keyboard
from core import i18n
from core import config, shared_state, auth, utils, keyboards, messaging
from core import nodes_db
from core.web.app import start_web_server
import asyncio
import logging
import signal
import os
import psutil
import sentry_sdk
from tortoise import Tortoise

if os.path.isdir("/proc_host"):
    psutil.PROCFS_PATH = "/proc_host"
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

if config.SENTRY_DSN and config.SENTRY_DSN.strip().startswith("http"):
    try:
        sentry_sdk.init(
            dsn=config.SENTRY_DSN, traces_sample_rate=1.0, profiles_sample_rate=1.0
        )
        logging.info("Sentry initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize Sentry: {e}")
else:
    logging.info("Sentry disabled (DSN not set or invalid).")

config.setup_logging(config.BOT_LOG_DIR, "bot")
bot = Bot(token=config.TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
dp.message.middleware(SpamThrottleMiddleware())
dp.message.middleware(AutoDeleteMessageMiddleware())
dp.callback_query.middleware(SpamThrottleMiddleware())
dp.callback_query.middleware(CallbackTTLMiddleware())
background_tasks = set()

# ─── Module Tier Configuration ───────────────────────────────────────────
# Tier 0 (ALWAYS_ON): loaded at startup, never unloaded.
# Tier 1 (ON_DEMAND): loaded on first use, unloaded after 5 min inactivity.
MODULE_CONFIG = {
    # Tier 0: Always-on — alert system + node monitoring
    "modules.notifications": {"tier": ModuleTier.ALWAYS_ON},
    "modules.nodes":         {"tier": ModuleTier.ALWAYS_ON},

    # Tier 1: On-demand — loaded when user triggers the command
    "modules.selftest":  {"tier": ModuleTier.ON_DEMAND},
    "modules.uptime":    {"tier": ModuleTier.ON_DEMAND},
    "modules.traffic":   {"tier": ModuleTier.ON_DEMAND},
    "modules.users":     {"tier": ModuleTier.ON_DEMAND},
    "modules.speedtest": {"tier": ModuleTier.ON_DEMAND},
    "modules.top":       {"tier": ModuleTier.ON_DEMAND},
    "modules.vless":     {"tier": ModuleTier.ON_DEMAND},
    "modules.xray":      {"tier": ModuleTier.ON_DEMAND},
    "modules.services":  {"tier": ModuleTier.ON_DEMAND},
    "modules.sshlog":    {"tier": ModuleTier.ON_DEMAND},
    "modules.fail2ban":  {"tier": ModuleTier.ON_DEMAND},
    "modules.logs":      {"tier": ModuleTier.ON_DEMAND},
    "modules.update":    {"tier": ModuleTier.ON_DEMAND},
    "modules.restart":   {"tier": ModuleTier.ON_DEMAND},
    "modules.reboot":    {"tier": ModuleTier.ON_DEMAND},
    "modules.optimize":  {"tier": ModuleTier.ON_DEMAND},
    "modules.backups":   {"tier": ModuleTier.ON_DEMAND},
}

UNLOAD_TTL = int(os.environ.get("MODULE_UNLOAD_TTL", 300))  # 5 min default

orchestrator = ModuleOrchestrator(dp, bot, MODULE_CONFIG, unload_ttl=UNLOAD_TTL)
shared_state.ORCHESTRATOR = orchestrator


async def show_main_menu(
    user_id: int,
    chat_id: int,
    state: FSMContext,
    message_id_to_delete: int = None,
    is_start_command: bool = False,
):
    command = "menu"
    await state.clear()
    lang = i18n.get_user_lang(user_id)
    is_first_start = is_start_command and user_id not in i18n.shared_state.USER_SETTINGS
    if not auth.is_allowed(user_id, command):
        if is_first_start:
            await messaging.send_support_message(bot, user_id, lang)
        if (
            lang == config.DEFAULT_LANGUAGE
            and user_id not in i18n.shared_state.USER_SETTINGS
        ):
            await bot.send_message(
                chat_id,
                _("language_select", "ru"),
                reply_markup=get_language_keyboard(),
            )
            await auth.send_access_denied_message(bot, user_id, chat_id, command)
            return
        await auth.send_access_denied_message(bot, user_id, chat_id, command)
        return
    if is_first_start:
        await messaging.send_support_message(bot, user_id, lang)
        await i18n.set_user_lang_async(user_id, lang)
    if str(user_id) not in shared_state.USER_NAMES:
        asyncio.create_task(auth.refresh_user_names(bot))
    if is_start_command:
        menu_text = _("main_menu_welcome", lang)
    else:
        menu_text = _("main_menu_return", lang)
    reply_markup = keyboards.get_main_reply_keyboard(user_id)
    try:
        sent_message = await bot.send_message(
            chat_id, menu_text, reply_markup=reply_markup
        )
        if message_id_to_delete:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
            except TelegramBadRequest:
                pass
        await messaging.delete_previous_message(
            user_id,
            ["menu", "subcategory"],
            chat_id,
            bot,
        )
        shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})[
            command
        ] = sent_message.message_id
    except Exception as e:
        logging.error(f"Failed to send main menu to user {user_id}: {e}")


@dp.message(Command("start", "menu"))
@dp.message(I18nFilter("btn_back_to_menu"))
async def start_or_menu_handler_message(message: types.Message, state: FSMContext):
    is_start_command = message.text == "/start"
    await show_main_menu(
        message.from_user.id, message.chat.id, state, is_start_command=is_start_command
    )


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await show_main_menu(
        callback.from_user.id,
        callback.message.chat.id,
        state,
        callback.message.message_id,
        is_start_command=False,
    )
    await callback.answer()


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
    markup = keyboards.get_subcategory_keyboard(category_key, user_id)
    cat_name = _(category_key, lang)
    text = _("cat_choose_action", lang, category=cat_name)
    sent = await message.answer(text, reply_markup=markup, parse_mode="HTML")
    await messaging.delete_previous_message(
        user_id,
        ["menu", "subcategory"],
        message.chat.id,
        message.bot,
    )
    shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})[
        "subcategory"
    ] = sent.message_id


@dp.message(I18nFilter("btn_configure_menu"))
async def configure_menu_handler(message: types.Message):
    user_id = message.from_user.id
    lang = i18n.get_user_lang(user_id)
    if not auth.is_allowed(user_id, "manage_users"):
        await message.answer(_("access_denied_no_rights", lang))
        return
    text = _("main_menu_settings_text", lang)
    markup = keyboards.get_keyboard_settings_inline(lang)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data.startswith("toggle_kb_cat_"))
async def toggle_kb_category(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = i18n.get_user_lang(user_id)
    if not auth.is_allowed(user_id, "manage_users"):
        await callback.answer(_("access_denied_no_rights", lang), show_alert=True)
        return
    cat_key = callback.data.replace("toggle_kb_cat_", "")
    configurable = [
        (btn_key, keyboards.BTN_CONFIG_MAP[btn_key])
        for btn_key in keyboards.CATEGORY_MAP.get(cat_key, [])
        if btn_key in keyboards.BTN_CONFIG_MAP
    ]
    if not configurable:
        await callback.answer()
        return
    all_on = all(config.KEYBOARD_CONFIG.get(cfg, True) for _btn, cfg in configurable)
    for _btn, config_key in configurable:
        config.KEYBOARD_CONFIG[config_key] = not all_on
    await config.save_keyboard_config_async(config.KEYBOARD_CONFIG)
    new_markup = keyboards.get_keyboard_settings_inline(lang)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_markup)
    except TelegramBadRequest:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("toggle_kb_"))
async def toggle_kb_config(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = i18n.get_user_lang(user_id)
    if not auth.is_allowed(user_id, "manage_users"):
        await callback.answer(_("access_denied_no_rights", lang), show_alert=True)
        return
    config_key = callback.data.replace("toggle_kb_", "")
    current_val = config.KEYBOARD_CONFIG.get(config_key, True)
    config.KEYBOARD_CONFIG[config_key] = not current_val
    await config.save_keyboard_config_async(config.KEYBOARD_CONFIG)
    new_markup = keyboards.get_keyboard_settings_inline(lang)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_markup)
    except TelegramBadRequest:
        pass
    await callback.answer()


@dp.callback_query(F.data == "close_kb_settings")
async def close_kb_settings(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception as e:
        logging.debug(f"Failed to delete message in close_kb_settings: {e}")
    await callback.answer()


@dp.message(I18nFilter("btn_language"))
async def language_handler(message: types.Message):
    user_id = message.from_user.id
    if not auth.is_allowed(user_id, "start"):
        await auth.send_access_denied_message(bot, user_id, message.chat.id, "start")
        return
    await message.answer(
        _("language_select", user_id), reply_markup=get_language_keyboard()
    )


@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    lang = callback.data.split("_")[-1]
    if lang not in i18n.STRINGS:
        lang = config.DEFAULT_LANGUAGE
    await i18n.set_user_lang_async(user_id, lang)
    await callback.answer(_("language_selected", lang))
    await show_main_menu(
        user_id, callback.message.chat.id, state, callback.message.message_id
    )


# ─── /memstats command ───────────────────────────────────────────────────
@dp.message(Command("memstats"))
async def memstats_handler(message: types.Message):
    """Show Memory Orchestrator stats (admin only)."""
    user_id = message.from_user.id
    if user_id != config.ADMIN_USER_ID:
        return
    text = orchestrator.format_stats()
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data == "cmd_memstats")
async def memstats_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Access denied", show_alert=True)
        return
    text = orchestrator.format_stats()
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ─── Catch-all / Unrecognized Message Handler ────────────────────────────
# Note: Registered manually in main() after orchestrator setup so it acts as a true fallback
async def unrecognized_message_handler(message: types.Message):
    """Fallback handler for any unrecognized text/commands. Fetches a useless fact."""
    user_id = message.from_user.id
    lang = i18n.get_user_lang(user_id)
    try:
        import aiohttp
        import urllib.parse
        async with aiohttp.ClientSession() as session:
            async with session.get("https://uselessfacts.jsph.pl/api/v2/facts/random") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    fact = data.get("text", "")
                    
                    if fact and lang != "en":
                        # Translate the fact if the user's language is not English
                        try:
                            translate_url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl={lang}&dt=t&q={urllib.parse.quote(fact)}"
                            async with session.get(translate_url) as tr_resp:
                                if tr_resp.status == 200:
                                    tr_data = await tr_resp.json()
                                    if tr_data and isinstance(tr_data, list) and len(tr_data) > 0:
                                        translated_text = "".join([part[0] for part in tr_data[0] if part[0]])
                                        if translated_text:
                                            fact = translated_text
                        except Exception as tr_e:
                            logging.error(f"Translation API error: {tr_e}")

                    if fact:
                        text = i18n._("unrecognized_command_fact", lang, fact=fact)
                    else:
                        text = i18n._("unrecognized_command", lang)
                    await message.answer(text, parse_mode="HTML")
                else:
                    await message.answer(i18n._("unrecognized_command", lang), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Failed to fetch useless fact: {e}")
        await message.answer(i18n._("unrecognized_command", lang), parse_mode="HTML")

async def shutdown(dispatcher: Dispatcher, bot_instance: Bot, web_runner=None):
    logging.info("Shutdown signal received. Stopping services...")
    try:
        await dispatcher.stop_polling()
    except Exception:
        pass
    if web_runner:
        try:
            await asyncio.wait_for(web_runner.cleanup(), timeout=5.0)
            logging.info("Web server stopped.")
        except asyncio.TimeoutError:
            logging.warning("Web server cleanup timed out.")
        except Exception as e:
            logging.error(f"Web server cleanup error: {e}")
    # Shutdown orchestrator
    await orchestrator.shutdown()
    # Cancel all background tasks (both orchestrator + legacy)
    all_tasks = background_tasks | orchestrator.background_tasks
    cancelled_tasks = []
    for task in list(all_tasks):
        if task and (not task.done()):
            task.cancel()
            cancelled_tasks.append(task)
    if cancelled_tasks:
        logging.info(f"Cancelling {len(cancelled_tasks)} background tasks...")
        try:
            await asyncio.wait_for(
                asyncio.gather(*cancelled_tasks, return_exceptions=True), timeout=5.0
            )
        except asyncio.TimeoutError:
            logging.warning("Background tasks cancellation timed out.")
        except Exception as e:
            logging.error(f"Error during tasks cancellation: {e}")
    logging.info("Closing DB connections...")
    try:
        await asyncio.wait_for(Tortoise.close_connections(), timeout=5.0)
    except Exception as e:
        logging.error(f"DB connections close error: {e}")
    if getattr(bot_instance, "session", None):
        await bot_instance.session.close()
    try:
        await utils.save_agent_availability_async()
    except Exception:
        pass
    logging.info("Bot stopped successfully.")


async def main():
    loop = asyncio.get_event_loop()
    web_runner = None
    try:
        logging.info(f"Bot starting in mode: {config.INSTALL_MODE.upper()}")
        await nodes_db.init_db()
        await auth.load_users_async()
        await utils.load_alerts_config_async()
        await utils.load_services_config_async()
        await i18n.load_user_settings_async()
        await utils.load_agent_availability_async()
        asyncio.create_task(auth.refresh_user_names(bot))
        # Убраны вызовы utils.initial_reboot_check и utils.initial_restart_check
        # Теперь эта логика обрабатывается в watchdog.py

        # ─── Memory Orchestrator: setup + start GC ───
        await orchestrator.setup()
        await orchestrator.start_gc()

        # Register the catch-all handler LAST so it doesn't intercept module commands
        dp.message.register(unrecognized_message_handler)

        logging.info("Starting Agent Web Server...")
        web_runner = await start_web_server(bot)
        if not web_runner:
            logging.warning("Web Server NOT started.")
        logging.info("Starting polling...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Exit main.")
    except Exception as e:
        logging.critical(f"Critical error: {e}", exc_info=True)
    finally:
        await shutdown(dp, bot, web_runner)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass