# /opt/tg-bot/core/i18n.py
import json
import logging
import os
from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from . import config
from . import shared_state

# --- СЛОВАРЬ ПЕРЕВОДОВ ---
STRINGS = {
    'ru': {
        # Общие
        "btn_back": "🔙 Назад",
        "btn_cancel": "❌ Отмена",
        "btn_back_to_menu": "🔙 Назад в меню",
        "btn_confirm": "✅ Подтвердить",
        "status_enabled": "✅",
        "status_disabled": "❌",
        "group_admins": "Админы",
        "group_users": "Пользователи",
        "group_unknown": "Неизвестно",
        "error_internal": "⚠️ Внутренняя ошибка.",
        "error_unexpected": "⚠️ Произошла ошибка.",
        "error_with_details": "⚠️ Произошла ошибка: {error}",
        "error_parsing_json": "❌ Ошибка при обработке результатов: Неверный формат ответа.\n<pre>{output}</pre>",
        "error_unexpected_json_parsing": "❌ Неожиданная ошибка при обработке результатов: {error}",

        # bot.py (Главное меню и Язык)
        "main_menu_welcome": "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu.",
        "language_select": "Пожалуйста, выберите ваш язык:",
        "language_selected": "✅ Язык успешно изменен на Русский.",
        "btn_language": "🇷🇺 Язык",
        "main_menu_placeholder": "Выберите опцию в меню...",

        # core/auth.py
        "access_denied_message": "⛔ Вы не являетесь пользователем бота. Ваш ID: <code>{user_id}</code>.\nК командам нет доступа, обратитесь к администратору.",
        "access_denied_button": "📤 Отправить свой ID администратору",
        "access_denied_generic": "⛔ Доступ запрещен.",
        "access_denied_not_root": "⛔ Эта функция доступна только в режиме 'root'.",
        "access_denied_no_rights": "⛔ У вас нет прав для выполнения этой команды.",
        "default_admin_name": "Главный Админ",
        "default_new_user_name": "Новый_{uid}",
        "default_id_user_name": "ID: {uid}",

        # core/keyboards.py (Кнопки меню)
        "btn_selftest": "🛠 Сведения о сервере",
        "btn_traffic": "📡 Трафик сети",
        "btn_uptime": "⏱ Аптайм",
        "btn_speedtest": "🚀 Скорость сети",
        "btn_top": "🔥 Топ процессов",
        "btn_xray": "🩻 Обновление X-ray",
        "btn_sshlog": "📜 SSH-лог",
        "btn_fail2ban": "🔒 Fail2Ban Log",
        "btn_logs": "📜 Последние события",
        "btn_users": "👤 Пользователи",
        "btn_vless": "🔗 VLESS-ссылка",
        "btn_update": "🔄 Обновление VPS",
        "btn_optimize": "⚡️ Оптимизация",
        "btn_restart": "♻️ Перезапуск бота",
        "btn_reboot": "🔄 Перезагрузка сервера",
        "btn_notifications": "🔔 Уведомления",

        # core/keyboards.py (Инлайн-кнопки)
        "btn_add_user": "➕ Добавить пользователя",
        "btn_delete_user": "➖ Удалить пользователя",
        "btn_change_group": "🔄 Изменить группу",
        "btn_my_id": "🆔 Мой ID",
        "delete_user_button_text": "{user_name} ({group})",
        "delete_self_button_text": "❌ Удалить себя ({user_name}, {group})",
        "btn_group_admins": "👑 Админы",
        "btn_group_users": "👤 Пользователи",
        "btn_reboot_confirm": "✅ Да, перезагрузить",
        "btn_reboot_cancel": "❌ Нет, отмена",
        "alerts_menu_res": "{status} Ресурсы (CPU/RAM/Disk)",
        "alerts_menu_logins": "{status} Входы SSH",
        "alerts_menu_bans": "{status} Баны (Fail2Ban)",
        "alerts_menu_downtime": "⏳ Даунтайм сервера (WIP)",

        # core/utils.py
        "utils_vless_error": "⚠️ Ошибка при генерации VLESS-ссылки: {error}",
        "utils_docker_ps_error": "Не удалось выполнить 'docker ps'. Убедитесь, что Docker установлен и запущен, и у бота есть права.\n<pre>{error}</pre>",
        "utils_bot_restarted": "✅ Бот успешно перезапущен.",
        "utils_server_rebooted": "✅ <b>Сервер успешно перезагружен! Бот снова в сети.</b>",

        # core/messaging.py
        "alert_no_users_for_type": "Нет пользователей с включенными уведомлениями типа '{alert_type}'.",
        "alert_sending_to_users": "Отправка алерта типа '{alert_type}' {count} пользователям...",
        "alert_sent_to_users": "Алерт типа '{alert_type}' отправлен {count} пользователям.",

        # watchdog.py
        "watchdog_alert_prefix": "🚨 <b>Система оповещений (Alert):</b>",
        "watchdog_log_read_error": "Ошибка чтения лога: {error}",
        "watchdog_log_error_found_details": "Обнаружена ОШИБКА: {details}",
        "watchdog_log_error_found_generic": "Обнаружены ошибки (ERROR/CRITICAL) в логе",
        "watchdog_log_exception": "Исключение при чтении лога: {error}",
        "watchdog_status_active_ok": "Сервис <b>{bot_name}</b>: Активен 🟢",
        "watchdog_status_active_error": "Сервис <b>{bot_name}</b>: Активен с ошибками 🟠\n\n<b>Детали:</b> {details}\n\nРекомендуется проверить `bot.log`.",
        "watchdog_status_active_log_fail": "Сервис <b>{bot_name}</b>: Активен 🟢 (Проверка лога не удалась)",
        "watchdog_status_activating": "Сервис <b>{bot_name}</b>: Запускается 🟡",
        "watchdog_status_down": "Сервис <b>{bot_name}</b>: Недоступен 🔴{reason}",
        "watchdog_status_down_reason": "Причина",
        "watchdog_status_down_failed": "Статус: failed",
        "watchdog_restart_fail": "⚠️ Alert-система НЕ СМОГЛА отправить команду перезапуска для <b>{service_name}</b>. Требуется ручная проверка.\nОшибка: {error}",
        "watchdog_systemctl_not_found": "⚠️ <code>systemctl</code> не найден. Не могу проверить статус сервиса.",
        "watchdog_check_error": "⚠️ Ошибка проверки статуса сервиса: {error}",
        "watchdog_started": "🚨 Внутренний сервис 'Система оповещений (Alert)' запущен.\nОтслеживание: <b>{bot_name}</b>",

        # modules/fail2ban.py
        "f2b_log_not_found": "⚠️ Файл лога Fail2Ban не найден: <code>{path}</code>",
        "f2b_log_read_error": "Не удалось прочитать файл лога.",
        "f2b_banned": "Бан",
        "f2b_already_banned": "Уже забанен",
        "f2b_header": "🔒 <b>Последние 10 блокировок IP (Fail2Ban):</b>\n\n{log_output}",
        "f2b_no_bans": "🔒 Нет недавних блокировок IP в логах Fail2Ban (проверено 50 последних строк).",
        "f2b_read_error_generic": "⚠️ Ошибка при чтении журнала Fail2Ban: {error}",
        "f2b_ban_entry": "🔒 <b>{ban_type}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Время: <b>{time}</b>{tz}\n🗓️ Дата: <b>{date}</b>",

        # modules/logs.py
        "logs_header": "📜 <b>Последние системные журналы:</b>\n<pre>{log_output}</pre>",
        "logs_read_error": "⚠️ Ошибка при чтении журналов: {error}",

        # modules/notifications.py
        "notifications_menu_title": "🔔 <b>Настройка уведомлений</b>\n\nВыберите, какие оповещения вы хотите получать.",
        "notifications_toggle_alert": "Уведомления '{alert_name}' {status}",
        "notifications_status_on": "✅ ВКЛЮЧЕНЫ",
        "notifications_status_off": "❌ ОТКЛЮЧЕНЫ",
        "notifications_alert_name_res": "Ресурсы",
        "notifications_alert_name_logins": "Входы/Выходы SSH",
        "notifications_alert_name_bans": "Баны",
        "notifications_downtime_stub": "⏳ Функция уведомлений о даунтайме сервера находится в разработке.\nПока рекомендуем использовать внешние сервисы мониторинга (например, UptimeRobot).",
        "alert_ssh_login_detected": "🔔 <b>Обнаружен вход SSH</b>\n\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Время: <b>{time}</b>{tz}",
        "alert_f2b_ban_detected": "🛡️ <b>Fail2Ban забанил IP</b>\n\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Время: <b>{time}</b>{tz}",
        "alert_cpu_high": "⚠️ <b>Превышен порог CPU!</b>\nТекущее использование: <b>{usage:.1f}%</b> (Порог: {threshold}%)",
        "alert_cpu_high_repeat": "‼️ <b>CPU все еще ВЫСОКИЙ!</b>\nТекущее использование: <b>{usage:.1f}%</b> (Порог: {threshold}%)",
        "alert_cpu_normal": "✅ <b>Нагрузка CPU нормализовалась.</b>\nТекущее использование: <b>{usage:.1f}%</b>",
        "alert_ram_high": "⚠️ <b>Превышен порог RAM!</b>\nТекущее использование: <b>{usage:.1f}%</b> (Порог: {threshold}%)",
        "alert_ram_high_repeat": "‼️ <b>RAM все еще ВЫСОКАЯ!</b>\nТекущее использование: <b>{usage:.1f}%</b> (Порог: {threshold}%)",
        "alert_ram_normal": "✅ <b>Использование RAM нормализовалось.</b>\nТекущее использование: <b>{usage:.1f}%</b>",
        "alert_disk_high": "⚠️ <b>Превышен порог Disk!</b>\nТекущее использование: <b>{usage:.1f}%</b> (Порог: {threshold}%)",
        "alert_disk_high_repeat": "‼️ <b>Disk все еще ВЫСОКИЙ!</b>\nТекущее использование: <b>{usage:.1f}%</b> (Порог: {threshold}%)",
        "alert_disk_normal": "✅ <b>Использование Disk нормализовалось.</b>\nТекущее использование: <b>{usage:.1f}%</b>",

        # modules/optimize.py
        "optimize_start": "⏳ <b>Запускаю оптимизацию системы...</b>\n\nЭто очень долгий процесс (5-15 минут).\nПожалуйста, не перезапускайте бота и не вызывайте другие команды.",
        "optimize_success": "✅ <b>Оптимизация завершена успешно!</b>\n\n<b>Последние 1000 символов вывода (включая sysctl):</b>\n<pre>{output}</pre>",
        "optimize_fail": "❌ <b>Ошибка во время оптимизации!</b>\n\n<b>Код возврата:</b> {code}\n<b>Вывод STDOUT (последние 1000):</b>\n<pre>{stdout}</pre>\n<b>Вывод STDERR (последние 2000):</b>\n<pre>{stderr}</pre>",

        # modules/reboot.py
        "reboot_confirm_prompt": "⚠️ Вы уверены, что хотите <b>перезагрузить сервер</b>? Все активные соединения будут разорваны.",
        "reboot_confirmed": "✅ Подтверждено. <b>Запускаю перезагрузку VPS</b>...",
        "reboot_error": "⚠️ Ошибка при отправке команды перезагрузки: {error}",

        # modules/restart.py
        "restart_start": "♻️ Бот уходит на перезапуск…",
        "restart_error": "⚠️ Ошибка при попытке перезапуска сервиса: {error}",

        # modules/selftest.py
        "selftest_gathering_info": "🔍 Собираю сведения о сервере...",
        "selftest_error": "⚠️ Ошибка при сборе системной статистики: {error}",
        "selftest_inet_ok": "✅ Интернет доступен",
        "selftest_inet_fail": "❌ Нет интернета",
        "selftest_ip_fail": "Не удалось определить",
        "selftest_ssh_source": "(из {source})",
        "selftest_ssh_source_journal": "(из journalctl)",
        "selftest_ssh_header": "\n\n📄 <b>Последний SSH-вход{source}:</b>\n",
        "selftest_ssh_entry": "👤 <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Время: <b>{time}</b>{tz}\n🗓️ Дата: <b>{date}</b>",
        "selftest_ssh_parse_fail": "Не удалось разобрать строку лога.",
        "selftest_ssh_not_found": "Не найдено записей.",
        "selftest_ssh_read_error": "⏳ Ошибка чтения логов: {error}",
        "selftest_ssh_root_only": "\n\n📄 <b>Последний SSH-вход:</b>\n<i>Информация доступна только в режиме root</i>",
        "selftest_results_header": "🛠 <b>Состояние сервера:</b>\n\n",
        "selftest_results_body": "✅ Бот работает\n📊 Процессор: <b>{cpu:.1f}%</b>\n💾 ОЗУ: <b>{mem:.1f}%</b>\n💽 ПЗУ: <b>{disk:.1f}%</b>\n⏱ Время работы: <b>{uptime}</b>\n{inet_status}\n⌛ Задержка (8.8.8.8): <b>{ping} мс</b>\n🌐 Внешний IP: <code>{ip}</code>\n📡 Трафик ⬇ <b>{rx}</b> / ⬆ <b>{tx}</b>",

        # modules/speedtest.py
        "speedtest_start": "🚀 Запуск speedtest... Это может занять до минуты.",
        "speedtest_results": "🚀 <b>Speedtest Результаты:</b>\n\n⬇️ <b>Скачивание:</b> {dl:.2f} Мбит/с\n⬆️ <b>Загрузка:</b> {ul:.2f} Мбит/с\n⏱ <b>Пинг:</b> {ping} мс\n\n🏢 <b>Сервер:</b> {server} ({location})\n🔗 <b>Подробнее:</b> {url}",
        "speedtest_fail": "❌ Ошибка при запуске speedtest:\n<pre>{error}</pre>",

        # modules/sshlog.py
        "sshlog_searching": "🔍 Ищу последние 10 событий SSH (вход/провал)...",
        "sshlog_header": "🔐 <b>Последние {count} событий SSH{source}:</b>\n\n{log_output}",
        "sshlog_not_found": "🔐 Не найдено событий SSH (вход/провал){source}.",
        "sshlog_read_error": "⚠️ Ошибка при чтении журнала SSH: {error}",
        "sshlog_entry_success": "✅ <b>Успешный вход</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",
        "sshlog_entry_invalid_user": "❌ <b>Неверный юзер</b>\n👤 Попытка: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",
        "sshlog_entry_wrong_pass": "❌ <b>Неверный пароль</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",
        "sshlog_entry_fail_pam": "❌ <b>Провал (PAM)</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",

        # modules/top.py
        "top_header": "🔥 <b>Топ 10 процессов по загрузке CPU:</b>\n<pre>{output}</pre>",
        "top_fail": "❌ Ошибка при получении списка процессов:\n<pre>{error}</pre>",

        # modules/traffic.py
        "traffic_stop": "✅ Мониторинг трафика остановлен.",
        "traffic_menu_return": "🏠 Главное меню:",
        "traffic_start": "📡 <b>Мониторинг трафика включен</b>...\n\n<i>Обновление каждые 5 секунд. Нажмите '📡 Трафик сети' еще раз, чтобы остановить.</i>",
        "traffic_start_fail": "⚠️ Не удалось запустить мониторинг трафика: {error}",
        "traffic_update_total": "📡 Общий трафик:",
        "traffic_update_speed": "⚡️ Скорость соединения:",
        "traffic_rx": "⬇️ RX: {value}",
        "traffic_tx": "⬆️ TX: {value}",
        "traffic_speed_rx": "⬇️ RX: {speed:.2f} Мбит/с",
        "traffic_speed_tx": "⬆️ TX: {speed:.2f} Мбит/с",

        # modules/update.py
        "update_start": "🔄 Выполняю обновление VPS... Это может занять несколько минут.",
        "update_success": "✅ Обновление завершено:\n<pre>{output}</pre>",
        "update_fail": "❌ Ошибка при обновлении (Код: {code}):\n<pre>{error}</pre>",

        # modules/uptime.py
        "uptime_text": "⏱ Время работы: <b>{uptime}</b>",
        "uptime_fail": "⚠️ Ошибка при получении аптайма: {error}",

        # modules/vless.py
        "vless_prompt_file": "📤 <b>Отправьте файл конфигурации Xray (JSON)</b>\n\n<i>Важно: файл должен содержать рабочую конфигурацию outbound с Reality.</i>",
        "vless_error_not_json": "⛔ <b>Ошибка:</b> Файл должен быть формата <code>.json</code>.\n\nПопробуйте отправить файл еще раз.",
        "vless_prompt_name": "✅ Файл JSON получен.\n\nТеперь <b>введите имя</b> для этой VLESS-ссылки (например, 'My_Server_1'):",
        "vless_error_file_processing": "⚠️ Произошла ошибка при обработке файла: {error}",
        "vless_error_no_json_session": "⚠️ Ошибка: Данные JSON не найдены в сессии. Попробуйте сначала.",
        "vless_success_caption": "✅ Ваша VLESS-ссылка с именем '<b>{name}</b>' готова:\n\n<code>{url}</code>",
        "vless_menu_return": "🏠 Возврат в главное меню.",
        "vless_error_not_file": "⛔ Пожалуйста, отправьте <b>документ</b> (файл), а не текст.",
        "vless_error_not_text": "⛔ Пожалуйста, отправьте <b>текстовое имя</b>.",

        # modules/xray.py
        "xray_detecting": "🔍 Определяю установленный клиент Xray...",
        "xray_detect_fail": "❌ Не удалось определить поддерживаемый клиент Xray (Marzban, Amnezia). Обновление невозможно.",
        "xray_detected_start_update": "✅ Обнаружен: <b>{client}</b> (контейнер: <code>{container}</code>). Начинаю обновление...",
        "xray_update_error": "Процесс обновления {client} завершился с ошибкой:\n<pre>{error}</pre>",
        "xray_update_success": "✅ Xray для <b>{client}</b> успешно обновлен до версии <b>{version}</b>",
        "xray_error_generic": "⚠️ <b>Ошибка обновления Xray:</b>\n\n{error}",
        "xray_version_unknown": "неизвестной",

        # modules/users.py (Добавления)
        "users_group_Admins": "Админы",
        "users_group_Пользователи": "Пользователи",
    },
    'en': {
        # Общие
        "btn_back": "🔙 Back",
        "btn_cancel": "❌ Cancel",
        "btn_back_to_menu": "🔙 Back to menu",
        "btn_confirm": "✅ Confirm",
        "status_enabled": "✅",
        "status_disabled": "❌",
        "group_admins": "Admins",
        "group_users": "Users",
        "group_unknown": "Unknown",
        "error_internal": "⚠️ Internal error.",
        "error_unexpected": "⚠️ An error occurred.",
        "error_with_details": "⚠️ An error occurred: {error}",
        "error_parsing_json": "❌ Error processing results: Invalid response format.\n<pre>{output}</pre>",
        "error_unexpected_json_parsing": "❌ Unexpected error processing results: {error}",

        # bot.py (Главное меню и Язык)
        "main_menu_welcome": "👋 Hi! Choose a command from the keyboard below. To show this menu again, use /menu.",
        "language_select": "Please select your language:",
        "language_selected": "✅ Language successfully changed to English.",
        "btn_language": "🇬🇧 Language",
        "main_menu_placeholder": "Select an option from the menu...",

        # core/auth.py
        "access_denied_message": "⛔ You are not an authorized user of this bot. Your ID: <code>{user_id}</code>.\nAccess to commands is denied. Please contact the administrator.",
        "access_denied_button": "📤 Send your ID to the administrator",
        "access_denied_generic": "⛔ Access denied.",
        "access_denied_not_root": "⛔ This feature is only available in 'root' mode.",
        "access_denied_no_rights": "⛔ You do not have permission to execute this command.",
        "default_admin_name": "Main Admin",
        "default_new_user_name": "New_{uid}",
        "default_id_user_name": "ID: {uid}",

        # core/keyboards.py (Кнопки меню)
        "btn_selftest": "🛠 Server Info",
        "btn_traffic": "📡 Network Traffic",
        "btn_uptime": "⏱ Uptime",
        "btn_speedtest": "🚀 Speedtest",
        "btn_top": "🔥 Top Processes",
        "btn_xray": "🩻 Update X-ray",
        "btn_sshlog": "📜 SSH Log",
        "btn_fail2ban": "🔒 Fail2Ban Log",
        "btn_logs": "📜 Recent Events",
        "btn_users": "👤 Users",
        "btn_vless": "🔗 VLESS Link",
        "btn_update": "🔄 Update VPS",
        "btn_optimize": "⚡️ Optimize",
        "btn_restart": "♻️ Restart Bot",
        "btn_reboot": "🔄 Reboot Server",
        "btn_notifications": "🔔 Notifications",

        # core/keyboards.py (Инлайн-кнопки)
        "btn_add_user": "➕ Add User",
        "btn_delete_user": "➖ Delete User",
        "btn_change_group": "🔄 Change Group",
        "btn_my_id": "🆔 My ID",
        "delete_user_button_text": "{user_name} ({group})",
        "delete_self_button_text": "❌ Delete myself ({user_name}, {group})",
        "btn_group_admins": "👑 Admins",
        "btn_group_users": "👤 Users",
        "btn_reboot_confirm": "✅ Yes, reboot",
        "btn_reboot_cancel": "❌ No, cancel",
        "alerts_menu_res": "{status} Resources (CPU/RAM/Disk)",
        "alerts_menu_logins": "{status} SSH Logins",
        "alerts_menu_bans": "{status} Bans (Fail2Ban)",
        "alerts_menu_downtime": "⏳ Server Downtime (WIP)",

        # core/utils.py
        "utils_vless_error": "⚠️ Error generating VLESS link: {error}",
        "utils_docker_ps_error": "Failed to execute 'docker ps'. Ensure Docker is installed, running, and the bot has permissions.\n<pre>{error}</pre>",
        "utils_bot_restarted": "✅ Bot restarted successfully.",
        "utils_server_rebooted": "✅ <b>Server rebooted successfully! The bot is back online.</b>",

        # core/messaging.py
        "alert_no_users_for_type": "No users with notifications enabled for type '{alert_type}'.",
        "alert_sending_to_users": "Sending alert type '{alert_type}' to {count} users...",
        "alert_sent_to_users": "Alert type '{alert_type}' sent to {count} users.",

        # watchdog.py
        "watchdog_alert_prefix": "🚨 <b>Alert System:</b>",
        "watchdog_log_read_error": "Log read error: {error}",
        "watchdog_log_error_found_details": "ERROR detected: {details}",
        "watchdog_log_error_found_generic": "Errors (ERROR/CRITICAL) detected in log",
        "watchdog_log_exception": "Exception reading log: {error}",
        "watchdog_status_active_ok": "Service <b>{bot_name}</b>: Active 🟢",
        "watchdog_status_active_error": "Service <b>{bot_name}</b>: Active with errors 🟠\n\n<b>Details:</b> {details}\n\nPlease check `bot.log`.",
        "watchdog_status_active_log_fail": "Service <b>{bot_name}</b>: Active 🟢 (Log check failed)",
        "watchdog_status_activating": "Service <b>{bot_name}</b>: Activating 🟡",
        "watchdog_status_down": "Service <b>{bot_name}</b>: Unavailable 🔴{reason}",
        "watchdog_status_down_reason": "Reason",
        "watchdog_status_down_failed": "Status: failed",
        "watchdog_restart_fail": "⚠️ Alert system FAILED to send restart command for <b>{service_name}</b>. Manual check required.\nError: {error}",
        "watchdog_systemctl_not_found": "⚠️ <code>systemctl</code> not found. Cannot check service status.",
        "watchdog_check_error": "⚠️ Error checking service status: {error}",
        "watchdog_started": "🚨 Internal 'Alert System' service started.\nTracking: <b>{bot_name}</b>",

        # modules/fail2ban.py
        "f2b_log_not_found": "⚠️ Fail2Ban log file not found: <code>{path}</code>",
        "f2b_log_read_error": "Could not read log file.",
        "f2b_banned": "Banned",
        "f2b_already_banned": "Already banned",
        "f2b_header": "🔒 <b>Last 10 IP bans (Fail2Ban):</b>\n\n{log_output}",
        "f2b_no_bans": "🔒 No recent IP bans found in Fail2Ban logs (checked last 50 lines).",
        "f2b_read_error_generic": "⚠️ Error reading Fail2Ban log: {error}",
        "f2b_ban_entry": "🔒 <b>{ban_type}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Time: <b>{time}</b>{tz}\n🗓️ Date: <b>{date}</b>",

        # modules/logs.py
        "logs_header": "📜 <b>Recent system logs:</b>\n<pre>{log_output}</pre>",
        "logs_read_error": "⚠️ Error reading logs: {error}",

        # modules/notifications.py
        "notifications_menu_title": "🔔 <b>Notification Settings</b>\n\nChoose which alerts you want to receive.",
        "notifications_toggle_alert": "Notifications '{alert_name}' {status}",
        "notifications_status_on": "✅ ENABLED",
        "notifications_status_off": "❌ DISABLED",
        "notifications_alert_name_res": "Resources",
        "notifications_alert_name_logins": "SSH Logins/Logouts",
        "notifications_alert_name_bans": "Bans",
        "notifications_downtime_stub": "⏳ Server downtime notifications are under development.\nFor now, we recommend using an external monitoring service (e.g., UptimeRobot).",
        "alert_ssh_login_detected": "🔔 <b>SSH Login Detected</b>\n\n👤 User: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Time: <b>{time}</b>{tz}",
        "alert_f2b_ban_detected": "🛡️ <b>Fail2Ban Banned IP</b>\n\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Time: <b>{time}</b>{tz}",
        "alert_cpu_high": "⚠️ <b>CPU Threshold Exceeded!</b>\nCurrent usage: <b>{usage:.1f}%</b> (Threshold: {threshold}%)",
        "alert_cpu_high_repeat": "‼️ <b>CPU Still HIGH!</b>\nCurrent usage: <b>{usage:.1f}%</b> (Threshold: {threshold}%)",
        "alert_cpu_normal": "✅ <b>CPU load normalized.</b>\nCurrent usage: <b>{usage:.1f}%</b>",
        "alert_ram_high": "⚠️ <b>RAM Threshold Exceeded!</b>\nCurrent usage: <b>{usage:.1f}%</b> (Threshold: {threshold}%)",
        "alert_ram_high_repeat": "‼️ <b>RAM Still HIGH!</b>\nCurrent usage: <b>{usage:.1f}%</b> (Threshold: {threshold}%)",
        "alert_ram_normal": "✅ <b>RAM usage normalized.</b>\nCurrent usage: <b>{usage:.1f}%</b>",
        "alert_disk_high": "⚠️ <b>Disk Threshold Exceeded!</b>\nCurrent usage: <b>{usage:.1f}%</b> (Threshold: {threshold}%)",
        "alert_disk_high_repeat": "‼️ <b>Disk Still HIGH!</b>\nCurrent usage: <b>{usage:.1f}%</b> (Threshold: {threshold}%)",
        "alert_disk_normal": "✅ <b>Disk usage normalized.</b>\nCurrent usage: <b>{usage:.1f}%</b>",

        # modules/optimize.py
        "optimize_start": "⏳ <b>Starting system optimization...</b>\n\nThis is a very long process (5-15 minutes).\nPlease do not restart the bot or run other commands.",
        "optimize_success": "✅ <b>Optimization completed successfully!</b>\n\n<b>Last 1000 characters of output (including sysctl):</b>\n<pre>{output}</pre>",
        "optimize_fail": "❌ <b>Error during optimization!</b>\n\n<b>Return Code:</b> {code}\n<b>STDOUT (last 1000):</b>\n<pre>{stdout}</pre>\n<b>STDERR (last 2000):</b>\n<pre>{stderr}</pre>",

        # modules/reboot.py
        "reboot_confirm_prompt": "⚠️ Are you sure you want to <b>reboot the server</b>? All active connections will be lost.",
        "reboot_confirmed": "✅ Confirmed. <b>Issuing VPS reboot</b>...",
        "reboot_error": "⚠️ Error sending reboot command: {error}",

        # modules/restart.py
        "restart_start": "♻️ Bot is restarting…",
        "restart_error": "⚠️ Error trying to restart service: {error}",

        # modules/selftest.py
        "selftest_gathering_info": "🔍 Gathering server info...",
        "selftest_error": "⚠️ Error gathering system stats: {error}",
        "selftest_inet_ok": "✅ Internet available",
        "selftest_inet_fail": "❌ No internet",
        "selftest_ip_fail": "Could not determine",
        "selftest_ssh_source": "(from {source})",
        "selftest_ssh_source_journal": "(from journalctl)",
        "selftest_ssh_header": "\n\n📄 <b>Last SSH login{source}:</b>\n",
        "selftest_ssh_entry": "👤 <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Time: <b>{time}</b>{tz}\n🗓️ Date: <b>{date}</b>",
        "selftest_ssh_parse_fail": "Could not parse log line.",
        "selftest_ssh_not_found": "No entries found.",
        "selftest_ssh_read_error": "⏳ Error reading logs: {error}",
        "selftest_ssh_root_only": "\n\n📄 <b>Last SSH login:</b>\n<i>Info available in root mode only</i>",
        "selftest_results_header": "🛠 <b>Server Status:</b>\n\n",
        "selftest_results_body": "✅ Bot is running\n📊 CPU: <b>{cpu:.1f}%</b>\n💾 RAM: <b>{mem:.1f}%</b>\n💽 Disk: <b>{disk:.1f}%</b>\n⏱ Uptime: <b>{uptime}</b>\n{inet_status}\n⌛ Ping (8.8.8.8): <b>{ping} ms</b>\n🌐 External IP: <code>{ip}</code>\n📡 Traffic ⬇ <b>{rx}</b> / ⬆ <b>{tx}</b>",

        # modules/speedtest.py
        "speedtest_start": "🚀 Starting speedtest... This may take up to a minute.",
        "speedtest_results": "🚀 <b>Speedtest Results:</b>\n\n⬇️ <b>Download:</b> {dl:.2f} Mbps\n⬆️ <b>Upload:</b> {ul:.2f} Mbps\n⏱ <b>Ping:</b> {ping} ms\n\n🏢 <b>Server:</b> {server} ({location})\n🔗 <b>Details:</b> {url}",
        "speedtest_fail": "❌ Error running speedtest:\n<pre>{error}</pre>",

        # modules/sshlog.py
        "sshlog_searching": "🔍 Searching for last 10 SSH events (login/fail)...",
        "sshlog_header": "🔐 <b>Last {count} SSH events{source}:</b>\n\n{log_output}",
        "sshlog_not_found": "🔐 No SSH events (login/fail) found{source}.",
        "sshlog_read_error": "⚠️ Error reading SSH log: {error}",
        "sshlog_entry_success": "✅ <b>Successful login</b>\n👤 User: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",
        "sshlog_entry_invalid_user": "❌ <b>Invalid user</b>\n👤 Attempt: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",
        "sshlog_entry_wrong_pass": "❌ <b>Failed password</b>\n👤 User: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",
        "sshlog_entry_fail_pam": "❌ <b>Failure (PAM)</b>\n👤 User: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {time}{tz} ({date})",

        # modules/top.py
        "top_header": "🔥 <b>Top 10 processes by CPU load:</b>\n<pre>{output}</pre>",
        "top_fail": "❌ Error getting process list:\n<pre>{error}</pre>",

        # modules/traffic.py
        "traffic_stop": "✅ Traffic monitoring stopped.",
        "traffic_menu_return": "🏠 Main menu:",
        "traffic_start": "📡 <b>Traffic monitoring enabled</b>...\n\n<i>Updates every 5 seconds. Press '📡 Network Traffic' again to stop.</i>",
        "traffic_start_fail": "⚠️ Failed to start traffic monitoring: {error}",
        "traffic_update_total": "📡 Total Traffic:",
        "traffic_update_speed": "⚡️ Connection Speed:",
        "traffic_rx": "⬇️ RX: {value}",
        "traffic_tx": "⬆️ TX: {value}",
        "traffic_speed_rx": "⬇️ RX: {speed:.2f} Mbps",
        "traffic_speed_tx": "⬆️ TX: {speed:.2f} Mbps",

        # modules/update.py
        "update_start": "🔄 Updating VPS... This may take a few minutes.",
        "update_success": "✅ Update complete:\n<pre>{output}</pre>",
        "update_fail": "❌ Error during update (Code: {code}):\n<pre>{error}</pre>",

        # modules/uptime.py
        "uptime_text": "⏱ Uptime: <b>{uptime}</b>",
        "uptime_fail": "⚠️ Error getting uptime: {error}",

        # modules/vless.py
        "vless_prompt_file": "📤 <b>Send your Xray configuration file (JSON)</b>\n\n<i>Important: The file must contain a working outbound configuration with Reality.</i>",
        "vless_error_not_json": "⛔ <b>Error:</b> File must be in <code>.json</code> format.\n\nPlease try sending the file again.",
        "vless_prompt_name": "✅ JSON file received.\n\nNow, <b>enter a name</b> for this VLESS link (e.g., 'My_Server_1'):",
        "vless_error_file_processing": "⚠️ An error occurred while processing the file: {error}",
        "vless_error_no_json_session": "⚠️ Error: JSON data not found in session. Please try again from the beginning.",
        "vless_success_caption": "✅ Your VLESS link named '<b>{name}</b>' is ready:\n\n<code>{url}</code>",
        "vless_menu_return": "🏠 Returning to main menu.",
        "vless_error_not_file": "⛔ Please send a <b>document</b> (file), not text.",
        "vless_error_not_text": "⛔ Please send a <b>text name</b>.",

        # modules/xray.py
        "xray_detecting": "🔍 Detecting installed Xray client...",
        "xray_detect_fail": "❌ Could not detect a supported Xray client (Marzban, Amnezia). Update aborted.",
        "xray_detected_start_update": "✅ Detected: <b>{client}</b> (container: <code>{container}</code>). Starting update...",
        "xray_update_error": "Update process for {client} failed:\n<pre>{error}</pre>",
        "xray_update_success": "✅ Xray for <b>{client}</b> successfully updated to version <b>{version}</b>",
        "xray_error_generic": "⚠️ <b>Xray Update Error:</b>\n\n{error}",
        "xray_version_unknown": "unknown",

        # modules/users.py (Добавления)
        "users_group_Admins": "Admins",
        "users_group_Пользователи": "Users",
    }
}

