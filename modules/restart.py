# /opt-tg-bot/modules/restart.py
import asyncio
import logging
import os
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest  # Добавим импорт

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
# --- [ИСПРАВЛЕНИЕ] Импортируем DEPLOY_MODE ---
from core.config import RESTART_FLAG_FILE, DEPLOY_MODE
# ------------------------------------------

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_restart"
# --------------------------------


def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------


def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(restart_handler)
    # --------------------------------------


async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "restart"  # Имя команды оставляем
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)
    # --- ИЗМЕНЕНО: Используем i18n ---
    sent_msg = await message.answer(_("restart_start", lang))
    # --------------------------------

    try:
        # Убедимся, что директория существует
        os.makedirs(os.path.dirname(RESTART_FLAG_FILE), exist_ok=True)
        # Записываем флаг. Watchdog (внутренний или внешний)
        # должен увидеть его и изменить сообщение.
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(f"{chat_id}:{sent_msg.message_id}")

        # --- [ИСПРАВЛЕНИЕ] Выбираем команду в зависимости от DEPLOY_MODE ---
        restart_cmd = ""
        if DEPLOY_MODE == "docker":
            # В режиме Docker мы должны использовать 'docker restart'
            # Имя контейнера берем из .env
            container_name = os.environ.get("TG_BOT_CONTAINER_NAME")
            if not container_name:
                raise Exception("TG_BOT_CONTAINER_NAME не установлен в .env")
            
            # Бот находится *внутри* контейнера, но у него есть
            # доступ к docker CLI (из Dockerfile) и docker.sock (из compose)
            restart_cmd = f"docker restart {container_name}"
            logging.info(f"Выполнение Docker-рестарта: {restart_cmd}")
            
        else:
            # В режиме Systemd (по умолчанию)
            restart_cmd = "sudo systemctl restart tg-bot.service"
            logging.info(f"Выполнение Systemd-рестарта: {restart_cmd}")
        # --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---

        process = await asyncio.create_subprocess_shell(restart_cmd)
        await process.wait()
        
        # В режиме systemd лог ниже выполнится.
        # В режиме docker контейнер будет убит до 'await'
        logging.info(f"Команда перезапуска ({DEPLOY_MODE}) отправлена.")

    except Exception as e:
        logging.error(
            f"Ошибка в restart_handler при отправке команды перезапуска: {e}")
        # Если команда не удалась, удаляем флаг
        if os.path.exists(RESTART_FLAG_FILE):
            try:
                os.remove(RESTART_FLAG_FILE)
            except OSError:
                pass
        try:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await message.bot.edit_message_text(
                text=_("restart_error", lang, error=str(e)),
                chat_id=chat_id,
                message_id=sent_msg.message_id
            )
            # --------------------------------
        except TelegramBadRequest as edit_e:  # Используем импортированный класс
            if "message to edit not found" in str(edit_e):
                logging.warning(
                    f"Не удалось изменить сообщение об ошибке перезапуска (возможно, удалено): {edit_e}")
            else:
                logging.error(
                    f"Не удалось изменить сообщение об ошибке перезапуска: {edit_e}")
        except Exception as edit_e:
            logging.error(
                f"Не удалось изменить сообщение об ошибке перезапуска: {edit_e}")