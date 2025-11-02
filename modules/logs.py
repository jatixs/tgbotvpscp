# /opt-tg-bot/modules/logs.py
import asyncio
import logging
import os
from aiogram import F, types, Router, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton

from core.config import INSTALL_MODE, DEPLOY_MODE, DEFAULT_LANGUAGE
from core.keyboards import get_main_reply_keyboard
from core.i18n import I18nFilter, get_text as _
from core.utils import escape_html  # <-- (ВАЖНО) ДОБАВЛЕН ИМПОРТ

BUTTON_KEY = "btn_logs"

def get_button() -> KeyboardButton:
    """Возвращает кнопку для главного меню."""
    return KeyboardButton(text=_(BUTTON_KEY, DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    """Регистрирует хэндлеры этого модуля в главном диспетчере."""
    dp.include_router(router)

router = Router()

@router.message(I18nFilter(BUTTON_KEY))
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
        # Docker-Root (с chroot)
        if os.path.exists("/host/usr/bin/journalctl"):
            cmd = ["chroot", "/host", "/usr/bin/journalctl", "-n", "20", "--no-pager"]
        elif os.path.exists("/host/bin/journalctl"):
            cmd = ["chroot", "/host", "/bin/journalctl", "-n", "20", "--no-pager"]
        else:
            await message.answer(
                _("logs_journalctl_not_found_in_host", user_id),
                reply_markup=main_keyboard
            )
            return
    else:
        # Systemd
        cmd = ["journalctl", "-n", "20", "--no-pager"]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            # --- [ИСПРАВЛЕНО] Экранируем вывод ---
            log_output = escape_html(stdout.decode().strip())
            # -------------------------------------
            response_text = _("logs_header", user_id, log_output=log_output)
        else:
            # --- [ИСПРАВЛЕНО] Экранируем ошибку ---
            error_message = escape_html(stderr.decode().strip())
            # ---------------------------------------
            logging.error(f"Ошибка при чтении журналов: {error_message}")
            response_text = _("logs_read_error", user_id, error=error_message)

        await message.answer(
            response_text,
            reply_markup=main_keyboard,
            parse_mode="HTML"  # Убедимся, что parse_mode включен
        )

    except FileNotFoundError:
        logging.error(f"Команда '{cmd[0]}' не найдена.")
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