# --- УПРАВЛЕНИЕ НАСТРОЙКАМИ ЯЗЫКА ---

def load_user_settings():
    """Загружает настройки пользователей (включая язык) из JSON."""
    try:
        if os.path.exists(config.USER_SETTINGS_FILE):
            with open(config.USER_SETTINGS_FILE, "r", encoding='utf-8') as f:
                settings = json.load(f)
                shared_state.USER_SETTINGS = {int(k): v for k, v in settings.items()}
            logging.info("Настройки пользователей (языки) загружены.")
        else:
            shared_state.USER_SETTINGS = {}
            logging.info("Файл user_settings.json не найден, используются пустые настройки.")
    except Exception as e:
        logging.error(f"Ошибка загрузки user_settings.json: {e}")
        shared_state.USER_SETTINGS = {}

def save_user_settings():
    """Сохраняет настройки пользователей (включая язык) в JSON."""
    try:
        os.makedirs(os.path.dirname(config.USER_SETTINGS_FILE), exist_ok=True)
        settings_to_save = {str(k): v for k, v in shared_state.USER_SETTINGS.items()}
        with open(config.USER_SETTINGS_FILE, "w", encoding='utf-8') as f:
            json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
        logging.debug("Настройки пользователей (языки) сохранены.")
    except Exception as e:
        logging.error(f"Ошибка сохранения user_settings.json: {e}")

