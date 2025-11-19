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

from core.i18n import _, I18nFilter, get_user_lang
from core import config
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
    escape_html,
    get_host_path)
from core.keyboards import get_alerts_menu_keyboard
from core.config import (
    RESOURCE_CHECK_INTERVAL, CPU_THRESHOLD, RAM_THRESHOLD, DISK_THRESHOLD,
    RESOURCE_ALERT_COOLDOWN
)

BUTTON_KEY = "btn_notifications"

def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(notifications_menu_handler)
    dp.callback_query(F.data.startswith("toggle_alert_"))(cq_toggle_alert)
    dp.callback_query(F.data == "alert_downtime_stub")(cq_alert_downtime_stub)

def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    """Запускает фоновые задачи мониторинга (ресурсы, SSH логи, Fail2Ban логи)."""
    
    # 1. Мониторинг ресурсов (CPU/RAM/Disk)
    task_resources = asyncio.create_task(
        resource_monitor(bot), name="ResourceMonitor")

    # 2. Мониторинг SSH (ищем нужный лог файл)
    ssh_log_file_to_monitor = None
    secure_path = get_host_path("/var/log/secure") # Для RHEL/CentOS
    auth_path = get_host_path("/var/log/auth.log") # Для Debian/Ubuntu

    if os.path.exists(secure_path):
        ssh_log_file_to_monitor = secure_path
    elif os.path.exists(auth_path):
        ssh_log_file_to_monitor = auth_path

    task_logins = None
    if ssh_log_file_to_monitor:
        task_logins = asyncio.create_task(
            reliable_tail_log_monitor(
                bot,
                ssh_log_file_to_monitor,
                "logins",
                parse_ssh_log_line), # Используем парсер, возвращающий dict
            name="LoginsMonitor")
    else:
        logging.warning(
            "Не найден лог SSH. Мониторинг SSH (logins) не запущен.")

    # 3. Мониторинг Fail2Ban
    f2b_log_file_to_monitor = get_host_path("/var/log/fail2ban.log")
    task_bans = asyncio.create_task(
        reliable_tail_log_monitor(
            bot,
            f2b_log_file_to_monitor,
            "bans",
            parse_f2b_log_line), # Используем парсер, возвращающий dict
        name="BansMonitor")

    tasks = [task_resources, task_bans]
    if task_logins:
        tasks.append(task_logins)

    return tasks

# --- Хэндлеры меню ---

