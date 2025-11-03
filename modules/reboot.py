# /opt-tg-bot/modules/reboot.py
import asyncio
import logging
import os
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

# Используем send_access_denied_message, т.к. текст там общий
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS

# --- [ИСПРАВЛЕНИЕ] Добавляем DEPLOY_MODE и INSTALL_MODE ---
from core.config import REBOOT_FLAG_FILE, INSTALL_MODE, DEPLOY_MODE
# --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

from core.keyboards import get_reboot_confirmation_keyboard

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_reboot"
# --------------------------------


def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------


def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(reboot_confirm_handler)
    # --------------------------------------
    dp.callback_query(F.data == "reboot")(reboot_handler)


async def reboot_confirm_handler(message: types.Message):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "reboot_confirm"
    if not is_allowed(user_id, command):
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.bot.send_message(message.chat.id, _("access_denied_not_root", lang))
        # --------------------------------
        return

    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    # --- ИЗМЕНЕНО: Используем i18n и передаем ID ---
    sent_message = await message.answer(
        _("reboot_confirm_prompt", lang),
        reply_markup=get_reboot_confirmation_keyboard(user_id),
        parse_mode="HTML"
    )
    # ----------------------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def reboot_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "reboot"

    if not is_allowed(user_id, command):
        try:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.answer(_("access_denied_not_root", lang), show_alert=True)
            # --------------------------------
        except TelegramBadRequest:
            pass
        return

    try:
        # --- ИЗМЕНЕНО: Используем i18n ---
        await callback.bot.edit_message_text(
            _("reboot_confirmed", lang),
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="HTML"
        )
        # --------------------------------
    except TelegramBadRequest:
        logging.warning(
            "Не удалось отредактировать сообщение о перезагрузке (возможно, удалено).")

    try:
        # Убедимся, что директория существует
        os.makedirs(os.path.dirname(REBOOT_FLAG_FILE), exist_ok=True)
        with open(REBOOT_FLAG_FILE, "w") as f:
            f.write(str(user_id))
    except Exception as e:
        logging.error(f"Не удалось записать флаг перезагрузки: {e}")

    try:
        # --- [ИСПРАВЛЕНИЕ] Выбираем команду в зависимости от режима ---
        reboot_cmd = ""
        if DEPLOY_MODE == "docker" and INSTALL_MODE == "root":
            # В Docker Root используем chroot, чтобы выполнить команду хоста
            # Используем полный путь /sbin/reboot для надежности
            reboot_cmd = "chroot /host /sbin/reboot"
        else:
            # В Systemd (или Docker Secure, где это все равно не сработает)
            # используем стандартную команду
            reboot_cmd = "reboot"
        # --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

        logging.info(f"Выполнение команды перезагрузки: {reboot_cmd}")
        process = await asyncio.create_subprocess_shell(reboot_cmd)
        await process.wait()
        logging.info("Команда перезагрузки отправлена.")
        
    except Exception as e:
        logging.error(f"Ошибка при отправке команды reboot: {e}")
        try:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await callback.bot.send_message(
                chat_id=chat_id,
                text=_("reboot_error", lang, error=e)
            )
            # --------------------------------
        except Exception as send_e:
            logging.error(
                f"Не удалось отправить сообщение об ошибке перезагрузки: {send_e}")