# /opt/tg-bot/modules/optimize.py
import asyncio
import logging
import re  # <--- ВОТ ИСПРАВЛЕНИЕ
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

BUTTON_TEXT = "⚡️ Оптимизация"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)

def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(optimize_handler)

async def optimize_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "optimize" # Новое имя команды

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    
    sent_message = await message.answer(
        "⏳ <b>Запускаю оптимизацию системы...</b>\n\n"
        "Это очень долгий процесс (5-15 минут).\n"
        "Пожалуйста, не перезапускайте бота и не вызывайте другие команды.",
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    
    # Команда выполняется от root (т.к. INSTALL_MODE=root), поэтому 'sudo' не нужен.
    # Добавлен DEBIAN_FRONTEND для apt install
    # ~/.cache заменен на /root/.cache, т.к. бот работает от root
    cmd = (
        "bash -c \""
        "apt update && apt full-upgrade -y && apt autoremove --purge -y && "
        "apt autoclean -y && journalctl --vacuum-time=2d && "
        "rm -rf /var/tmp/* /tmp/* /root/.cache/* && "
        "DEBIAN_FRONTEND=noninteractive apt install preload cpufrequtils zram-tools -y && "
        "systemctl enable preload && systemctl start preload && "
        "echo 'vm.swappiness=10' | tee -a /etc/sysctl.conf && "
        "echo 'vm.vfs_cache_pressure=50' | tee -a /etc/sysctl.conf && "
        "sysctl -p && systemctl restart systemd-journald && systemctl daemon-reexec"
        "\""
    )
    
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    await delete_previous_message(user_id, command, chat_id, message.bot)

    if process.returncode == 0:
        # Ищем вывод sysctl -p в stdout
        sysctl_output = ""
        sysctl_match = re.search(r'vm\.swappiness = 10.*vm\.vfs_cache_pressure = 50', output, re.DOTALL)
        if sysctl_match:
            sysctl_output = sysctl_match.group(0)

        response_text = (
            f"✅ <b>Оптимизация завершена успешно!</b>\n\n"
            f"<b>Последние 1000 символов вывода (включая sysctl):</b>\n"
            f"<pre>{escape_html(output[-1000:])}</pre>"
        )
    else:
        response_text = (
            f"❌ <b>Ошибка во время оптимизации!</b>\n\n"
            f"<b>Код возврата:</b> {process.returncode}\n"
            f"<b>Вывод STDOUT (последние 1000):</b>\n"
            f"<pre>{escape_html(output[-1000:])}</pre>\n"
            f"<b>Вывод STDERR (последние 2000):</b>\n"
            f"<pre>{escape_html(error_output[-2000:])}</pre>"
        )

    sent_message_final = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id