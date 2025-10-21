# /opt/tg-bot/modules/notifications.py
import asyncio
import logging
import psutil
import time
import re
import os
from datetime import datetime
from aiogram import F, Dispatcher, types, Bot
from aiogram.types import KeyboardButton
from aiogram.exceptions import TelegramBadRequest

from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message, send_alert
from core.shared_state import (
    LAST_MESSAGE_IDS,
    ALERTS_CONFIG,
    RESOURCE_ALERT_STATE,
    LAST_RESOURCE_ALERT_TIME)
from core.utils import (
    save_alerts_config,
    get_country_flag,
    get_server_timezone_label,
    escape_html)
from core.keyboards import get_alerts_menu_keyboard
from core.config import (
    RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD,
    RESOURCE_ALERT_COOLDOWN
)

BUTTON_TEXT = "🔔 Уведомления"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(notifications_menu_handler)

    # Callbacks
    dp.callback_query(F.data.startswith("toggle_alert_"))(cq_toggle_alert)
    dp.callback_query(F.data == "alert_downtime_stub")(cq_alert_downtime_stub)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    """Возвращает фоновые задачи для запуска в main()"""

    # 1. Монитор ресурсов
    task_resources = asyncio.create_task(
        resource_monitor(bot), name="ResourceMonitor")

    # 2. Монитор SSH
    ssh_log_file_to_monitor = None
    if os.path.exists("/var/log/secure"):
        ssh_log_file_to_monitor = "/var/log/secure"
    elif os.path.exists("/var/log/auth.log"):
        ssh_log_file_to_monitor = "/var/log/auth.log"

    task_logins = None
    if ssh_log_file_to_monitor:
        task_logins = asyncio.create_task(
            reliable_tail_log_monitor(
                bot,
                ssh_log_file_to_monitor,
                "logins",
                parse_ssh_log_line),
            name="LoginsMonitor")
    else:
        logging.warning(
            "Не найден лог SSH. Мониторинг SSH (logins) не запущен.")

    # 3. Монитор F2B
    f2b_log_file_to_monitor = "/var/log/fail2ban.log"
    task_bans = asyncio.create_task(
        reliable_tail_log_monitor(
            bot,
            f2b_log_file_to_monitor,
            "bans",
            parse_f2b_log_line),
        name="BansMonitor")

    tasks = [task_resources, task_bans]
    if task_logins:
        tasks.append(task_logins)

    return tasks

# --- Хэндлеры ---


async def notifications_menu_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "notifications_menu"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id, message.bot)

    keyboard = get_alerts_menu_keyboard(user_id)
    sent_message = await message.answer(
        "🔔 <b>Настройка уведомлений</b>\n\n"
        "Выберите, какие оповещения вы хотите получать.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def cq_toggle_alert(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "toggle_alert_resources"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        alert_type = callback.data.split('_', 2)[-1]
        if alert_type not in ["resources", "logins", "bans"]:
            raise ValueError(f"Неизвестный тип алерта: {alert_type}")
    except Exception as e:
        logging.error(
            f"Ошибка разбора callback_data в cq_toggle_alert: {e} (data: {callback.data})")
        await callback.answer("⚠️ Внутренняя ошибка (неверный callback).", show_alert=True)
        return

    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}

    current_state = ALERTS_CONFIG[user_id].get(alert_type, False)
    new_state = not current_state
    ALERTS_CONFIG[user_id][alert_type] = new_state
    save_alerts_config()

    logging.info(
        f"Пользователь {user_id} изменил '{alert_type}' на {new_state}")
    new_keyboard = get_alerts_menu_keyboard(user_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=new_keyboard)
        if alert_type == "resources":
            alert_name = "Ресурсы"
        elif alert_type == "logins":
            alert_name = "Входы/Выходы SSH"
        else:
            alert_name = "Баны"
        await callback.answer(f"Уведомления '{alert_name}' {'✅ ВКЛЮЧЕНЫ' if new_state else '❌ ОТКЛЮЧЕНЫ'}.")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Состояние уже обновлено.")
        else:
            logging.error(f"Ошибка обновления клавиатуры уведомлений: {e}")
            await callback.answer("⚠️ Ошибка обновления интерфейса.", show_alert=True)
    except Exception as e:
        logging.error(f"Критическая ошибка в cq_toggle_alert: {e}")
        await callback.answer("⚠️ Критическая ошибка.", show_alert=True)


