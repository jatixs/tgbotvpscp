# /opt/tg-bot/modules/xray.py
import asyncio
import re
import logging
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html, detect_xray_client

BUTTON_TEXT = "🩻 Обновление X-ray"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(updatexray_handler)

async def updatexray_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "updatexray"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    sent_msg = await message.answer("🔍 Определяю установленный клиент Xray...")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id
    
    try:
        client, container_name = await detect_xray_client() 

        if not client:
            await message.bot.edit_message_text("❌ Не удалось определить поддерживаемый клиент Xray (Marzban, Amnezia). Обновление невозможно.", chat_id=chat_id, message_id=sent_msg.message_id)
            return

        version = "неизвестной"
        client_name_display = client.capitalize()

        await message.bot.edit_message_text(f"✅ Обнаружен: <b>{client_name_display}</b> (контейнер: <code>{escape_html(container_name)}</code>). Начинаю обновление...", chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

        update_cmd = ""
        version_cmd = ""

        if client == "amnezia":
            update_cmd = (
                f'docker exec {container_name} /bin/bash -c "'
                'rm -f Xray-linux-64.zip xray geoip.dat geosite.dat && '
                'wget -q -O Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && '
                'wget -q -O geoip.dat https://github.com/v2fly/geoip/releases/latest/download/geoip.dat && '
                'wget -q -O geosite.dat https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat && '
                'unzip -o Xray-linux-64.zip xray && '
                'cp xray /usr/bin/xray && '
                'cp geoip.dat /usr/bin/geoip.dat && '
                'cp geosite.dat /usr/bin/geosite.dat && '
                'rm Xray-linux-64.zip xray geoip.dat geosite.dat" && '
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
             env_file = "/opt/marzban/.env"
             update_env_cmd = (
                 f"if ! grep -q '^XRAY_EXECUTABLE_PATH=' {env_file}; then echo 'XRAY_EXECUTABLE_PATH=/var/lib/marzban/xray-core/xray' >> {env_file}; else sed -i 's|^XRAY_EXECUTABLE_PATH=.*|XRAY_EXECUTABLE_PATH=/var/lib/marzban/xray-core/xray|' {env_file}; fi && "
                 f"if ! grep -q '^XRAY_ASSETS_PATH=' {env_file}; then echo 'XRAY_ASSETS_PATH=/var/lib/marzban/xray-core' >> {env_file}; else sed -i 's|^XRAY_ASSETS_PATH=.*|XRAY_ASSETS_PATH=/var/lib/marzban/xray-core|' {env_file}; fi"
             )
             restart_cmd = f"docker restart {container_name}"
             update_cmd = f"{check_deps_cmd} && {download_unzip_cmd} && {update_env_cmd} && {restart_cmd}"
             version_cmd = f'docker exec {container_name} /var/lib/marzban/xray-core/xray version'

        process_update = await asyncio.create_subprocess_shell(update_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_update, stderr_update = await process_update.communicate()

        if process_update.returncode != 0:
            error_output = stderr_update.decode() or stdout_update.decode()
            raise Exception(f"Процесс обновления {client_name_display} завершился с ошибкой:\n<pre>{escape_html(error_output)}</pre>")

        process_version = await asyncio.create_subprocess_shell(version_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_version, _ = await process_version.communicate()
        version_output = stdout_version.decode('utf-8', 'ignore')
        version_match = re.search(r'Xray\s+([\d\.]+)', version_output)
        if version_match:
            version = version_match.group(1)

        final_message = f"✅ Xray для <b>{client_name_display}</b> успешно обновлен до версии <b>{version}</b>"
        await message.bot.edit_message_text(final_message, chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка в updatexray_handler: {e}")
        error_msg = f"⚠️ <b>Ошибка обновления Xray:</b>\n\n{str(e)}"
        try:
             await message.bot.edit_message_text(error_msg , chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")
        except TelegramBadRequest as edit_e:
             if "message to edit not found" in str(edit_e):
                  logging.warning("UpdateXray: Failed to edit error message, likely deleted.")
                  await message.answer(error_msg, parse_mode="HTML")
             else:
                  raise
    finally:
        await state.clear()