async def notifications_menu_handler(message: types.Message):
    """Отображает меню настроек уведомлений."""
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    command = "notifications_menu"

    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, message.chat.id, command)
        return

    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    keyboard = get_alerts_menu_keyboard(user_id)
    sent_message = await message.answer(
        _("notifications_menu_title", lang),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def cq_toggle_alert(callback: types.CallbackQuery):
    """Переключает состояние (вкл/выкл) конкретного типа уведомления."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not is_allowed(
            user_id,
            "toggle_alert_resources"):
        await callback.answer(_("access_denied_generic", lang), show_alert=True)
        return

    try:
        # Извлекаем тип алерта из callback_data (toggle_alert_resources -> resources)
        alert_type = callback.data.split('_', 2)[-1]
        if alert_type not in ["resources", "logins", "bans"]:
            raise ValueError(f"Неизвестный тип алерта: {alert_type}")
    except Exception as e:
        logging.error(
            f"Ошибка разбора callback_data в cq_toggle_alert: {e} (data: {callback.data})")
        await callback.answer(_("error_internal", lang) + " (invalid callback)", show_alert=True)
        return

    if user_id not in ALERTS_CONFIG:
        ALERTS_CONFIG[user_id] = {}

    # Переключаем значение
    current_state = ALERTS_CONFIG[user_id].get(alert_type, False)
    new_state = not current_state
    ALERTS_CONFIG[user_id][alert_type] = new_state
    save_alerts_config()

    logging.info(
        f"Пользователь {user_id} изменил '{alert_type}' на {new_state}")
    
    # Обновляем клавиатуру
    new_keyboard = get_alerts_menu_keyboard(user_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=new_keyboard)
        
        # Формируем текст уведомления о переключении
        alert_name_map = {
            "resources": "notifications_alert_name_res",
            "logins": "notifications_alert_name_logins",
            "bans": "notifications_alert_name_bans"
        }
        alert_name = _(alert_name_map.get(alert_type, "error_internal"), lang)
        status_text = _(
            "notifications_status_on",
            lang) if new_state else _(
            "notifications_status_off",
            lang)

        await callback.answer(_("notifications_toggle_alert", lang, alert_name=alert_name, status=status_text))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer(_("users_already_here", lang))
        else:
            logging.error(f"Ошибка обновления клавиатуры уведомлений: {e}")
            await callback.answer(_("error_unexpected", lang), show_alert=True)
    except Exception as e:
        logging.error(f"Критическая ошибка в cq_toggle_alert: {e}")
        await callback.answer(_("error_unexpected", lang), show_alert=True)

async def cq_alert_downtime_stub(callback: types.CallbackQuery):
    """Заглушка для функции даунтайма."""
    lang = get_user_lang(callback.from_user.id)
    await callback.answer(
        _("notifications_downtime_stub", lang),
        show_alert=True
    )

# --- Парсеры логов (Возвращают словарь с данными, а не готовый текст) ---

async def parse_ssh_log_line(line: str) -> dict | None:
    """
    Парсит строку SSH лога. Возвращает словарь {key, params} для i18n.
    """
    match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
    if match:
        try:
            user = escape_html(match.group(1))
            ip = escape_html(match.group(2))
            flag = await asyncio.to_thread(get_country_flag, ip)
            tz_label = get_server_timezone_label()
            now_time = datetime.now().strftime('%H:%M:%S')
            
            return {
                "key": "alert_ssh_login_detected",
                "params": {
                    "user": user,
                    "flag": flag,
                    "ip": ip,
                    "time": now_time,
                    "tz": tz_label
                }
            }
        except Exception as e:
            logging.warning(f"parse_ssh_log_line: Ошибка парсинга: {e}")
            return None
    return None

async def parse_f2b_log_line(line: str) -> dict | None:
    """
    Парсит строку Fail2Ban лога. Возвращает словарь {key, params} для i18n.
    """
    match = re.search(r"fail2ban\.actions.* Ban\s+(\S+)", line)
    if match:
        try:
            ip = escape_html(match.group(1).strip(" \n\t,"))
            flag = await asyncio.to_thread(get_country_flag, ip)
            tz_label = get_server_timezone_label()
            now_time = datetime.now().strftime('%H:%M:%S')
            
            return {
                "key": "alert_f2b_ban_detected",
                "params": {
                    "flag": flag,
                    "ip": ip,
                    "time": now_time,
                    "tz": tz_label
                }
            }
        except Exception as e:
            logging.warning(f"parse_f2b_log_line: Ошибка парсинга: {e}")
            return None
    return None

# --- Фоновые задачи ---

async def resource_monitor(bot: Bot):
    """
    Мониторит CPU, RAM, Disk.
    Отправляет алерты, если превышены пороги.
    """
    global RESOURCE_ALERT_STATE, LAST_RESOURCE_ALERT_TIME
    logging.info("Монитор ресурсов запущен.")
    await asyncio.sleep(15) # Даем системе прогрузиться

    while True:
        try:
            def check_resources_sync():
                cpu = psutil.cpu_percent(interval=1)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage(get_host_path('/')).percent
                return cpu, ram, disk

            cpu_usage, ram_usage, disk_usage = await asyncio.to_thread(check_resources_sync)
            logging.debug(
                f"Проверка ресурсов: CPU={cpu_usage}%, RAM={ram_usage}%, Disk={disk_usage}%")

            # Список кортежей (ключ_i18n, параметры) для всех сработавших алертов
            alerts_data = []
            current_time = time.time()

            # --- Логика CPU ---
            if cpu_usage >= CPU_THRESHOLD:
                if not RESOURCE_ALERT_STATE["cpu"]:
                    alerts_data.append(("alert_cpu_high", {"usage": cpu_usage, "threshold": CPU_THRESHOLD}))
                    logging.info("Сгенерирован алерт CPU.")
                    RESOURCE_ALERT_STATE["cpu"] = True
                    LAST_RESOURCE_ALERT_TIME["cpu"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["cpu"] > RESOURCE_ALERT_COOLDOWN:
                    # Повторный алерт
                    alerts_data.append(("alert_cpu_high_repeat", {"usage": cpu_usage, "threshold": CPU_THRESHOLD}))
                    logging.info("Сгенерирован повторный алерт CPU.")
                    LAST_RESOURCE_ALERT_TIME["cpu"] = current_time
            elif cpu_usage < CPU_THRESHOLD and RESOURCE_ALERT_STATE["cpu"]:
                # Нормализация
                alerts_data.append(("alert_cpu_normal", {"usage": cpu_usage}))
                logging.info("Сгенерирован алерт нормализации CPU.")
                RESOURCE_ALERT_STATE["cpu"] = False
                LAST_RESOURCE_ALERT_TIME["cpu"] = 0

            # --- Логика RAM ---
            if ram_usage >= RAM_THRESHOLD:
                if not RESOURCE_ALERT_STATE["ram"]:
                    alerts_data.append(("alert_ram_high", {"usage": ram_usage, "threshold": RAM_THRESHOLD}))
                    logging.info("Сгенерирован алерт RAM.")
                    RESOURCE_ALERT_STATE["ram"] = True
                    LAST_RESOURCE_ALERT_TIME["ram"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["ram"] > RESOURCE_ALERT_COOLDOWN:
                    alerts_data.append(("alert_ram_high_repeat", {"usage": ram_usage, "threshold": RAM_THRESHOLD}))
                    logging.info("Сгенерирован повторный алерт RAM.")
                    LAST_RESOURCE_ALERT_TIME["ram"] = current_time
            elif ram_usage < RAM_THRESHOLD and RESOURCE_ALERT_STATE["ram"]:
                alerts_data.append(("alert_ram_normal", {"usage": ram_usage}))
                logging.info("Сгенерирован алерт нормализации RAM.")
                RESOURCE_ALERT_STATE["ram"] = False
                LAST_RESOURCE_ALERT_TIME["ram"] = 0

            # --- Логика Disk ---
            if disk_usage >= DISK_THRESHOLD:
                if not RESOURCE_ALERT_STATE["disk"]:
                    alerts_data.append(("alert_disk_high", {"usage": disk_usage, "threshold": DISK_THRESHOLD}))
                    logging.info("Сгенерирован алерт Disk.")
                    RESOURCE_ALERT_STATE["disk"] = True
                    LAST_RESOURCE_ALERT_TIME["disk"] = current_time
                elif current_time - LAST_RESOURCE_ALERT_TIME["disk"] > RESOURCE_ALERT_COOLDOWN:
                    alerts_data.append(("alert_disk_high_repeat", {"usage": disk_usage, "threshold": DISK_THRESHOLD}))
                    logging.info("Сгенерирован повторный алерт Disk.")
                    LAST_RESOURCE_ALERT_TIME["disk"] = current_time
            elif disk_usage < DISK_THRESHOLD and RESOURCE_ALERT_STATE["disk"]:
                alerts_data.append(("alert_disk_normal", {"usage": disk_usage}))
                logging.info("Сгенерирован алерт нормализации Disk.")
                RESOURCE_ALERT_STATE["disk"] = False
                LAST_RESOURCE_ALERT_TIME["disk"] = 0

            # --- Отправка алертов ---
            if alerts_data:
                # Создаем функцию-генератор, которая принимает язык и возвращает переведенный текст
                def alert_text_generator(lang):
                    messages = []
                    for key, params in alerts_data:
                        messages.append(_(key, lang, **params))
                    return "\n\n".join(messages)
                
                # Передаем функцию в send_alert
                await send_alert(bot, alert_text_generator, "resources")

        except Exception as e:
            logging.error(f"Ошибка в мониторе ресурсов: {e}")

        await asyncio.sleep(RESOURCE_CHECK_INTERVAL)


# --- Вспомогательные функции для монитора логов ---

def prepare_log_alert_func(alert_data_dict):
    """
    Превращает словарь данных (key, params) в функцию генерации текста.
    """
    if not alert_data_dict: return None
    key = alert_data_dict.get("key")
    params = alert_data_dict.get("params", {})
    return lambda lang: _(key, lang, **params)

async def _read_stdout(process, alert_type, parse_function, close_event):
    """Читает stdout и отправляет алерты."""
    try:
        async for line in process.stdout:
            try:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str:
                    # parse_function теперь возвращает dict (данные), а не строку
                    alert_data = await parse_function(line_str)
                    if alert_data:
                        # Превращаем данные в функцию-генератор
                        msg_func = prepare_log_alert_func(alert_data)
                        await send_alert(process.bot_ref, msg_func, alert_type)
            except Exception as e:
                logging.error(
                    f"Монитор {alert_type} (stdout): Ошибка парсинга строки: {e}")
    except Exception as e:
        if not isinstance(e, asyncio.CancelledError):
            logging.error(
                f"Монитор {alert_type} (stdout): Ошибка чтения потока: {e}")
    finally:
        logging.info(f"Монитор {alert_type}: stdout ридер завершен.")
        close_event.set()

async def _read_stderr(process, alert_type, close_event):
    """Читает stderr для логирования ошибок tail."""
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
        close_event.set()

async def reliable_tail_log_monitor(
        bot: Bot,
        log_file_path: str,
        alert_type: str,
        parse_function: callable):
    """
    Надежный монитор лог-файла через 'tail -f'.
    Перезапускается при ошибках или ротации логов (через завершение процесса).
    """
    process = None
    stdout_closed = asyncio.Event()
    stderr_closed = asyncio.Event()
    stdout_task = None
    stderr_task = None

    try:
        while True:
            stdout_closed.clear()
            stderr_closed.clear()
            process = None
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
                # Запускаем tail
                process = await asyncio.create_subprocess_shell(
                    f"tail -n 0 -f {log_file_path}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                process.bot_ref = bot
                logging.info(
                    f"Монитор {alert_type} (PID: {process.pid}) следит за {log_file_path}")

                # Запускаем асинхронное чтение потоков
                stdout_task = asyncio.create_task(
                    _read_stdout(
                        process,
                        alert_type,
                        parse_function,
                        stdout_closed))
                stderr_task = asyncio.create_task(
                    _read_stderr(process, alert_type, stderr_closed))

                # Ждем завершения процесса (например, если tail упал)
                return_code = await process.wait()

                logging.warning(
                    f"Процесс 'tail' для {alert_type} (PID: {process.pid}) умер с кодом {return_code}. Ожидание ридеров...")

                # Ждем закрытия потоков
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
                # Очистка задач
                if stdout_task and not stdout_task.done():
                    stdout_task.cancel()
                    logging.debug(
                        f"Монитор {alert_type}: Отмена задачи stdout...")
                if stderr_task and not stderr_task.done():
                    stderr_task.cancel()
                    logging.debug(
                        f"Монитор {alert_type}: Отмена задачи stderr...")

                if stdout_task:
                    await asyncio.gather(stdout_task, return_exceptions=True)
                if stderr_task:
                    await asyncio.gather(stderr_task, return_exceptions=True)

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
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        logging.info(f"Монитор {alert_type} отменен (штатное завершение).")

    finally:
        # Финальная очистка при выходе
        pid = process.pid if process else None
        logging.info(
            f"Завершение работы монитора {alert_type}, попытка остановки 'tail' (PID: {pid})...")

        if stdout_task and not stdout_task.done():
            stdout_task.cancel()
        if stderr_task and not stderr_task.done():
            stderr_task.cancel()

        if stdout_task or stderr_task:
            tasks_to_wait = [t for t in (stdout_task, stderr_task) if t]
            await asyncio.gather(*tasks_to_wait, return_exceptions=True)
            logging.info(f"Монитор {alert_type}: Задачи чтения остановлены.")

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