async def cq_alert_downtime_stub(callback: types.CallbackQuery):
    await callback.answer(
        "⏳ Функция уведомлений о даунтайме сервера находится в разработке.\n"
        "Пока рекомендуем использовать внешние сервисы мониторинга (например, UptimeRobot).",
        show_alert=True
    )

# --- Парсеры логов ---


async def parse_ssh_log_line(line: str) -> str | None:
    match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
    if match:
        try:
            user = escape_html(match.group(1))
            ip = escape_html(match.group(2))
            flag = await asyncio.to_thread(get_country_flag, ip)
            tz_label = get_server_timezone_label()
            now_time = datetime.now().strftime('%H:%M:%S')
            return (f"🔔 <b>Обнаружен вход SSH</b>\n\n"
                    f"👤 Пользователь: <b>{user}</b>\n"
                    f"🌍 IP: <b>{flag} {ip}</b>\n"
                    f"⏰ Время: <b>{now_time}</b>{tz_label}")
        except Exception as e:
            logging.warning(f"parse_ssh_log_line: Ошибка парсинга: {e}")
            return None
    return None


async def parse_f2b_log_line(line: str) -> str | None:
    match = re.search(r"fail2ban\.actions.* Ban\s+(\S+)", line)
    if match:
        try:
            ip = escape_html(match.group(1).strip(" \n\t,"))
            flag = await asyncio.to_thread(get_country_flag, ip)
            tz_label = get_server_timezone_label()
            now_time = datetime.now().strftime('%H:%M:%S')
            return (f"🛡️ <b>Fail2Ban забанил IP</b>\n\n"
                    f"🌍 IP: <b>{flag} {ip}</b>\n"
                    f"⏰ Время: <b>{now_time}</b>{tz_label}")
        except Exception as e:
            logging.warning(f"parse_f2b_log_line: Ошибка парсинга: {e}")
            return None
    return None

# --- Фоновые задачи ---


