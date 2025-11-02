# /opt-tg-bot/modules/logs.py
import asyncio
import logging
import os  # <-- Добавлен import os
from aiogram import F, types, Router
from aiogram.fsm.context import FSMContext

from core.config import INSTALL_MODE, DEPLOY_MODE  # <-- Импортируем режимы
# --- [ИСПРАВЛЕНО] ---
from core.keyboards import get_main_reply_keyboard  # <-- Правильное имя функции
from core.i18n import I18nFilter, get_text as _
# --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

router = Router()


@router.message(I18nFilter("btn_logs"))
async def logs_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()

    # --- [ИСПРАВЛЕНО] Получаем карту кнопок и создаем клавиатуру ОДИН РАЗ ---
    buttons_map = getattr(
        message.bot, 'buttons_map', {
            "user": [], "admin": [], "root": []})
    main_keyboard = get_main_reply_keyboard(user_id, buttons_map)
    # --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

    # --- [ИСПРАВЛЕНИЕ] ---
    if DEPLOY_MODE == "docker" and INSTALL_MODE == "secure":
        # В Docker Secure нет доступа к journalctl
        await message.answer(
            _("logs_docker_secure_not_available", user_id),
            reply_markup=main_keyboard  # <-- Используем исправленную клавиатуру
        )
        return

    # Определяем команду в зависимости от режима
    cmd = []
    if DEPLOY_MODE == "docker" and INSTALL_MODE == "root":
        # В Docker Root ищем journalctl на хосте
        if os.path.exists("/host/usr/bin/journalctl"):
            cmd = ["/host/usr/bin/journalctl", "-n", "20", "--no-pager"]
        elif os.path.exists("/host/bin/journalctl"):
            cmd = ["/host/bin/journalctl", "-n", "20", "--no-pager"]
        else:
            await message.answer(
                _("logs_journalctl_not_found_in_host", user_id),
                reply_markup=main_keyboard  # <-- Используем исправленную клавиатуру
            )
            return
    else:
        # Стандартный режим (Systemd)
        cmd = ["journalctl", "-n", "20", "--no-pager"]
    # --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

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
            reply_markup=main_keyboard  # <-- Используем исправленную клавиатуру
        )

    except FileNotFoundError:
        logging.error("Команда journalctl не найдена.")
        await message.answer(
            _("logs_journalctl_not_found", user_id),
            reply_markup=main_keyboard  # <-- Используем исправленную клавиатуру
        )
    except Exception as e:
        logging.error(f"Ошибка при выполнении logs_handler: {e}")
        await message.answer(
            _("error_unexpected", user_id),
            reply_markup=main_keyboard  # <-- Используем исправленную клавиатуру
        )