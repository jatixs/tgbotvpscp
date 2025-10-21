# /opt/tg-bot/modules/selftest.py
import asyncio
import psutil
import time
import re
import os
import logging
from datetime import datetime
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import format_uptime, format_traffic, get_country_flag, get_server_timezone_label
from core.config import INSTALL_MODE

BUTTON_TEXT = "🛠 Сведения о сервере"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(selftest_handler)


async def selftest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "selftest"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)

    sent_message = await message.answer("🔍 Собираю сведения о сервере...")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    def get_system_stats_sync():
        psutil.cpu_percent(interval=None)
        time.sleep(0.2)
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        with open("/proc/uptime") as f:
            uptime_sec = float(f.readline().split()[0])
        counters = psutil.net_io_counters()
        rx = counters.bytes_recv
        tx = counters.bytes_sent
        return cpu, mem, disk, uptime_sec, rx, tx

    try:
        cpu, mem, disk, uptime_sec, rx, tx = await asyncio.to_thread(get_system_stats_sync)
    except Exception as e:
        logging.error(f"Ошибка при сборе системной статистики: {e}")
        await message.bot.edit_message_text(f"⚠️ Ошибка при сборе системной статистики: {e}", chat_id=chat_id, message_id=sent_message.message_id)
        return

    uptime_str = format_uptime(uptime_sec)

    ping_cmd = "ping -c 1 -W 1 8.8.8.8"
    ping_process = await asyncio.create_subprocess_shell(
        ping_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    ping_stdout, _ = await ping_process.communicate()
    ping_result = ping_stdout.decode()
    ping_match = re.search(r"time=([\d\.]+) ms", ping_result)
    ping_time = ping_match.group(1) if ping_match else "N/A"
    internet = "✅ Интернет доступен" if ping_match else "❌ Нет интернета"

    ip_cmd = "curl -4 -s --max-time 3 ifconfig.me"
    ip_process = await asyncio.create_subprocess_shell(
        ip_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    ip_stdout, _ = await ip_process.communicate()
    external_ip = ip_stdout.decode().strip() or "Не удалось определить"

    last_login_info = ""
    if INSTALL_MODE == "root":
        try:
            log_file = None
            if await asyncio.to_thread(os.path.exists, "/var/log/secure"):
                log_file = "/var/log/secure"
            elif await asyncio.to_thread(os.path.exists, "/var/log/auth.log"):
                log_file = "/var/log/auth.log"

            line = None
            source = ""

            if log_file:
                source = f" (из {os.path.basename(log_file)})"
                cmd = f"tail -n 100 {log_file}"
                process = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    raise Exception(stderr.decode())

                for l in reversed(stdout.decode().strip().split('\n')):
                    if "Accepted" in l and "sshd" in l:
                        line = l.strip()
                        break
            else:
                source = " (из journalctl)"
                cmd = "journalctl -u ssh --no-pager -g 'Accepted' | tail -n 1"
                process = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
                except asyncio.TimeoutError:
                    raise Exception("journalctl завис (тайм-аут 5с)")

                if process.returncode != 0:
                    raise Exception(stderr.decode())
                line = stdout.decode().strip()

            if line:
                dt_object = None
                date_match_iso = re.search(
                    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                date_match_syslog = re.search(
                    r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

                try:
                    if date_match_iso:
                        dt_object = datetime.strptime(
                            date_match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                    elif date_match_syslog:
                        log_timestamp = datetime.strptime(
                            date_match_syslog.group(1), "%b %d %H:%M:%S")
                        current_year = datetime.now().year
                        dt_object = log_timestamp.replace(year=current_year)
                        if dt_object > datetime.now():
                            dt_object = dt_object.replace(
                                year=current_year - 1)
                except Exception as e:
                    logging.warning(
                        f"Selftest: не удалось распарсить дату: {e}. Строка: {line}")

                login_match = re.search(
                    r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)

                if dt_object and login_match:
                    user = login_match.group(1)
                    ip = login_match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)

                    tz_label = get_server_timezone_label()
                    formatted_time = dt_object.strftime("%H:%M")
                    formatted_date = dt_object.strftime("%d.%m.%Y")

                    last_login_info = (
                        f"\n\n📄 <b>Последний SSH-вход{source}:</b>\n"
                        f"👤 <b>{user}</b>\n"
                        f"🌍 IP: <b>{flag} {ip}</b>\n"
                        f"⏰ Время: <b>{formatted_time}</b>{tz_label}\n"
                        f"🗓️ Дата: <b>{formatted_date}</b>"
                    )
                else:
                    logging.warning(
                        f"Selftest: Не удалось разобрать строку SSH (login_match={login_match}, dt_object={dt_object}): {line}")
                    last_login_info = f"\n\n📄 <b>Последний SSH-вход{source}:</b>\nНе удалось разобрать строку лога."
            else:
                last_login_info = f"\n\n📄 <b>Последний SSH-вход{source}:</b>\nНе найдено записей."

        except Exception as e:
            logging.warning(f"SSH log check skipped: {e}")
            last_login_info = f"\n\n📄 <b>Последний SSH-вход:</b>\n⏳ Ошибка чтения логов: {e}"
    else:
        last_login_info = "\n\n📄 <b>Последний SSH-вход:</b>\n<i>Информация доступна только в режиме root</i>"

    response_text = (
        f"🛠 <b>Состояние сервера:</b>\n\n"
        f"✅ Бот работает\n"
        f"📊 Процессор: <b>{cpu:.1f}%</b>\n"
        f"💾 ОЗУ: <b>{mem:.1f}%</b>\n"
        f"💽 ПЗУ: <b>{disk:.1f}%</b>\n"
        f"⏱ Время работы: <b>{uptime_str}</b>\n"
        f"{internet}\n"
        f"⌛ Задержка (8.8.8.8): <b>{ping_time} мс</b>\n"
        f"🌐 Внешний IP: <code>{external_ip}</code>\n"
        f"📡 Трафик ⬇ <b>{format_traffic(rx)}</b> / ⬆ <b>{format_traffic(tx)}</b>")

    response_text += last_login_info

    await message.bot.edit_message_text(response_text, chat_id=chat_id, message_id=sent_message.message_id, parse_mode="HTML")
