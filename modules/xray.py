# /opt-tg-bot/modules/xray.py
import asyncio
import re
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# --- Используем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html, detect_xray_client

# --- Используем ключ для i18n ---
BUTTON_KEY = "btn_xray"
# --------------------------------

def get_button() -> KeyboardButton:
    # --- Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(updatexray_handler)
    # --------------------------------------

async def updatexray_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # --- Получаем язык ---
    lang = get_user_lang(user_id)
    # ----------------------
    command = "updatexray"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)

    # --- Используем i18n ---
    sent_msg = await message.answer(_("xray_detecting", lang))
    # ----------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id

    try:
        client, container_name = await detect_xray_client()

        if not client:
            # --- Используем i18n ---
            await message.bot.edit_message_text(
                _("xray_detect_fail", lang),
                chat_id=chat_id,
                message_id=sent_msg.message_id
            )
            # ----------------------
            return

        # --- Используем i18n ---
        version = _("xray_version_unknown", lang)
        # ----------------------
        client_name_display = client.capitalize()

        # --- Используем i18n ---
        await message.bot.edit_message_text(
            _("xray_detected_start_update", lang, client=client_name_display, container=escape_html(container_name)),
            chat_id=chat_id,
            message_id=sent_msg.message_id,
            parse_mode="HTML"
        )
        # ----------------------

        update_cmd = ""
        version_cmd = ""

        # --- Возвращаем логику из old_xray.py ---
        if client == "amnezia":
            update_cmd = (
                f'docker exec {container_name} /bin/sh -c "' # Используем /bin/sh для Alpine
                'apk add --no-cache wget unzip && ' # Добавляем установку зависимостей
                'rm -f Xray-linux-64.zip xray geoip.dat geosite.dat && '
                'wget -q -O Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && '
                'wget -q -O geoip.dat https://github.com/v2fly/geoip/releases/latest/download/geoip.dat && '
                'wget -q -O geosite.dat https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat && '
                'unzip -o Xray-linux-64.zip xray && '
                'cp xray /usr/bin/xray && '
                'cp geoip.dat /usr/bin/geoip.dat && '
                'cp geosite.dat /usr/bin/geosite.dat && '
                'rm Xray-linux-64.zip xray geoip.dat geosite.dat && '
                'apk del wget unzip' # Удаляем зависимости
                '" && '
                f'docker restart {container_name}'
            )
            version_cmd = f"docker exec {container_name} /usr/bin/xray version"

        elif client == "marzban":
            check_deps_cmd = "command -v unzip >/dev/null 2>&1 || (DEBIAN_FRONTEND=noninteractive apt-get update -y && apt-get install -y unzip wget)"
            download_unzip_cmd = (
                "mkdir -p /var/lib/marzban/xray-core && "
                "cd /var/lib/marzban/xray-core && "
                "wget -q -O Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && "
                "wget -q -O geoip.dat https://github.com/v2fly/geoip/releases/latest/download/geoip.dat && "
                "wget -q -O geosite.dat https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat && "
                "unzip -o Xray-linux-64.zip xray && "
                "rm Xray-linux-64.zip"
            )
            # Ищем .env в стандартном расположении Marzban
            env_file_path = "/opt/marzban/.env"
            # Проверяем наличие файла перед использованием
            update_env_cmd = f"if [ -f {env_file_path} ]; then "
            update_env_cmd += (
                 f"if ! grep -q '^XRAY_EXECUTABLE_PATH=' {env_file_path}; then echo 'XRAY_EXECUTABLE_PATH=/var/lib/marzban/xray-core/xray' >> {env_file_path}; else sed -i 's|^XRAY_EXECUTABLE_PATH=.*|XRAY_EXECUTABLE_PATH=/var/lib/marzban/xray-core/xray|' {env_file_path}; fi && "
                 f"if ! grep -q '^XRAY_ASSETS_PATH=' {env_file_path}; then echo 'XRAY_ASSETS_PATH=/var/lib/marzban/xray-core' >> {env_file_path}; else sed -i 's|^XRAY_ASSETS_PATH=.*|XRAY_ASSETS_PATH=/var/lib/marzban/xray-core|' {env_file_path}; fi; "
            )
            update_env_cmd += "else echo 'Warning: Marzban .env file not found at /opt/marzban/.env'; fi" # Добавляем предупреждение, если файл не найден

            restart_cmd = f"docker restart {container_name}"
            # Собираем полную команду
            update_cmd = f"{check_deps_cmd} && {download_unzip_cmd} && {update_env_cmd} && {restart_cmd}"
            version_cmd = f'docker exec {container_name} /var/lib/marzban/xray-core/xray version'
        # --- Конец возвращенной логики ---

        process_update = await asyncio.create_subprocess_shell(update_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_update, stderr_update = await process_update.communicate()

        if process_update.returncode != 0:
            error_output = stderr_update.decode('utf-8', 'ignore') or stdout_update.decode('utf-8', 'ignore')
            # --- Используем i18n ---
            raise Exception(_("xray_update_error", lang, client=client_name_display, error=escape_html(error_output)))
            # ----------------------

        process_version = await asyncio.create_subprocess_shell(version_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_version, stderr_version = await process_version.communicate() # stderr_version не используется, но получаем его
        version_output = stdout_version.decode('utf-8', 'ignore')
        version_match = re.search(r'Xray\s+([\d\.]+)', version_output)
        if version_match:
            version = version_match.group(1)

        # --- Используем i18n ---
        final_message = _("xray_update_success", lang, client=client_name_display, version=version)
        # ----------------------
        await message.bot.edit_message_text(final_message, chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка в updatexray_handler: {e}")
        # --- Используем i18n ---
        error_msg = _("xray_error_generic", lang, error=str(e))
        # ----------------------
        try:
             await message.bot.edit_message_text(error_msg , chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")
        except TelegramBadRequest as edit_e:
             if "message to edit not found" in str(edit_e):
                  logging.warning("UpdateXray: Failed to edit error message, likely deleted.")
                  await message.answer(error_msg, parse_mode="HTML")
             else:
                  raise # Перевыбрасываем другие ошибки BadRequest
    finally:
        await state.clear()