def get_user_lang(user_id: int) -> str:
    """Получает язык пользователя. 'ru' по умолчанию."""
    # --- ИСПРАВЛЕНИЕ: Проверяем тип user_id ---
    if not isinstance(user_id, int):
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logging.warning(f"get_user_lang вызван с нечисловым user_id: {user_id}. Возвращаю язык по умолчанию.")
            return config.DEFAULT_LANGUAGE
    # ----------------------------------------
    return shared_state.USER_SETTINGS.get(user_id, {}).get("lang", config.DEFAULT_LANGUAGE)

def set_user_lang(user_id: int, lang: str):
    """Устанавливает язык для пользователя и сохраняет."""
    # --- ИСПРАВЛЕНИЕ: Проверяем тип user_id ---
    if not isinstance(user_id, int):
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logging.error(f"set_user_lang вызван с нечисловым user_id: {user_id}. Сохранение отменено.")
            return
    # ----------------------------------------
    if user_id not in shared_state.USER_SETTINGS:
        shared_state.USER_SETTINGS[user_id] = {}
    shared_state.USER_SETTINGS[user_id]["lang"] = lang
    save_user_settings()
    logging.info(f"Язык для пользователя {user_id} изменен на '{lang}'")

# --- ГЛАВНАЯ ФУНКЦИЯ ПЕРЕВОДА ---