async def resource_monitor(bot: Bot):
    global RESOURCE_ALERT_STATE, LAST_RESOURCE_ALERT_TIME
    logging.info("Монитор ресурсов запущен.")
    await asyncio.sleep(15)

    while True:
        try:
            def check_resources_sync():
                cpu = psutil.cpu_percent(interval=1)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage('/').percent
                return cpu, ram, disk

            cpu_usage, ram_usage, disk_usage = await asyncio.to_thread(check_resources_sync)
            logging.debug(
                f"Проверка ресурсов: CPU={cpu_usage}%, RAM={ram_usage}%, Disk={disk_usage}%")

            alerts_to_send = []
            current_time = time.time()

            # Логика CPU
            if cpu_usage >= CPU_THRESHOLD:
                if not RESOURCE_ALERT_STATE["cpu"]:
                    msg = f"⚠️ <b>Превышен порог CPU!</b>\nТекущее использование: <b>{cpu_usage:.1f}%</b> (Порог: {CPU_THRESHOLD}%)"
                    alerts_to_send.append(msg)
                    logging.info("Сгенерирован алерт CPU.")
                    RESOURCE_ALERT_STATE["cpu"] = True
                    LAST_RESOURCE_ALERT_TIME["cpu"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["cpu"] > RESOURCE_ALERT_COOLDOWN:
                    msg = f"‼️ <b>CPU все еще ВЫСОКИЙ!</b>\nТекущее использование: <b>{cpu_usage:.1f}%</b> (Порог: {CPU_THRESHOLD}%)"
                    alerts_to_send.append(msg)
                    logging.info("Сгенерирован повторный алерт CPU.")
                    LAST_RESOURCE_ALERT_TIME["cpu"] = current_time
            elif cpu_usage < CPU_THRESHOLD and RESOURCE_ALERT_STATE["cpu"]:
                alerts_to_send.append(
                    f"✅ <b>Нагрузка CPU нормализовалась.</b>\nТекущее использование: <b>{cpu_usage:.1f}%</b>")
                logging.info("Сгенерирован алерт нормализации CPU.")
                RESOURCE_ALERT_STATE["cpu"] = False
                LAST_RESOURCE_ALERT_TIME["cpu"] = 0

            # Логика RAM
            if ram_usage >= RAM_THRESHOLD:
                if not RESOURCE_ALERT_STATE["ram"]:
                    msg = f"⚠️ <b>Превышен порог RAM!</b>\nТекущее использование: <b>{ram_usage:.1f}%</b> (Порог: {RAM_THRESHOLD}%)"
                    alerts_to_send.append(msg)
                    logging.info("Сгенерирован алерт RAM.")
                    RESOURCE_ALERT_STATE["ram"] = True
                    LAST_RESOURCE_ALERT_TIME["ram"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["ram"] > RESOURCE_ALERT_COOLDOWN:
                    msg = f"‼️ <b>RAM все еще ВЫСОКАЯ!</b>\nТекущее использование: <b>{ram_usage:.1f}%</b> (Порог: {RAM_THRESHOLD}%)"
                    alerts_to_send.append(msg)
                    logging.info("Сгенерирован повторный алерт RAM.")
                    LAST_RESOURCE_ALERT_TIME["ram"] = current_time
            elif ram_usage < RAM_THRESHOLD and RESOURCE_ALERT_STATE["ram"]:
                alerts_to_send.append(
                    f"✅ <b>Использование RAM нормализовалось.</b>\nТекущее использование: <b>{ram_usage:.1f}%</b>")
                logging.info("Сгенерирован алерт нормализации RAM.")
                RESOURCE_ALERT_STATE["ram"] = False
                LAST_RESOURCE_ALERT_TIME["ram"] = 0

            # Логика Disk
            if disk_usage >= DISK_THRESHOLD:
                if not RESOURCE_ALERT_STATE["disk"]:
                    msg = f"⚠️ <b>Превышен порог Disk!</b>\nТекущее использование: <b>{disk_usage:.1f}%</b> (Порог: {DISK_THRESHOLD}%)"
                    alerts_to_send.append(msg)
                    logging.info("Сгенерирован алерт Disk.")
                    RESOURCE_ALERT_STATE["disk"] = True
                    LAST_RESOURCE_ALERT_TIME["disk"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["disk"] > RESOURCE_ALERT_COOLDOWN:
                    msg = f"‼️ <b>Disk все еще ВЫСОКИЙ!</b>\nТекущее использование: <b>{disk_usage:.1f}%</b> (Порог: {DISK_THRESHOLD}%)"
                    alerts_to_send.append(msg)
                    logging.info("Сгенерирован повторный алерт Disk.")
                    LAST_RESOURCE_ALERT_TIME["disk"] = current_time
            elif disk_usage < DISK_THRESHOLD and RESOURCE_ALERT_STATE["disk"]:
                alerts_to_send.append(
                    f"✅ <b>Использование Disk нормализовалось.</b>\nТекущее использование: <b>{disk_usage:.1f}%</b>")
                logging.info("Сгенерирован алерт нормализации Disk.")
                RESOURCE_ALERT_STATE["disk"] = False
                LAST_RESOURCE_ALERT_TIME["disk"] = 0

            if alerts_to_send:
                full_alert_message = "\n\n".join(alerts_to_send)
                await send_alert(bot, full_alert_message, "resources")

        except Exception as e:
            logging.error(f"Ошибка в мониторе ресурсов: {e}")

        await asyncio.sleep(RESOURCE_CHECK_INTERVAL)

# --- [НАЧАЛО ИСПРАВЛЕНИЯ] ---
# Вложенные функции для безопасного чтения потоков


async def _read_stdout(process, alert_type, parse_function, close_event):
    """Читает stdout процесса, пока он не закроется."""
    try:
        async for line in process.stdout:
            try:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    message = await parse_function(line_str)
                    if message:
                        await send_alert(process.bot_ref, message, alert_type)
            except Exception as e:
                logging.error(
                    f"Монитор {alert_type} (stdout): Ошибка парсинга строки: {e}")
    except Exception as e:
        # Эта ошибка (например, CancelledError) не должна приводить к падению,
        # но мы должны ее залогировать, если это не отмена.
        if not isinstance(e, asyncio.CancelledError):
            logging.error(
                f"Монитор {alert_type} (stdout): Ошибка чтения потока: {e}")
    finally:
        logging.info(f"Монитор {alert_type}: stdout ридер завершен.")
        close_event.set()  # Сигнализируем, что мы закончили


async def _read_stderr(process, alert_type, close_event):
    """Читает stderr процесса, пока он не закроется."""
    try:
        async for line in process.stderr:
            try:
                stderr_str = line.decode('utf-8', errors='ignore').strip()
                if stderr_str:
                    logging.warning(
                        f"Монитор {alert_type} (tail stderr): {stderr_str}")
            except Exception as e:
                logging.error(
                    f"Монитор {alert_type} (stderr): Ошибка парсинга строки: {e}")
    except Exception as e:
        if not isinstance(e, asyncio.CancelledError):
            logging.error(
                f"Монитор {alert_type} (stderr): Ошибка чтения потока: {e}")
    finally:
        logging.info(f"Монитор {alert_type}: stderr ридер завершен.")
        close_event.set()  # Сигнализируем, что мы закончили


async def reliable_tail_log_monitor(
        bot: Bot,
        log_file_path: str,
        alert_type: str,
        parse_function: callable):
    process = None
    # Создаем эвенты *вне* цикла, чтобы к ним был доступ в finally при отмене
    stdout_closed = asyncio.Event()
    stderr_closed = asyncio.Event()
    stdout_task = None
    stderr_task = None

    try:
        while True:
            # Сбрасываем эвенты в начале каждой итерации
            stdout_closed.clear()
            stderr_closed.clear()
            process = None  # Убеждаемся, что процесс сброшен
            stdout_task = None
            stderr_task = None

            if not await asyncio.to_thread(os.path.exists, log_file_path):
                logging.warning(
                    f"Монитор: {log_file_path} не найден. Проверка через 60с.")
                await asyncio.sleep(60)
                continue

            logging.info(
                f"Запуск (или перезапуск) монитора {alert_type} для {log_file_path}")
            try:
                process = await asyncio.create_subprocess_shell(
                    f"tail -n 0 -f {log_file_path}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                # Сохраняем ссылку на бота в объекте процесса для доступа из
                # _read_stdout
                process.bot_ref = bot
                logging.info(
                    f"Монитор {alert_type} (PID: {process.pid}) следит за {log_file_path}")

                # Запускаем задачи чтения
                stdout_task = asyncio.create_task(
                    _read_stdout(
                        process,
                        alert_type,
                        parse_function,
                        stdout_closed))
                stderr_task = asyncio.create_task(
                    _read_stderr(process, alert_type, stderr_closed))

                # Ждем завершения *самого* процесса tail
                return_code = await process.wait()

                logging.warning(
                    f"Процесс 'tail' для {alert_type} (PID: {process.pid}) умер с кодом {return_code}. Ожидание ридеров...")

                # Даем ридерам 2 секунды, чтобы обработать EOF и закрыться
                # штатно
                try:
                    await asyncio.wait_for(asyncio.gather(stdout_closed.wait(), stderr_closed.wait()), timeout=2.0)
                    logging.info(
                        f"Монитор {alert_type}: Оба ридера штатно завершились.")
                except asyncio.TimeoutError:
                    logging.warning(
                        f"Монитор {alert_type}: Таймаут ожидания закрытия ридеров. Принудительная отмена.")

            except PermissionError:
                logging.warning(
                    f"Монитор: Нет прав на чтение {log_file_path}. Проверка через 60с.")
                await asyncio.sleep(60)
            except Exception as e:
                pid_info = f"(PID: {process.pid})" if process else ""
                logging.error(
                    f"Критическая ошибка во внутреннем цикле reliable_tail_log_monitor ({log_file_path}) {pid_info}: {e}")

            finally:
                # Этот 'finally' сработает, когда 'tail' умрет или произойдет ошибка (PermissionError и др.)
                # Он отменит задачи чтения, если они еще не завершились
                if stdout_task and not stdout_task.done():
                    stdout_task.cancel()
                    logging.debug(
                        f"Монитор {alert_type}: Отмена задачи stdout...")
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    logging.debug(
                        f"Монитор {alert_type}: Отмена задачи stderr...")

                # Ждем завершения отмененных задач
                if stdout_task:
                    await asyncio.gather(stdout_task, return_exceptions=True)
                if stderr_task:
                    await asyncio.gather(stderr_task, return_exceptions=True)

                # Если процесс еще жив (маловероятно, но возможно)
                if process and process.returncode is None:
                    try:
                        process.terminate()
                        logging.warning(
                            f"Монитор {alert_type}: Принудительное завершение 'tail' (PID: {process.pid}).")
                    except ProcessLookupError:
                        pass

                process = None
                logging.info(
                    f"Монитор {alert_type}: Пауза 5 сек перед перезапуском...")
                # Пауза перед перезапуском внешнего цикла while True
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        logging.info(f"Монитор {alert_type} отменен (штатное завершение).")

    finally:
        # Этот 'finally' сработает только при полной остановке бота
        # (CancelledError)
        pid = process.pid if process else None
        logging.info(
            f"Завершение работы монитора {alert_type}, попытка остановки 'tail' (PID: {pid})...")

        # Отменяем задачи чтения, если они еще живы
        if stdout_task and not stdout_task.done():
            stdout_task.cancel()
        if stderr_task and not stderr_task.done():
            stderr_task.cancel()

        # Ждем их завершения
        if stdout_task or stderr_task:
            tasks_to_wait = [t for t in (stdout_task, stderr_task) if t]
            await asyncio.gather(*tasks_to_wait, return_exceptions=True)
            logging.info(f"Монитор {alert_type}: Задачи чтения остановлены.")

        # Убиваем процесс 'tail'
        if process and process.returncode is None:
            logging.info(
                f"Монитор {alert_type}: Остановка процесса tail (PID: {pid}).")
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                    logging.info(
                        f"Монитор {alert_type}: 'tail' (PID: {pid}) успешно остановлен (terminate).")
                except asyncio.TimeoutError:
                    logging.warning(
                        f"Монитор {alert_type}: 'tail' (PID: {pid}) не завершился за 2 сек. Попытка kill().")
                    try:
                        process.kill()
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                        logging.info(
                            f"Монитор {alert_type}: 'tail' (PID: {pid}) успешно убит (kill).")
                    except Exception:
                        pass
            except Exception:
                pass
        elif process:
            logging.info(
                f"Монитор {alert_type}: 'tail' (PID: {pid}) уже был завершен (код: {process.returncode}).")
        else:
            logging.info(
                f"Монитор {alert_type}: Процесс tail не был запущен или уже был очищен.")
# --- [КОНЕЦ ИСПРАВЛЕНИЯ] ---
