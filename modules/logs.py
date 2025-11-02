# /opt/tg-bot/modules/logs.py
import asyncio
import logging
import os
from aiogram import F, types, Router, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton

from core.config import INSTALL_MODE, DEPLOY_MODE, DEFAULT_LANGUAGE
from core.keyboards import get_main_reply_keyboard
from core.i18n import I18nFilter, get_text as _

# --- [ИСПРАВЛЕНИЕ: Добавлены get_button и register_handlers] ---
BUTTON_KEY = "btn_logs"

def get_button() -> KeyboardButton:
    """Возвращает кнопку для главного меню."""
    return KeyboardButton(text=_(BUTTON_KEY, DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    """Регистрирует хэндлеры этого модуля в главном диспетчере."""
    # Включаем роутер, который содержит все хэндлеры
    dp.include_router(router)
# --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

router = Router() # Роутер остается

@router.message(I18nFilter(BUTTON_KEY)) # Используем BUTTON_KEY
async def logs_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()

    buttons_map = getattr(
        message.bot, 'buttons_map', {
            "user": [], "admin": [], "root": []})
    main_keyboard = get_main_reply_keyboard(user_id, buttons_map)

    if DEPLOY_MODE == "docker" and INSTALL_MODE == "secure":
        await message.answer(
            _("logs_docker_secure_not_available", user_id),
            reply_markup=main_keyboard
        )
        return

    cmd = []
    if DEPLOY_MODE == "docker" and INSTALL_MODE == "root":
        if os.path.exists("/host/usr/bin/journalctl"):
            cmd = ["/host/usr/bin/journalctl", "-n", "20", "--no-pager"]
        elif os.path.exists("/host/bin/journalctl"):
            cmd = ["/host/bin/journalctl", "-n", "20", "--no-pager"]
        else:
            await message.answer(
                _("logs_journalctl_not_found_in_host", user_id),
                reply_markup=main_keyboard
            )
            return
    else:
        cmd = ["journalctl", "-n", "20", "--no-pager"]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            log_output = stdout.decode().strip()
            response_text = _("logs_header", user_id, log_output=log_output)
        else:
            error_message = stderr.decode().strip()
            logging.error(f"Ошибка при чтении журналов: {error_message}")
            response_text = _("logs_read_error", user_id, error=error_message)

        await message.answer(
            response_text,
            reply_markup=main_keyboard
        )

    except FileNotFoundError:
        logging.error("Команда journalctl не найдена.")
        await message.answer(
            _("logs_journalctl_not_found", user_id),
            reply_markup=main_keyboard
        )
    except Exception as e:
        logging.error(f"Ошибка при выполнении logs_handler: {e}")
        await message.answer(
            _("error_unexpected", user_id),
            reply_markup=main_keyboard
        )