def _(key: str, user_id_or_lang: int | str | None, **kwargs) -> str: # Добавили None
    """
    Получает переведенную строку.
    Пример: _("main_menu_welcome", user_id)
    Пример с форматированием: _("my_id_text", user_id, user_id=user_id)
    """
    lang = user_id_or_lang
    if isinstance(user_id_or_lang, int):
        lang = get_user_lang(user_id_or_lang)
    # --- ИСПРАВЛЕНИЕ: Обработка None ---
    elif user_id_or_lang is None:
        lang = config.DEFAULT_LANGUAGE
    # ----------------------------------

    if lang not in STRINGS:
        lang = config.DEFAULT_LANGUAGE

    string_template = STRINGS.get(lang, {}).get(key,
        STRINGS.get(config.DEFAULT_LANGUAGE, {}).get(key, f"[{key}]")
    )

    try:
        return string_template.format(**kwargs)
    except (KeyError, TypeError, ValueError): # Добавили ValueError
        # Если .format() не удался (например, нет kwargs, или неверный тип)
        logging.warning(f"Ошибка форматирования для ключа '{key}' языка '{lang}' с параметрами {kwargs}. Шаблон: '{string_template}'")
        return string_template # Возвращаем неформатированный шаблон

# --- ФИЛЬТРЫ ДЛЯ AIOGRAM ---

def get_all_translations(key: str) -> list[str]:
    """
    Возвращает список всех переводов для одного ключа.
    Используется для aiogram F.text.in_([...])
    """
    translations = []
    for lang_strings in STRINGS.values():
        if key in lang_strings:
            translations.append(lang_strings[key])
    # Уникальные значения + проверка, что список не пустой
    unique_translations = list(set(translations))
    if not unique_translations:
        logging.error(f"Ключ перевода '{key}' не найден ни в одном языке!")
        return [f"[{key}]"] # Возвращаем ключ как запасной вариант
    return unique_translations

def I18nFilter(key: str):
    """
    Создает фильтр Aiogram, который сработает, если текст сообщения
    совпадает с ЛЮБЫМ переводом указанного ключа.
    """
    return F.text.in_(get_all_translations(key))

# --- Клавиатура смены языка ---
def get_language_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для выбора языка."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")
        ]
    ])
    return keyboard