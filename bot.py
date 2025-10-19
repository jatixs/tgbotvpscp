import asyncio
import os
import psutil
import re
import json
import urllib.parse
import logging
import requests
import sys
import signal # Needed for shutdown handler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta
import qrcode
from PIL import Image
import io
from aiogram.types import BufferedInputFile
import time



TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure")
ADMIN_USERNAME = os.environ.get("TG_ADMIN_USERNAME")

try:
    ADMIN_USER_ID = int(os.environ.get("TG_ADMIN_ID"))
except (ValueError, TypeError):
    print("Ошибка: Переменная окружения TG_ADMIN_ID должна быть установлена и быть числом.")
    sys.exit(1)

if not TOKEN:
    print("Ошибка: Переменная окружения TG_BOT_TOKEN не установлена.")
    sys.exit(1)

if not ADMIN_USERNAME:
    print("-------------------------------------------------------")
    print("ВНИМАНИЕ: Переменная TG_ADMIN_USERNAME не установлена.")
    print("Кнопка 'Отправить ID' будет открывать ПРОФИЛЬ админа,")
    print("а не личный чат. Для открытия прямого чата, установите")
    print("эту переменную (указав свой юзернейм без @).")
    print("-------------------------------------------------------")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")
RESTART_FLAG_FILE = os.path.join(CONFIG_DIR, "restart_flag.txt")
ALERTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "alerts_config.json")

LOG_FILE = os.path.join(LOG_DIR, "bot.log")
logging.basicConfig(level=logging.INFO, filename=LOG_FILE, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

TRAFFIC_INTERVAL = 5
RESOURCE_CHECK_INTERVAL = 60 # Интервал проверки ресурсов (1 минута)
CPU_THRESHOLD = 90.0
RAM_THRESHOLD = 90.0
DISK_THRESHOLD = 95.0

# --- [ИНТЕГРАЦИЯ] Добавлено для повторных алертов ---
RESOURCE_ALERT_COOLDOWN = 1800 # 30 минут (1800 сек) - как часто слать НАПОМИНАНИЯ
LAST_RESOURCE_ALERT_TIME = {"cpu": 0, "ram": 0, "disk": 0}
# --------------------------------------------------

ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {}
RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False}


bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class GenerateVlessStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_name = State()

class ManageUsersStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()
    # waiting_for_change_group = State() # Это состояние не использовалось, убираем

def load_alerts_config():
    global ALERTS_CONFIG
    try:
        if os.path.exists(ALERTS_CONFIG_FILE):
            with open(ALERTS_CONFIG_FILE, "r", encoding='utf-8') as f:
                ALERTS_CONFIG = json.load(f)
                ALERTS_CONFIG = {int(k): v for k, v in ALERTS_CONFIG.items()}
            logging.info("Настройки уведомлений загружены.")
        else:
            ALERTS_CONFIG = {}
            logging.info("Файл настроек уведомлений не найден, используется пустой конфиг.")
    except Exception as e:
        logging.error(f"Ошибка загрузки alerts_config.json: {e}")
        ALERTS_CONFIG = {}

def save_alerts_config():
    try:
        os.makedirs(os.path.dirname(ALERTS_CONFIG_FILE), exist_ok=True)
        with open(ALERTS_CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump({str(k): v for k, v in ALERTS_CONFIG.items()}, f, indent=4, ensure_ascii=False)
        logging.info("Настройки уведомлений сохранены.")
    except Exception as e:
        logging.error(f"Ошибка сохранения alerts_config.json: {e}")

load_alerts_config()

def get_country_flag(ip: str) -> str:
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=2)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get("countryCode")
            if country_code:
                flag = "".join(chr(ord(char) + 127397) for char in country_code.upper())
                return flag
    except requests.exceptions.RequestException as e:
        logging.warning(f"Ошибка при получении флага для IP {ip}: {e}")
        return "❓"
    return "🌍"

def escape_html(text):
    if text is None:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def load_users():
    global ALLOWED_USERS, USER_NAMES
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                ALLOWED_USERS = {int(user["id"]): user["group"] for user in data.get("allowed_users", [])}
                USER_NAMES = data.get("user_names", {})

        if ADMIN_USER_ID not in ALLOWED_USERS:
            ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
            USER_NAMES[str(ADMIN_USER_ID)] = "Главный Админ"
            save_users()

        logging.info(f"Пользователи загружены. Разрешено ID: {list(ALLOWED_USERS.keys())}")
    except Exception as e:
        logging.error(f"Критическая ошибка загрузки users.json: {e}")
        ALLOWED_USERS = {ADMIN_USER_ID: "Админы"}
        USER_NAMES = {str(ADMIN_USER_ID): "Главный Админ"}
        save_users()

def save_users():
    try:
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        data = {
            "allowed_users": [{"id": uid, "group": group} for uid, group in ALLOWED_USERS.items()],
            "user_names": user_names_to_save
        }
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logging.info(f"Успешно сохранено users.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}")

def is_allowed(user_id, command=None):
    if user_id not in ALLOWED_USERS:
        return False

    user_commands = ["start", "menu", "back_to_menu", "uptime", "traffic", "selftest", "get_id", "get_id_inline", "notifications_menu", "toggle_alert_resources", "toggle_alert_logins", "toggle_alert_bans", "alert_downtime_stub"]
    if command in user_commands:
        return True

    is_admin_group = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    if not is_admin_group:
        return False

    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray", "adduser", "add_user"
    ]
    if command in admin_only_commands:
        return True

    root_only_commands = [
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs", "restart", "update"
    ]
    if command in root_only_commands:
        return INSTALL_MODE == "root"

    # Добавил команды, которых не хватало для проверки
    if command and any(cmd in command for cmd in ["delete_user", "set_group", "change_group", "xray_install", "back_to_manage_users", "back_to_delete_users"]):
        return True

    return False


# --- [ИЗМЕНЕНИЕ] Исправленная функция обновления имен ---
async def refresh_user_names():
    needs_save = False
    # Проходим по копии ключей, чтобы избежать проблем при возможном удалении юзера во время итерации (хотя здесь это маловероятно)
    user_ids_to_check = list(ALLOWED_USERS.keys())

    logging.info(f"Начинаю обновление имен для {len(user_ids_to_check)} пользователей...")

    for uid in user_ids_to_check:
        uid_str = str(uid)
        current_name = USER_NAMES.get(uid_str)

        # Обновляем, если:
        # 1. ID вообще нет в словаре имен
        # 2. Имя - это временное "Новый_..."
        # 3. Имя - это запасное "ID: ..." (если get_chat ранее не сработал)
        # 4. Имя - это "Главный Админ" (на случай, если админ сменил имя)
        should_refresh = (
            not current_name
            or current_name.startswith("Новый_")
            or current_name.startswith("ID: ")
            or current_name == "Главный Админ"
        )

        if should_refresh:
            try:
                logging.debug(f"Пытаюсь получить имя для ID: {uid}")
                chat = await bot.get_chat(uid)
                # Выбираем лучшее доступное имя: Имя > Юзернейм > Запасной вариант
                new_name = chat.first_name or chat.username
                if not new_name:
                    # Если нет ни имени, ни юзернейма, используем ID
                    new_name = f"ID: {uid}"
                    logging.warning(f"Не удалось получить Имя/Юзернейм для {uid}, использую '{new_name}'")
                else:
                    # Экранируем HTML на всякий случай, если имя содержит спецсимволы
                    new_name = escape_html(new_name)

                # Обновляем, только если имя действительно изменилось
                if current_name != new_name:
                    logging.info(f"Обновлено имя для {uid}: '{current_name}' -> '{new_name}'")
                    USER_NAMES[uid_str] = new_name
                    needs_save = True
                else:
                    logging.debug(f"Имя для {uid} не изменилось ('{current_name}').")

            except TelegramBadRequest as e:
                # Частые ошибки: чат не найден (пользователь удалил аккаунт?) или бот заблокирован
                if "chat not found" in str(e) or "bot was blocked by the user" in str(e):
                     logging.warning(f"Не удалось обновить имя для {uid}: {e}. Использую 'ID: {uid}'.")
                     # Устанавливаем запасное имя, если его еще нет
                     if current_name != f"ID: {uid}":
                          USER_NAMES[uid_str] = f"ID: {uid}"
                          needs_save = True
                else:
                     # Другие ошибки API Telegram
                     logging.error(f"Непредвиденная ошибка Telegram API при получении имени для {uid}: {e}")
                     # Оставляем старое имя или устанавливаем запасное
                     if not current_name or current_name.startswith("Новый_"):
                          USER_NAMES[uid_str] = f"ID: {uid}"
                          needs_save = True
            except Exception as e:
                # Любые другие непредвиденные ошибки
                logging.error(f"Непредвиденная ошибка при обновлении имени для {uid}: {e}")
                if not current_name or current_name.startswith("Новый_"):
                     USER_NAMES[uid_str] = f"ID: {uid}"
                     needs_save = True

    if needs_save:
        logging.info("Обнаружены изменения в именах, сохраняю users.json...")
        save_users()
    else:
        logging.info("Обновление имен завершено, изменений не найдено.")
# --- [КОНЕЦ ИЗМЕНЕНИЯ] ---


async def get_user_name(user_id):
    try:
        cached_name = USER_NAMES.get(str(user_id))
        if cached_name and "Unknown" not in cached_name and "Главный Админ" not in cached_name:
            return cached_name

        chat = await bot.get_chat(user_id)
        name = chat.first_name or chat.username or f"Unknown_{user_id}"
        USER_NAMES[str(user_id)] = name
        save_users()
        return name
    except Exception as e:
        logging.error(f"Ошибка получения имени для ID {user_id}: {e}")
        return f"Unknown_{user_id}"

async def send_access_denied_message(user_id, chat_id, command):
    await delete_previous_message(user_id, command, chat_id)

    text_to_send = f"мой ID: {user_id}"
    admin_link = ""

    if ADMIN_USERNAME:
        admin_link = f"https://t.me/{ADMIN_USERNAME}?text={urllib.parse.quote(text_to_send)}"
    else:
        admin_link = f"tg://user?id={ADMIN_USER_ID}&text={urllib.parse.quote(text_to_send)}"
        logging.warning("Переменная TG_ADMIN_USERNAME не установлена. Используется ссылка по ID (открывает профиль).")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить свой ID администратору", url=admin_link)]
    ])
    sent_message = await bot.send_message(
        chat_id,
        f"⛔ Вы не являетесь пользователем бота. Ваш ID: <code>{user_id}</code>.\n"
        "К командам нет доступа, обратитесь к администратору.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

def get_main_reply_keyboard(user_id):
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"

    buttons = [
        [KeyboardButton(text="🛠 Сведения о сервере"), KeyboardButton(text="📡 Трафик сети")],
        [KeyboardButton(text="⏱ Аптайм"), KeyboardButton(text="🔔 Уведомления")],
    ]

    admin_buttons_flat = [btn.text for row in buttons for btn in row]

    if is_admin:
        if INSTALL_MODE == 'secure':
            secure_admin_buttons = [
                [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                [KeyboardButton(text="🚀 Скорость сети"), KeyboardButton(text="🔥 Топ процессов")],
                [KeyboardButton(text="🩻 Обновление X-ray")],
            ]
            for row in reversed(secure_admin_buttons):
                new_row = [btn for btn in row if btn.text not in admin_buttons_flat]
                if new_row:
                    buttons.insert(0, new_row)
                    admin_buttons_flat.extend([btn.text for btn in new_row])


        elif INSTALL_MODE == 'root':
             root_admin_buttons = [
                 [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                 [KeyboardButton(text="🔥 Топ процессов"), KeyboardButton(text="📜 SSH-лог")],
                 [KeyboardButton(text="🔒 Fail2Ban Log"), KeyboardButton(text="📜 Последние события")],
                 [KeyboardButton(text="🚀 Скорость сети")],
                 [KeyboardButton(text="🔄 Обновление VPS"), KeyboardButton(text="🩻 Обновление X-ray")],
                 [KeyboardButton(text="🔄 Перезагрузка сервера"), KeyboardButton(text="♻️ Перезапуск бота")]
             ]
             for row in reversed(root_admin_buttons):
                 new_row = [btn for btn in row if btn.text not in admin_buttons_flat]
                 if new_row:
                     buttons.insert(0, new_row)
                     admin_buttons_flat.extend([btn.text for btn in new_row])


    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, input_field_placeholder="Выберите опцию в меню...")
    return keyboard

def get_manage_users_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="add_user"),
            InlineKeyboardButton(text="➖ Удалить пользователя", callback_data="delete_user")
        ],
        [
            InlineKeyboardButton(text="🔄 Изменить группу", callback_data="change_group"),
            InlineKeyboardButton(text="🆔 Мой ID", callback_data="get_id_inline")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_delete_users_keyboard(current_user_id):
    buttons = []
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}"), reverse=False) # Fallback to ID if name missing

    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID:
            continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}") # Use fallback here too
        button_text = f"{user_name} ({group})"
        callback_data = f"delete_user_{uid}"
        if uid == current_user_id:
            button_text = f"❌ Удалить себя ({user_name}, {group})"
            callback_data = f"request_self_delete_{uid}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_change_group_keyboard():
    buttons = []
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), f"ID: {item[0]}"), reverse=False)
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID:
            continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        buttons.append([InlineKeyboardButton(text=f"{user_name} ({group})", callback_data=f"select_user_change_group_{uid}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_selection_keyboard(user_id_to_change=None):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👑 Админы", callback_data=f"set_group_{user_id_to_change or 'new'}_Админы"),
            InlineKeyboardButton(text="👤 Пользователи", callback_data=f"set_group_{user_id_to_change or 'new'}_Пользователи")
        ],
        [
            InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_manage_users")
        ]
    ])
    return keyboard

def get_self_delete_confirmation_keyboard(user_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_self_delete_{user_id}"),
            InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_delete_users")
        ]
    ])
    return keyboard

def get_reboot_confirmation_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, перезагрузить", callback_data="reboot"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_back_keyboard(callback_data="back_to_manage_users"):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)
        ]
    ])
    return keyboard

def get_alerts_menu_keyboard(user_id):
    user_config = ALERTS_CONFIG.get(user_id, {})
    res_enabled = user_config.get("resources", False)
    logins_enabled = user_config.get("logins", False)
    bans_enabled = user_config.get("bans", False)

    res_text = f"{'✅' if res_enabled else '❌'} Ресурсы (CPU/RAM/Disk)"
    logins_text = f"{'✅' if logins_enabled else '❌'} Входы/Выходы SSH"
    bans_text = f"{'✅' if bans_enabled else '❌'} Баны (Fail2Ban)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=res_text, callback_data="toggle_alert_resources")],
        [InlineKeyboardButton(text=logins_text, callback_data="toggle_alert_logins")],
        [InlineKeyboardButton(text=bans_text, callback_data="toggle_alert_bans")],
        [InlineKeyboardButton(text="⏳ Даунтайм сервера", callback_data="alert_downtime_stub")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])
    return keyboard


def convert_json_to_vless(json_data, custom_name):
    try:
        config = json.loads(json_data)
        outbound = config['outbounds'][0]
        vnext = outbound['settings']['vnext'][0]
        user = vnext['users'][0]
        reality = outbound['streamSettings']['realitySettings']
        vless_params = {
            'id': user['id'],
            'address': vnext['address'],
            'port': vnext['port'],
            'security': outbound['streamSettings']['security'],
            'host': reality['serverName'],
            'fp': reality['fingerprint'],
            'pbk': reality['publicKey'],
            'sid': reality['shortId'],
            'type': outbound['streamSettings']['network'],
            'flow': user['flow'],
            'encryption': user['encryption'],
            'headerType': 'none'
        }
        vless_url = (f"vless://{vless_params['id']}@{vless_params['address']}:{vless_params['port']}"
                     f"?security={vless_params['security']}"
                     f"&encryption={vless_params['encryption']}"
                     f"&pbk={urllib.parse.quote(vless_params['pbk'])}"
                     f"&host={urllib.parse.quote(vless_params['host'])}"
                     f"&headerType={vless_params['headerType']}"
                     f"&fp={vless_params['fp']}"
                     f"&type={vless_params['type']}"
                     f"&flow={vless_params['flow']}"
                     f"&sid={vless_params['sid']}"
                     f"#{urllib.parse.quote(custom_name)}")
        return vless_url
    except Exception as e:
        logging.error(f"Ошибка при генерации VLESS-ссылки: {e}")
        return f"⚠️ Ошибка при генерации VLESS-ссылки: {str(e)}"

def format_traffic(bytes_value):
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"]
    value = float(bytes_value)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"

def format_uptime(seconds):
    seconds = int(seconds)
    years = seconds // (365 * 24 * 3600)
    remaining = seconds % (365 * 24 * 3600)
    days = remaining // (24 * 3600)
    remaining %= (24 * 3600)
    hours = remaining // 3600
    remaining %= 3600
    mins = remaining // 60
    secs = remaining % 60
    parts = []
    if years > 0:
        parts.append(f"{years}г")
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0:
        parts.append(f"{hours}ч")
    if mins > 0:
        parts.append(f"{mins}м")
    if seconds < 60 or not parts:
       parts.append(f"{secs}с")
    return " ".join(parts) if parts else "0с"

def get_server_timezone_label():
    try:
        offset_str = time.strftime("%z")
        if not offset_str or len(offset_str) != 5:
            return ""

        sign = offset_str[0]
        hours_str = offset_str[1:3]
        mins_str = offset_str[3:5]

        hours_int = int(hours_str)

        if mins_str == "00":
            return f" (GMT{sign}{hours_int})"
        else:
            return f" (GMT{sign}{hours_int}:{mins_str})"
    except Exception:
        return ""

async def delete_previous_message(user_id: int, command, chat_id: int):
    cmds_to_delete = [command] if not isinstance(command, list) else command
    for cmd in cmds_to_delete:
        try:
            if user_id in LAST_MESSAGE_IDS and cmd in LAST_MESSAGE_IDS[user_id]:
                msg_id = LAST_MESSAGE_IDS[user_id].pop(cmd)
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest as e:
            if "message to delete not found" not in str(e) and "message can't be deleted" not in str(e):
                logging.error(f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")
        except Exception as e:
            logging.error(f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")

async def send_alert(message: str, alert_type: str):
    if not alert_type:
        logging.warning("send_alert вызван без указания alert_type")
        return

    sent_count = 0
    users_to_alert = []
    for user_id, config in ALERTS_CONFIG.items():
        if config.get(alert_type, False):
           users_to_alert.append(user_id)

    if not users_to_alert:
        logging.info(f"Нет пользователей с включенными уведомлениями типа '{alert_type}'.")
        return

    logging.info(f"Отправка алерта типа '{alert_type}' {len(users_to_alert)} пользователям...")
    for user_id in users_to_alert:
        try:
            await bot.send_message(user_id, message, parse_mode="HTML")
            sent_count += 1
            await asyncio.sleep(0.1)
        except TelegramBadRequest as e:
            if "chat not found" in str(e) or "bot was blocked by the user" in str(e):
                logging.warning(f"Не удалось отправить алерт пользователю {user_id}: чат не найден или бот заблокирован.")
            else:
                logging.error(f"Неизвестная ошибка TelegramBadRequest при отправке алерта {user_id}: {e}")
        except Exception as e:
            logging.error(f"Ошибка при отправке алерта пользователю {user_id}: {e}")

    logging.info(f"Алерт типа '{alert_type}' отправлен {sent_count} пользователям.")


# --- [ИНТЕГРАЦИЯ] Парсеры для мониторинга логов ---

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

# --- [ИНТЕГРАЦИЯ] Фоновый монитор логов (tail -f) (ИСПРАВЛЕННЫЙ v3) ---

async def reliable_tail_log_monitor(log_file_path: str, alert_type: str, parse_function: callable):
    process = None
    stdout_closed = asyncio.Event()
    stderr_closed = asyncio.Event()

    async def close_pipe(pipe, name, event):
        if pipe and not pipe.at_eof():
            try:
                pipe.feed_eof()
                logging.debug(f"Монитор {alert_type}: Закрытие пайпа {name}...")
            except Exception as e:
                logging.warning(f"Монитор {alert_type}: Ошибка при feed_eof() для пайпа {name}: {e}")
            finally:
                 event.set()
        else:
            event.set()

    try:
        while True:
            stdout_closed.clear()
            stderr_closed.clear()

            if not await asyncio.to_thread(os.path.exists, log_file_path):
                 logging.warning(f"Монитор: {log_file_path} не найден. Проверка через 60с.")
                 await asyncio.sleep(60)
                 continue

            logging.info(f"Запуск (или перезапуск) монитора {alert_type} для {log_file_path}")
            try:
                process = await asyncio.create_subprocess_shell(
                    f"tail -n 0 -f {log_file_path}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                logging.info(f"Монитор {alert_type} (PID: {process.pid}) следит за {log_file_path}")

                while True:
                    tasks = [
                        asyncio.create_task(process.stdout.readline()),
                        asyncio.create_task(process.stderr.readline())
                    ]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                    for task in pending: task.cancel()

                    stdout_line = None
                    stderr_line = None

                    for task in done:
                        try:
                            result = task.result()
                            if task == tasks[0]: stdout_line = result
                            else: stderr_line = result
                        except asyncio.CancelledError: pass
                        except Exception as e:
                             logging.error(f"Монитор {alert_type}: Ошибка чтения из пайпа: {e}")
                             if process.returncode is None: await asyncio.sleep(0.1)
                             if process.returncode is not None: break

                    if stdout_line:
                        line_str = stdout_line.decode('utf-8', errors='ignore').strip()
                        message = await parse_function(line_str)
                        if message: await send_alert(message, alert_type)
                    elif stdout_line is not None:
                         logging.info(f"Монитор {alert_type}: stdout достиг EOF.")
                         stdout_closed.set()

                    if stderr_line:
                        stderr_str = stderr_line.decode('utf-8', errors='ignore').strip()
                        logging.warning(f"Монитор {alert_type} (tail stderr): {stderr_str}")
                    elif stderr_line is not None:
                         logging.info(f"Монитор {alert_type}: stderr достиг EOF.")
                         stderr_closed.set()

                    if process.returncode is not None:
                        logging.warning(f"Процесс 'tail' для {alert_type} (PID: {process.pid if process else 'N/A'}) умер с кодом {process.returncode}. Перезапуск...")
                        stdout_closed.set()
                        stderr_closed.set()
                        process = None
                        break

                    if stdout_closed.is_set() and stderr_closed.is_set() and process and process.returncode is None:
                         logging.warning(f"Монитор {alert_type}: Оба пайпа закрыты, но процесс tail (PID: {process.pid}) еще жив. Попытка перезапуска.")
                         break

            except PermissionError:
                 logging.warning(f"Монитор: Нет прав на чтение {log_file_path}. Проверка через 60с.")
                 await asyncio.sleep(60)
            except Exception as e:
                pid_info = f"(PID: {process.pid})" if process else ""
                logging.error(f"Критическая ошибка во внутреннем цикле reliable_tail_log_monitor ({log_file_path}) {pid_info}: {e}")
                if process and process.returncode is None:
                    try: process.terminate()
                    except ProcessLookupError: pass
                process = None
                await asyncio.sleep(10)

    except asyncio.CancelledError:
         logging.info(f"Монитор {alert_type} отменен (штатное завершение).")

    finally:
        pid = process.pid if process else None
        logging.info(f"Завершение работы монитора {alert_type}, попытка остановки 'tail' (PID: {pid})...")

        pipe_close_tasks = []
        if process:
             if hasattr(process, 'stdout') and process.stdout:
                 pipe_close_tasks.append(close_pipe(process.stdout, 'stdout', stdout_closed))
             else: stdout_closed.set()
             if hasattr(process, 'stderr') and process.stderr:
                 pipe_close_tasks.append(close_pipe(process.stderr, 'stderr', stderr_closed))
             else: stderr_closed.set()

        if pipe_close_tasks:
             try:
                 await asyncio.wait_for(asyncio.gather(*pipe_close_tasks), timeout=1.0)
                 logging.debug(f"Монитор {alert_type}: Попытка закрытия пайпов завершена.")
             except asyncio.TimeoutError:
                 logging.warning(f"Монитор {alert_type}: Таймаут при ожидании закрытия пайпов.")
             except Exception as pipe_e:
                  logging.error(f"Монитор {alert_type}: Ошибка при закрытии пайпов: {pipe_e}")

        if process and process.returncode is None:
            logging.info(f"Монитор {alert_type}: Остановка процесса tail (PID: {pid}).")
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                    logging.info(f"Монитор {alert_type}: 'tail' (PID: {pid}) успешно остановлен (terminate).")
                except asyncio.TimeoutError:
                    logging.warning(f"Монитор {alert_type}: 'tail' (PID: {pid}) не завершился за 2 сек после terminate(). Попытка kill().")
                    try:
                        process.kill()
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                        logging.info(f"Монитор {alert_type}: 'tail' (PID: {pid}) успешно убит (kill).")
                    except asyncio.TimeoutError: logging.error(f"Монитор {alert_type}: 'tail' (PID: {pid}) не завершился даже после kill().")
                    except ProcessLookupError: pass
                    except Exception as kill_e: logging.error(f"Монитор {alert_type}: Ошибка при kill() 'tail' (PID: {pid}): {kill_e}")
            except ProcessLookupError: pass
            except Exception as e: logging.error(f"Монитор {alert_type}: Неожиданная ошибка при остановке 'tail' (PID: {pid}): {e}")
        elif process:
             logging.info(f"Монитор {alert_type}: 'tail' (PID: {pid}) уже был завершен (код: {process.returncode}) до блока finally.")
        else:
            logging.info(f"Монитор {alert_type}: Процесс tail не был запущен или уже был очищен.")

# --- [ КОНЕЦ БЛОКОВ ИНТЕГРАЦИИ ] ---


@dp.message(Command("start", "menu"))
@dp.message(F.text == "🔙 Назад в меню")
async def start_or_menu_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "start" if message.text == "/start" else "menu"
    await state.clear()
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, ["start", "menu", "manage_users", "reboot_confirm", "generate_vless", "adduser", "notifications_menu", "traffic", "get_id"], chat_id)
    if str(user_id) not in USER_NAMES:
       await refresh_user_names()
    sent_message = await message.answer(
        "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu.",
        reply_markup=get_main_reply_keyboard(user_id)
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    await state.clear()

    if not is_allowed(user_id, "menu"):
        await send_access_denied_message(user_id, chat_id, "menu")
        await callback.answer()
        return

    await delete_previous_message(
        user_id,
        ["start", "menu", "manage_users", "reboot_confirm", "generate_vless",
         "adduser", "notifications_menu", "traffic", "get_id"],
        chat_id
    )

    sent_message = await bot.send_message(
        chat_id,
        "🏠 Главное меню:",
        reply_markup=get_main_reply_keyboard(user_id)
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})["menu"] = sent_message.message_id
    await callback.answer()

@dp.message(F.text == "👤 Пользователи")
async def manage_users_handler(message: types.Message):
    user_id = message.from_user.id
    command = "manage_users"
    if not is_allowed(user_id, command):
        await bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    await delete_previous_message(user_id, command, message.chat.id)

    user_list = "\n".join([
        f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
        for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
    ])
    if not user_list:
        user_list = "Других пользователей нет."

    sent_message = await message.answer(
        f"👤 <b>Управление пользователями</b>:\n\n{user_list}\n\nВыберите действие:",
        reply_markup=get_manage_users_keyboard(),
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(F.text == "🔄 Перезагрузка сервера")
async def reboot_confirm_handler(message: types.Message):
    user_id = message.from_user.id
    command = "reboot_confirm"
    if not is_allowed(user_id, command):
        await bot.send_message(message.chat.id, "⛔ Эта функция доступна только в режиме 'root'.")
        return
    await delete_previous_message(user_id, command, message.chat.id)
    sent_message = await message.answer("⚠️ Вы уверены, что хотите <b>перезагрузить сервер</b>? Все активные соединения будут разорваны.", reply_markup=get_reboot_confirmation_keyboard(), parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(F.text == "🔗 VLESS-ссылка")
async def generate_vless_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    await delete_previous_message(user_id, command, message.chat.id)
    
    # Клавиатура "Отменить"
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")]
    ])
    
    sent_message = await message.answer(
        "📤 <b>Отправьте файл конфигурации Xray (JSON)</b>\n\n<i>Важно: файл должен содержать рабочую конфигурацию outbound с Reality.</i>", 
        reply_markup=cancel_keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    await state.set_state(GenerateVlessStates.waiting_for_file)

# --- Original Handlers ---
async def fall2ban_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "fall2ban"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    try:
        F2B_LOG_FILE = "/var/log/fail2ban.log"

        if not await asyncio.to_thread(os.path.exists, F2B_LOG_FILE):
             sent_message = await message.answer(f"⚠️ Файл лога Fail2Ban не найден: <code>{F2B_LOG_FILE}</code>", parse_mode="HTML")
             LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
             return

        def read_f2b_log():
             try:
                  with open(F2B_LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
                       return f.readlines()[-50:]
             except Exception as read_e:
                  logging.error(f"Error reading Fail2Ban log file: {read_e}")
                  return None

        lines = await asyncio.to_thread(read_f2b_log)

        if lines is None:
             raise Exception("Не удалось прочитать файл лога.")

        log_entries = []
        tz_label = get_server_timezone_label()
        regex_ban = r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* Ban\s+(\S+)"
        regex_already = r"(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3}).*fail2ban\.actions.* (\S+)\s+already banned"

        for line in reversed(lines):
            line = line.strip()
            if "fail2ban.actions" not in line:
                continue

            match = None
            ban_type = None
            ip = None
            timestamp_str = None

            match_ban_found = re.search(regex_ban, line)
            if match_ban_found:
                match = match_ban_found
                ban_type = "Бан"
                timestamp_str, ip = match.groups()
            else:
                match_already_found = re.search(regex_already, line)
                if match_already_found:
                    match = match_already_found
                    ban_type = "Уже забанен"
                    timestamp_str, ip = match.groups()

            if match and ip and timestamp_str:
                try:
                    dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    formatted_time = dt.strftime('%H:%M:%S')
                    formatted_date = dt.strftime('%d.%m.%Y')
                    log_entries.append(f"🔒 <b>{ban_type}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ Время: <b>{formatted_time}</b>{tz_label}\n🗓️ Дата: <b>{formatted_date}</b>")
                except ValueError:
                    logging.warning(f"Could not parse Fail2Ban timestamp: {timestamp_str}")
                    continue
                except Exception as parse_e:
                    logging.error(f"Error processing Fail2Ban line: {parse_e} | Line: {line}")
                    continue

            if len(log_entries) >= 10:
                break

        if log_entries:
            log_output = "\n\n".join(log_entries)
            sent_message = await message.answer(f"🔒 <b>Последние 10 блокировок IP (Fail2Ban):</b>\n\n{log_output}", parse_mode="HTML")
        else:
            sent_message = await message.answer("🔒 Нет недавних блокировок IP в логах Fail2Ban (проверено 50 последних строк).")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    except Exception as e:
        logging.error(f"Ошибка при чтении журнала Fail2Ban: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журнала Fail2Ban: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def sshlog_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "sshlog"
    if not is_allowed(user_id, command):
         await send_access_denied_message(user_id, chat_id, command)
         return

    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer("🔍 Ищу последние 10 событий SSH (вход/провал)...")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    try:
        log_file = None
        if await asyncio.to_thread(os.path.exists, "/var/log/secure"):
            log_file = "/var/log/secure"
        elif await asyncio.to_thread(os.path.exists, "/var/log/auth.log"):
            log_file = "/var/log/auth.log"

        lines = []
        source = ""
        log_entries = []
        found_count = 0

        if log_file:
            source = f" (из {os.path.basename(log_file)})"
            cmd = f"tail -n 200 {log_file}"
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0: raise Exception(stderr.decode())
            lines = stdout.decode().strip().split('\n')
        else:
            source = " (из journalctl, за месяц)"
            cmd = "journalctl -u ssh -n 100 --no-pager --since '1 month ago' -o short-precise"
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                raise Exception("journalctl завис (тайм-аут 5с)")
            if process.returncode != 0: raise Exception(stderr.decode())
            lines = stdout.decode().strip().split('\n')

        tz_label = get_server_timezone_label()

        for line in reversed(lines):
            if found_count >= 10:
                break

            line = line.strip()
            if "sshd" not in line:
                continue

            dt_object = None
            date_match_iso = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            date_match_syslog = re.search(r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

            try:
                if date_match_iso:
                    dt_object = datetime.strptime(date_match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                elif date_match_syslog:
                    log_timestamp = datetime.strptime(date_match_syslog.group(1), "%b %d %H:%M:%S")
                    current_year = datetime.now().year
                    dt_object = log_timestamp.replace(year=current_year)
                    if dt_object > datetime.now():
                        dt_object = dt_object.replace(year=current_year - 1)
                else:
                    continue
            except Exception as e:
                logging.warning(f"Sshlog: не удалось распарсить дату: {e}. Строка: {line}")
                continue

            formatted_time = dt_object.strftime('%H:%M:%S')
            formatted_date = dt_object.strftime('%d.%m.%Y')

            entry = None

            match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)
            if match:
                user = match.group(1)
                ip = match.group(2)
                flag = await asyncio.to_thread(get_country_flag, ip)
                entry = f"✅ <b>Успешный вход</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if not entry:
                match = re.search(r"Failed\s+(?:\S+)\s+for\s+invalid\s+user\s+(\S+)\s+from\s+(\S+)", line)
                if match:
                    user = match.group(1)
                    ip = match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry = f"❌ <b>Неверный юзер</b>\n👤 Попытка: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if not entry:
                match = re.search(r"Failed password for (\S+) from (\S+)", line)
                if match:
                    user = match.group(1)
                    ip = match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry = f"❌ <b>Неверный пароль</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if not entry:
                match = re.search(r"authentication failure;.*rhost=(\S+)\s+user=(\S+)", line)
                if match:
                    ip = match.group(1)
                    user = match.group(2)
                    flag = await asyncio.to_thread(get_country_flag, ip)
                    entry = f"❌ <b>Провал (PAM)</b>\n👤 Пользователь: <b>{user}</b>\n🌍 IP: <b>{flag} {ip}</b>\n⏰ {formatted_time}{tz_label} ({formatted_date})"

            if entry:
                log_entries.append(entry)
                found_count += 1

        if log_entries:
            log_output = "\n\n".join(log_entries)
            await bot.edit_message_text(f"🔐 <b>Последние {found_count} событий SSH{source}:</b>\n\n{log_output}", chat_id=chat_id, message_id=sent_message.message_id, parse_mode="HTML")
        else:
            await bot.edit_message_text(f"🔐 Не найдено событий SSH (вход/провал){source}.", chat_id=chat_id, message_id=sent_message.message_id)

    except Exception as e:
        logging.error(f"Ошибка при чтении журнала SSH: {e}")
        await bot.edit_message_text(f"⚠️ Ошибка при чтении журнала SSH: {str(e)}", chat_id=chat_id, message_id=sent_message.message_id)


async def logs_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "logs"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    try:
        cmd = "journalctl -n 20 --no-pager -o short-precise"
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(stderr.decode())
        log_output = escape_html(stdout.decode())
        sent_message = await message.answer(f"📜 <b>Последние системные журналы:</b>\n<pre>{log_output}</pre>", parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при чтении журналов: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журналов: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "restart"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    sent_msg = await message.answer("♻️ Бот уходит на перезапуск…")
    try:
        with open(RESTART_FLAG_FILE, "w") as f:
            f.write(f"{chat_id}:{sent_msg.message_id}")
        restart_cmd = "sudo systemctl restart tg-bot.service"
        process = await asyncio.create_subprocess_shell(restart_cmd)
        await process.wait()
        logging.info("Restart command sent for tg-bot.service")
    except Exception as e:
        logging.error(f"Ошибка в restart_handler при отправке команды перезапуска: {e}")
        if os.path.exists(RESTART_FLAG_FILE):
            os.remove(RESTART_FLAG_FILE)
        try:
            await bot.edit_message_text(text=f"⚠️ Ошибка при попытке перезапуска сервиса: {str(e)}", chat_id=chat_id, message_id=sent_msg.message_id)
        except Exception as edit_e:
            logging.error(f"Failed to edit restart error message: {edit_e}")


async def selftest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "selftest"

    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
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
        await bot.edit_message_text(f"⚠️ Ошибка при сборе системной статистики: {e}", chat_id=chat_id, message_id=sent_message.message_id)
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
                if process.returncode != 0: raise Exception(stderr.decode())

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

                if process.returncode != 0: raise Exception(stderr.decode())
                line = stdout.decode().strip()

            if line:
                dt_object = None
                date_match_iso = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                date_match_syslog = re.search(r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", line)

                try:
                    if date_match_iso:
                        dt_object = datetime.strptime(date_match_iso.group(1), "%Y-%m-%dT%H:%M:%S")
                    elif date_match_syslog:
                        log_timestamp = datetime.strptime(date_match_syslog.group(1), "%b %d %H:%M:%S")
                        current_year = datetime.now().year
                        dt_object = log_timestamp.replace(year=current_year)
                        if dt_object > datetime.now():
                            dt_object = dt_object.replace(year=current_year - 1)
                except Exception as e:
                    logging.warning(f"Selftest: не удалось распарсить дату: {e}. Строка: {line}")

                login_match = re.search(r"Accepted\s+(?:\S+)\s+for\s+(\S+)\s+from\s+(\S+)", line)

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
                    logging.warning(f"Selftest: Не удалось разобрать строку SSH (login_match={login_match}, dt_object={dt_object}): {line}")
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
        f"📡 Трафик ⬇ <b>{format_traffic(rx)}</b> / ⬆ <b>{format_traffic(tx)}</b>"
    )

    response_text += last_login_info

    await bot.edit_message_text(response_text, chat_id=chat_id, message_id=sent_message.message_id, parse_mode="HTML")


async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "speedtest"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer("🚀 Запуск speedtest... Это может занять до минуты.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    cmd = "speedtest --accept-license --accept-gdpr --format=json"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()

    await delete_previous_message(user_id, command, chat_id)

    if process.returncode == 0:
        output = stdout.decode('utf-8', errors='ignore')
        try:
            data = json.loads(output)
            download_speed = data.get("download", {}).get("bandwidth", 0) / 125000
            upload_speed = data.get("upload", {}).get("bandwidth", 0) / 125000
            ping_latency = data.get("ping", {}).get("latency", "N/A")
            server_name = data.get("server", {}).get("name", "N/A")
            server_location = data.get("server", {}).get("location", "N/A")
            result_url = data.get("result", {}).get("url", "N/A")

            response_text = (f"🚀 <b>Speedtest Результаты:</b>\n\n"
                             f"⬇️ <b>Скачивание:</b> {download_speed:.2f} Мбит/с\n"
                             f"⬆️ <b>Загрузка:</b> {upload_speed:.2f} Мбит/с\n"
                             f"⏱ <b>Пинг:</b> {ping_latency} мс\n\n"
                             f"🏢 <b>Сервер:</b> {server_name} ({server_location})\n"
                             f"🔗 <b>Подробнее:</b> {result_url}")
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка парсинга JSON от speedtest: {e}\nOutput: {output[:500]}")
            response_text = f"❌ Ошибка при обработке результатов speedtest: Неверный формат ответа.\n<pre>{escape_html(output[:1000])}</pre>"
        except Exception as e:
             logging.error(f"Неожиданная ошибка обработки speedtest: {e}")
             response_text = f"❌ Неожиданная ошибка при обработке результатов speedtest: {escape_html(str(e))}"
    else:
        error_output = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
        logging.error(f"Ошибка выполнения speedtest. Код: {process.returncode}. Вывод: {error_output}")
        response_text = f"❌ Ошибка при запуске speedtest:\n<pre>{escape_html(error_output)}</pre>"

    sent_message_final = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id


async def top_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "top"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    cmd = "ps aux --sort=-%cpu | head -n 15"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        output = escape_html(stdout.decode())
        response_text = f"🔥 <b>Топ 14 процессов по загрузке CPU:</b>\n<pre>{output}</pre>"
    else:
        error_output = escape_html(stderr.decode())
        response_text = f"❌ Ошибка при получении списка процессов:\n<pre>{error_output}</pre>"
    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def traffic_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "traffic"
    if not is_allowed(user_id, command):
         await send_access_denied_message(user_id, chat_id, command)
         return

    all_commands_to_delete = [
        "start", "menu", "manage_users", "reboot_confirm", "generate_vless", 
        "adduser", "notifications_menu", "traffic", "get_id", "fall2ban", 
        "sshlog", "logs", "restart", "selftest", "speedtest", "top", 
        "update", "uptime", "updatexray"
    ]

    if user_id in TRAFFIC_MESSAGE_IDS:
        logging.info(f"Остановка мониторинга трафика для {user_id} (IF блок)")
        try:
            message_id = TRAFFIC_MESSAGE_IDS.pop(user_id)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramBadRequest, KeyError) as e:
            logging.warning(f"Не удалось удалить сообщение трафика при остановке: {e}")
        
        TRAFFIC_PREV.pop(user_id, None)
        logging.debug("Остановка: Очистка предыдущих сообщений...")
        await delete_previous_message(user_id, all_commands_to_delete, chat_id)
        sent_message = await message.answer("✅ Мониторинг трафика остановлен.", reply_markup=get_main_reply_keyboard(user_id))
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        logging.debug(f"Остановка: Сообщение 'Остановлен' (ID: {sent_message.message_id}) сохранено в LAST_MESSAGE_IDS.")

    else:
        logging.info(f"Запуск мониторинга трафика для {user_id} (ELSE блок)")
        logging.debug("Запуск: Очистка предыдущих сообщений...")
        await delete_previous_message(user_id, all_commands_to_delete, chat_id)

        def get_initial_counters():
            return psutil.net_io_counters()

        try:
            counters = await asyncio.to_thread(get_initial_counters)
            TRAFFIC_PREV[user_id] = (counters.bytes_recv, counters.bytes_sent)
            msg_text = ("📡 <b>Мониторинг трафика включен</b>...\n\n<i>Обновление каждые 5 секунд. Мониторинг НЕ будет остановлен при нажатии других кнопок. Нажмите '📡 Трафик сети' еще раз, чтобы остановить.</i>")
            sent_message = await message.answer(msg_text, parse_mode="HTML")
            TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
            logging.debug(f"Запуск: Сообщение 'Включен' (ID: {sent_message.message_id}) сохранено в TRAFFIC_MESSAGE_IDS.")
        except Exception as e:
            logging.error(f"Error starting traffic monitor for {user_id}: {e}")
            await message.answer(f"⚠️ Не удалось запустить мониторинг трафика: {e}")


async def update_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "update"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer("🔄 Выполняю обновление VPS... Это может занять несколько минут.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"
    process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    await delete_previous_message(user_id, command, chat_id)

    if process.returncode == 0:
        response_text = f"✅ Обновление завершено:\n<pre>{escape_html(output[-4000:])}</pre>"
    else:
        response_text = f"❌ Ошибка при обновлении (Код: {process.returncode}):\n<pre>{escape_html(error_output[-4000:])}</pre>"

    sent_message_final = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_final.message_id


async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "uptime"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    try:
        def read_uptime_file():
            with open("/proc/uptime") as f:
                return float(f.readline().split()[0])

        uptime_sec = await asyncio.to_thread(read_uptime_file)
        uptime_str = format_uptime(uptime_sec)
        sent_message = await message.answer(f"⏱ Время работы: <b>{uptime_str}</b>", parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
       logging.error(f"Ошибка в uptime_handler: {e}")
       sent_message = await message.answer(f"⚠️ Ошибка при получении аптайма: {str(e)}")
       LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def detect_xray_client():
    cmd = "docker ps --format '{{.Names}} {{.Image}}'"
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logging.error(f"Ошибка выполнения 'docker ps': {stderr.decode()}")
        raise Exception(f"Не удалось выполнить 'docker ps'. Убедитесь, что Docker установлен и запущен, и у бота есть права.\n<pre>{stderr.decode()}</pre>")

    containers = stdout.decode().strip().split('\n')
    if not containers:
        logging.warning("detect_xray_client: 'docker ps' не вернул контейнеров.")
        return None, None

    # Поиск Amnezia
    for line in containers:
        if not line: continue
        try:
            name, image = line.split(' ', 1)
            if 'amnezia' in image.lower() and 'xray' in image.lower():
                logging.info(f"Обнаружен Amnezia (контейнер: {name}, образ: {image})")
                return "amnezia", name
        except ValueError: continue

    # Поиск Marzban
    for line in containers:
        if not line: continue
        try:
            name, image = line.split(' ', 1)
            if ('marzban' in image.lower() or 'marzban' in name.lower()) and 'xray' not in name.lower():
                logging.info(f"Обнаружен Marzban (контейнер: {name}, образ: {image})")
                return "marzban", name
        except ValueError: continue

    logging.warning("Не удалось определить поддерживаемый Xray (Marzban, Amnezia).")
    return None, None


async def updatexray_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "updatexray"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)
    sent_msg = await message.answer("🔍 Определяю установленный клиент Xray...")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id
    try:
        client, container_name = await detect_xray_client() 

        if not client:
            await bot.edit_message_text("❌ Не удалось определить поддерживаемый клиент Xray (Marzban, Amnezia). Обновление невозможно.", chat_id=chat_id, message_id=sent_msg.message_id)
            return

        version = "неизвестной"
        client_name_display = client.capitalize()

        await bot.edit_message_text(f"✅ Обнаружен: <b>{client_name_display}</b> (контейнер: <code>{escape_html(container_name)}</code>). Начинаю обновление...", chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

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
        await bot.edit_message_text(final_message, chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка в updatexray_handler: {e}")
        error_msg = f"⚠️ <b>Ошибка обновления Xray:</b>\n\n{str(e)}"
        try:
             await bot.edit_message_text(error_msg , chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")
        except TelegramBadRequest as edit_e:
             if "message to edit not found" in str(edit_e):
                  logging.warning("UpdateXray: Failed to edit error message, likely deleted.")
                  await message.answer(error_msg, parse_mode="HTML")
             else:
                  raise
    finally:
        await state.clear()


# --- [БЛОК ИСПРАВЛЕНИЙ] Обработчики нажатий (callback) ---

# Отдельный обработчик для back_to_menu
@dp.callback_query(F.data == "back_to_menu")
async def cq_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    command = "back_to_menu"
    try:
        await state.clear()
        if not is_allowed(user_id, command):
            await callback.answer("⛔ Доступ запрещен.", show_alert=True)
            return
        await callback.message.edit_text("Возврат в меню...", reply_markup=None)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): pass
        elif "message to edit not found" in str(e): pass
        else:
            logging.error(f"Ошибка в cq_back_to_menu (edit): {e}")
            await callback.answer("⚠️ Ошибка при возврате в меню.", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_back_to_menu: {e}")
        await callback.answer("⚠️ Ошибка при возврате в меню.", show_alert=True)
    finally:
        await callback.answer()

# Обработчики для toggle_alert_*, alert_downtime_stub, get_id_inline, back_to_manage_users
@dp.callback_query(F.data.startswith("toggle_alert_"))
async def cq_toggle_alert(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "toggle_alert_resources"): 
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        alert_type = callback.data.split('_', 2)[-1]
        if alert_type not in ["resources", "logins", "bans"]: raise ValueError(f"Неизвестный тип алерта: {alert_type}")
    except Exception as e:
        logging.error(f"Ошибка разбора callback_data в cq_toggle_alert: {e} (data: {callback.data})")
        await callback.answer("⚠️ Внутренняя ошибка (неверный callback).", show_alert=True)
        return
    if user_id not in ALERTS_CONFIG: ALERTS_CONFIG[user_id] = {}
    current_state = ALERTS_CONFIG[user_id].get(alert_type, False)
    new_state = not current_state
    ALERTS_CONFIG[user_id][alert_type] = new_state
    save_alerts_config() 
    logging.info(f"Пользователь {user_id} изменил '{alert_type}' на {new_state}")
    new_keyboard = get_alerts_menu_keyboard(user_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_keyboard)
        if alert_type == "resources": alert_name = "Ресурсы"
        elif alert_type == "logins": alert_name = "Входы/Выходы SSH"
        else: alert_name = "Баны"
        await callback.answer(f"Уведомления '{alert_name}' {'✅ ВКЛЮЧЕНЫ' if new_state else '❌ ОТКЛЮЧЕНЫ'}.")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): await callback.answer("Состояние уже обновлено.")
        else:
            logging.error(f"Ошибка обновления клавиатуры уведомлений: {e}")
            await callback.answer("⚠️ Ошибка обновления интерфейса.", show_alert=True)
    except Exception as e:
        logging.error(f"Критическая ошибка в cq_toggle_alert: {e}")
        await callback.answer("⚠️ Критическая ошибка.", show_alert=True)

@dp.callback_query(F.data == "alert_downtime_stub")
async def cq_alert_downtime_stub(callback: types.CallbackQuery):
    await callback.answer(
        "⏳ Функция уведомлений о даунтайме сервера находится в разработке.\n"
        "Пока рекомендуем использовать внешние сервисы мониторинга (например, UptimeRobot).", 
        show_alert=True
    )

@dp.callback_query(F.data == "get_id_inline")
async def cq_get_id_inline(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    command = "get_id_inline"
    if not is_allowed(user_id, command):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            f"Ваш ID: <code>{user_id}</code>",
            parse_mode="HTML",
            reply_markup=get_back_keyboard("back_to_manage_users")
        )
        await callback.answer(f"Ваш ID: {user_id}")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): await callback.answer("Вы уже здесь.")
        else:
            logging.error(f"Ошибка в cq_get_id_inline (edit): {e}")
            await callback.answer("⚠️ Ошибка", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_get_id_inline: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

@dp.callback_query(F.data == "back_to_manage_users")
async def cq_back_to_manage_users(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    command = "back_to_manage_users"
    if not is_allowed(user_id, command):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        await state.clear() 
        user_list = "\n".join([
            f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
            for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
        ])
        if not user_list: user_list = "Других пользователей нет."
        await callback.message.edit_text(
            f"👤 <b>Управление пользователями</b>:\n\n{user_list}\n\nВыберите действие:",
            reply_markup=get_manage_users_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
    except TelegramBadRequest as e:
        if "message is not modified" in str(e): await callback.answer("Вы уже здесь.")
        else:
            logging.error(f"Ошибка в cq_back_to_manage_users (edit): {e}")
            await callback.answer("⚠️ Ошибка", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_back_to_manage_users: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

# --- Обработчики управления пользователями ---
@dp.callback_query(F.data == "add_user")
async def cq_add_user_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "add_user"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Добавление пользователя</b>\n\nВведите Telegram ID пользователя:",
        reply_markup=get_back_keyboard("back_to_manage_users"),
        parse_mode="HTML"
    )
    await state.set_state(ManageUsersStates.waiting_for_user_id)
    await callback.answer()

@dp.message(StateFilter(ManageUsersStates.waiting_for_user_id))
async def process_add_user_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    original_question_msg_id = None
    if user_id in LAST_MESSAGE_IDS and "manage_users" in LAST_MESSAGE_IDS[user_id]:
        original_question_msg_id = LAST_MESSAGE_IDS[user_id].get("manage_users") # Use get for safety
    elif message.reply_to_message and message.reply_to_message.from_user.is_bot:
         original_question_msg_id = message.reply_to_message.message_id

    try:
        new_user_id = int(message.text.strip())
        if new_user_id in ALLOWED_USERS:
            await message.reply("⚠️ Этот пользователь уже добавлен.")
            return

        await state.update_data(new_user_id=new_user_id)

        if original_question_msg_id:
            try:
                await bot.edit_message_text(
                    "Отлично. Теперь выберите группу для нового пользователя:",
                    chat_id=message.chat.id,
                    message_id=original_question_msg_id,
                    reply_markup=get_group_selection_keyboard()
                )
                await message.delete()
            except TelegramBadRequest as edit_err:
                 logging.warning(f"Не удалось отредактировать сообщение {original_question_msg_id} для выбора группы: {edit_err}. Отправляю новое.")
                 await message.reply(
                    "Отлично. Теперь выберите группу для нового пользователя:",
                    reply_markup=get_group_selection_keyboard()
                 )
        else:
             await message.reply(
                "Отлично. Теперь выберите группу для нового пользователя:",
                reply_markup=get_group_selection_keyboard()
             )

        await state.set_state(ManageUsersStates.waiting_for_group)
    except ValueError:
        await message.reply("⛔ Неверный ID. Пожалуйста, введите числовой Telegram ID.")
    except Exception as e:
        logging.error(f"Ошибка в process_add_user_id: {e}")
        await message.reply("⚠️ Произошла ошибка. Попробуйте еще раз.")

@dp.callback_query(StateFilter(ManageUsersStates.waiting_for_group), F.data.startswith("set_group_new_"))
async def process_add_user_group(callback: types.CallbackQuery, state: FSMContext):
    try:
        group = callback.data.split('_')[-1]
        user_data = await state.get_data()
        new_user_id = user_data.get('new_user_id')

        if not new_user_id:
             raise ValueError("Не найден ID пользователя в состоянии FSM.")

        ALLOWED_USERS[new_user_id] = group
        USER_NAMES[str(new_user_id)] = f"Новый_{new_user_id}" # Устанавливаем временное имя
        save_users() # Сохраняем с временным именем
        logging.info(f"Админ {callback.from_user.id} добавил пользователя {new_user_id} в группу '{group}'")

        # Запускаем обновление имени в фоне
        asyncio.create_task(refresh_user_names())

        await callback.message.edit_text(f"✅ Пользователь <code>{new_user_id}</code> успешно добавлен в группу <b>{group}</b>.", parse_mode="HTML", reply_markup=get_back_keyboard("back_to_manage_users"))
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка в process_add_user_group: {e}")
        await callback.message.edit_text("⚠️ Произошла ошибка при добавлении пользователя.", reply_markup=get_back_keyboard("back_to_manage_users"))
    finally:
        await callback.answer()


@dp.callback_query(F.data == "delete_user")
async def cq_delete_user_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "delete_user"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    keyboard = get_delete_users_keyboard(user_id)
    await callback.message.edit_text("➖ <b>Удаление пользователя</b>\n\nВыберите пользователя для удаления:", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_user_"))
async def cq_delete_user_confirm(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if not is_allowed(admin_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer("⛔ Нельзя удалить Главного Админа.", show_alert=True)
            return
        if user_id_to_delete not in ALLOWED_USERS:
            await callback.answer("⚠️ Пользователь не найден.", show_alert=True)
            keyboard = get_delete_users_keyboard(admin_id)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group = ALLOWED_USERS.pop(user_id_to_delete, "Неизвестно")
        USER_NAMES.pop(str(user_id_to_delete), None)
        save_users()
        logging.info(f"Админ {admin_id} удалил пользователя {deleted_user_name} ({user_id_to_delete}) из группы '{deleted_group}'")

        keyboard = get_delete_users_keyboard(admin_id)
        await callback.message.edit_text(f"✅ Пользователь <b>{deleted_user_name}</b> удален.\n\nВыберите пользователя для удаления:", reply_markup=keyboard, parse_mode="HTML")
        await callback.answer(f"Пользователь {deleted_user_name} удален.", show_alert=False)

    except Exception as e:
        logging.error(f"Ошибка в cq_delete_user_confirm: {e}")
        await callback.answer("⚠️ Ошибка при удалении.", show_alert=True)

@dp.callback_query(F.data.startswith("request_self_delete_"))
async def cq_request_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             await callback.answer("⛔ Ошибка: ID не совпадают.", show_alert=True)
             return
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer("⛔ Главный Админ не может удалить себя.", show_alert=True)
            return

        keyboard = get_self_delete_confirmation_keyboard(user_id)
        await callback.message.edit_text("⚠️ <b>Вы уверены, что хотите удалить себя из списка пользователей бота?</b>\nВы потеряете доступ ко всем командам.", reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        logging.error(f"Ошибка в cq_request_self_delete: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("confirm_self_delete_"))
async def cq_confirm_self_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_delete = int(callback.data.split('_')[-1])
        if user_id != user_id_to_delete:
             await callback.answer("⛔ Ошибка: ID не совпадают.", show_alert=True)
             return
        if user_id_to_delete == ADMIN_USER_ID:
            await callback.answer("⛔ Главный Админ не может удалить себя.", show_alert=True)
            return

        deleted_user_name = USER_NAMES.get(str(user_id_to_delete), f"ID: {user_id_to_delete}")
        deleted_group = ALLOWED_USERS.pop(user_id_to_delete, "Неизвестно")
        USER_NAMES.pop(str(user_id_to_delete), None)
        save_users()
        logging.info(f"Пользователь {deleted_user_name} ({user_id_to_delete}) удалил себя из группы '{deleted_group}'")

        await callback.message.delete()
        await callback.answer("✅ Вы успешно удалены из пользователей бота.", show_alert=True)

    except Exception as e:
        logging.error(f"Ошибка в cq_confirm_self_delete: {e}")
        await callback.answer("⚠️ Ошибка при удалении.", show_alert=True)

@dp.callback_query(F.data == "back_to_delete_users")
async def cq_back_to_delete_users(callback: types.CallbackQuery):
     await cq_delete_user_list(callback)


@dp.callback_query(F.data == "change_group")
async def cq_change_group_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, "change_group"):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    keyboard = get_change_group_keyboard()
    await callback.message.edit_text("🔄 <b>Изменение группы</b>\n\nВыберите пользователя:", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("select_user_change_group_"))
async def cq_select_user_for_group_change(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return
    try:
        user_id_to_change = int(callback.data.split('_')[-1])
        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            await callback.answer("⚠️ Неверный пользователь или Главный Админ.", show_alert=True)
            return

        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        current_group = ALLOWED_USERS[user_id_to_change]
        keyboard = get_group_selection_keyboard(user_id_to_change)
        await callback.message.edit_text(
            f"Выбран пользователь: <b>{user_name}</b>\nТекущая группа: <b>{current_group}</b>\n\nВыберите новую группу:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в cq_select_user_for_group_change: {e}")
        await callback.answer("⚠️ Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("set_group_"))
async def cq_set_group(callback: types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    is_adding_new_user = current_state == ManageUsersStates.waiting_for_group

    admin_id = callback.from_user.id
    if not is_allowed(admin_id, callback.data):
        await callback.answer("⛔ Доступ запрещен.", show_alert=True)
        return

    if is_adding_new_user:
        await process_add_user_group(callback, state)
        return

    try:
        parts = callback.data.split('_')
        user_id_to_change = int(parts[2])
        new_group = parts[3]

        if user_id_to_change not in ALLOWED_USERS or user_id_to_change == ADMIN_USER_ID:
            await callback.answer("⚠️ Неверный пользователь или Главный Админ.", show_alert=True)
            return

        old_group = ALLOWED_USERS[user_id_to_change]
        ALLOWED_USERS[user_id_to_change] = new_group
        save_users()
        user_name = USER_NAMES.get(str(user_id_to_change), f"ID: {user_id_to_change}")
        logging.info(f"Админ {admin_id} изменил группу для {user_name} ({user_id_to_change}) с '{old_group}' на '{new_group}'")

        keyboard = get_change_group_keyboard()
        await callback.message.edit_text(
             f"✅ Группа для <b>{user_name}</b> изменена на <b>{new_group}</b>.\n\nВыберите пользователя:",
             reply_markup=keyboard,
             parse_mode="HTML"
        )
        await callback.answer(f"Группа для {user_name} изменена.")

    except (IndexError, ValueError) as e:
         logging.error(f"Ошибка разбора callback_data в cq_set_group: {e} (data: {callback.data})")
         await callback.answer("⚠️ Внутренняя ошибка.", show_alert=True)
    except Exception as e:
        logging.error(f"Ошибка в cq_set_group: {e}")
        await callback.answer("⚠️ Ошибка при смене группы.", show_alert=True)


# --- [ КОНЕЦ БЛОКА УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЯМИ ] ---


# --- Text Handlers ---
@dp.message(F.text == "🔔 Уведомления")
async def notifications_menu_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "notifications_menu"

    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)

    keyboard = get_alerts_menu_keyboard(user_id)
    sent_message = await message.answer(
        "🔔 <b>Настройка уведомлений</b>\n\n"
        "Выберите, какие оповещения вы хотите получать.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


@dp.message(F.text == "🔒 Fail2Ban Log")
async def text_fall2ban_handler(message: types.Message):
    await fall2ban_handler(message)

@dp.message(F.text == "📜 SSH-лог")
async def text_sshlog_handler(message: types.Message):
    await sshlog_handler(message)

@dp.message(F.text == "📜 Последние события")
async def text_logs_handler(message: types.Message):
    await logs_handler(message)

@dp.message(F.text == "♻️ Перезапуск бота")
async def text_restart_handler(message: types.Message):
    await restart_handler(message)

@dp.message(F.text == "🛠 Сведения о сервере")
async def text_selftest_handler(message: types.Message):
    await selftest_handler(message)

@dp.message(F.text == "🚀 Скорость сети")
async def text_speedtest_handler(message: types.Message):
    await speedtest_handler(message)

@dp.message(F.text == "🔥 Топ процессов")
async def text_top_handler(message: types.Message):
    await top_handler(message)

@dp.message(F.text == "📡 Трафик сети")
async def text_traffic_handler(message: types.Message):
    await traffic_handler(message)

@dp.message(F.text == "🔄 Обновление VPS")
async def text_update_handler(message: types.Message):
    await update_handler(message)

@dp.message(F.text == "⏱ Аптайм")
async def text_uptime_handler(message: types.Message):
    await uptime_handler(message)

@dp.message(F.text == "🩻 Обновление X-ray")
async def text_updatexray_handler(message: types.Message, state: FSMContext):
    await updatexray_handler(message, state)


@dp.message(F.text == "🆔 Мой ID")
async def text_get_id_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "get_id"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    
    await delete_previous_message(user_id, command, message.chat.id)
    sent_message = await message.answer(
        f"Ваш ID: <code>{user_id}</code>\n\n"
        "<i>(Эта кнопка удалена из главного меню, но вы можете найти ее в меню '👤 Пользователи')</i>", 
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


# --- Reboot Handler ---
@dp.callback_query(F.data == "reboot")
async def reboot_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    command = "reboot" 

    if not is_allowed(user_id, command):
        try:
             await callback.answer("⛔ Отказано в доступе (не root).", show_alert=True) 
        except TelegramBadRequest:
             pass
        return

    try:
        await bot.edit_message_text("✅ Подтверждено. <b>Запускаю перезагрузку VPS</b>...", chat_id=chat_id, message_id=message_id, parse_mode="HTML")
    except TelegramBadRequest:
        logging.warning("Не удалось отредактировать сообщение о перезагрузке (возможно, удалено).")

    try:
        with open(REBOOT_FLAG_FILE, "w") as f:
            f.write(str(user_id))
    except Exception as e:
        logging.error(f"Не удалось записать флаг перезагрузки: {e}")

    try:
        # Убираем sudo, если уже root
        reboot_cmd = "reboot" if INSTALL_MODE == "root" else "sudo reboot"
        logging.info(f"Выполнение команды перезагрузки: {reboot_cmd}")
        process = await asyncio.create_subprocess_shell(reboot_cmd)
        logging.info("Команда перезагрузки отправлена.")
    except Exception as e:
        logging.error(f"Ошибка при отправке команды reboot: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при отправке команды перезагрузки: {e}")
        except Exception as send_e:
            logging.error(f"Не удалось отправить сообщение об ошибке перезагрузки: {send_e}")


# --- Background Tasks & Startup ---
async def traffic_monitor():
    await asyncio.sleep(TRAFFIC_INTERVAL)
    while True:
        current_users = list(TRAFFIC_MESSAGE_IDS.keys())
        if not current_users:
            await asyncio.sleep(TRAFFIC_INTERVAL)
            continue

        for user_id in current_users:
            if user_id not in TRAFFIC_MESSAGE_IDS: continue
            message_id = TRAFFIC_MESSAGE_IDS.get(user_id)
            if not message_id:
                logging.warning(f"Traffic monitor: Missing message ID for user {user_id}")
                TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                continue

            try:
                def get_traffic_update():
                    counters_now = psutil.net_io_counters()
                    rx_now = counters_now.bytes_recv
                    tx_now = counters_now.bytes_sent
                    prev_rx, prev_tx = TRAFFIC_PREV.get(user_id, (rx_now, tx_now))
                    rx_delta = max(0, rx_now - prev_rx)
                    tx_delta = max(0, tx_now - prev_tx)
                    rx_speed = rx_delta * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                    tx_speed = tx_delta * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                    return rx_now, tx_now, rx_speed, tx_speed

                rx, tx, rx_speed, tx_speed = await asyncio.to_thread(get_traffic_update)
                TRAFFIC_PREV[user_id] = (rx, tx)

                msg_text = (f"📡 Общий трафик:\n"
                            f"=========================\n"
                            f"⬇️ RX: {format_traffic(rx)}\n"
                            f"⬆️ TX: {format_traffic(tx)}\n\n"
                            f"⚡️ Скорость соединения:\n"
                            f"=========================\n"
                            f"⬇️ RX: {rx_speed:.2f} Мбит/с\n"
                            f"⬆️ TX: {tx_speed:.2f} Мбит/с")

                await bot.edit_message_text(chat_id=user_id, message_id=message_id, text=msg_text)

            except TelegramRetryAfter as e:
                logging.warning(f"Traffic Monitor: TelegramRetryAfter for {user_id}: Wait {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e): pass
                elif "message to edit not found" in str(e) or "chat not found" in str(e):
                    logging.warning(f"Traffic Monitor: Message/Chat not found for user {user_id}. Stopping monitor.")
                    TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                    TRAFFIC_PREV.pop(user_id, None)
                else:
                    logging.error(f"Traffic Monitor: Unexpected TelegramBadRequest for {user_id}: {e}")
                    TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                    TRAFFIC_PREV.pop(user_id, None)
            except Exception as e:
                logging.error(f"Traffic Monitor: Critical error updating for {user_id}: {e}")
                TRAFFIC_MESSAGE_IDS.pop(user_id, None)
                TRAFFIC_PREV.pop(user_id, None)

        await asyncio.sleep(TRAFFIC_INTERVAL)

# Новая логика повторных алертов
async def resource_monitor():
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
            logging.debug(f"Проверка ресурсов: CPU={cpu_usage}%, RAM={ram_usage}%, Disk={disk_usage}%")

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
                 alerts_to_send.append(f"✅ <b>Нагрузка CPU нормализовалась.</b>\nТекущее использование: <b>{cpu_usage:.1f}%</b>")
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
                 alerts_to_send.append(f"✅ <b>Использование RAM нормализовалось.</b>\nТекущее использование: <b>{ram_usage:.1f}%</b>")
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
                 alerts_to_send.append(f"✅ <b>Использование Disk нормализовалось.</b>\nТекущее использование: <b>{disk_usage:.1f}%</b>")
                 logging.info("Сгенерирован алерт нормализации Disk.")
                 RESOURCE_ALERT_STATE["disk"] = False
                 LAST_RESOURCE_ALERT_TIME["disk"] = 0

            if alerts_to_send:
                full_alert_message = "\n\n".join(alerts_to_send)
                await send_alert(full_alert_message, "resources")

        except Exception as e:
            logging.error(f"Ошибка в мониторе ресурсов: {e}")

        await asyncio.sleep(RESOURCE_CHECK_INTERVAL)


async def initial_restart_check():
    if os.path.exists(RESTART_FLAG_FILE):
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
                chat_id, message_id = map(int, content.split(':'))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="✅ Бот успешно перезапущен.")
            logging.info(f"Изменено сообщение о перезапуске в чате ID: {chat_id}")
        except FileNotFoundError: logging.info("Restart flag file not found on startup.")
        except ValueError: logging.error("Invalid content in restart flag file.")
        except TelegramBadRequest as e: logging.warning(f"Failed to edit restart message (likely deleted or invalid): {e}")
        except Exception as e: logging.error(f"Ошибка при обработке флага перезапуска: {e}")
        finally:
            try: os.remove(RESTART_FLAG_FILE)
            except OSError as e:
                 if e.errno != 2: logging.error(f"Error removing restart flag file: {e}")


async def initial_reboot_check():
    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                user_id_str = f.read().strip()
                if not user_id_str.isdigit(): raise ValueError("Invalid content in reboot flag file.")
                user_id = int(user_id_str)
            await bot.send_message(chat_id=user_id, text="✅ <b>Сервер успешно перезагружен! Бот снова в сети.</b>", parse_mode="HTML")
            logging.info(f"Отправлено уведомление о перезагрузке пользователю ID: {user_id}")
        except FileNotFoundError: logging.info("Reboot flag file not found on startup.")
        except ValueError as ve: logging.error(f"Error processing reboot flag file content: {ve}")
        except TelegramBadRequest as e: logging.warning(f"Failed to send reboot notification to user {user_id_str}: {e}")
        except Exception as e: logging.error(f"Ошибка при обработке флага перезагрузки: {e}")
        finally:
             try: os.remove(REBOOT_FLAG_FILE)
             except OSError as e:
                  if e.errno != 2: logging.error(f"Error removing reboot flag file: {e}")


# Новая логика `main` для корректного завершения (v3)
async def main():
    background_tasks = set()

    async def shutdown(dispatcher: Dispatcher, bot_instance: Bot):
        logging.info("Получен сигнал завершения. Остановка polling...")
        try:
            await dispatcher.stop_polling()
            logging.info("Polling остановлен.")
        except Exception as e:
            logging.error(f"Ошибка при остановке polling: {e}")

        logging.info("Начинаю отмену фоновых задач...")
        for task in list(background_tasks):
            if task and not task.done():
                task.cancel()

        logging.info("Ожидание завершения фоновых задач (с таймаутом)...")
        results = await asyncio.gather(*background_tasks, return_exceptions=True)
        background_tasks.clear()

        for i, result in enumerate(results):
             if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                 logging.error(f"Ошибка при завершении фоновой задачи (индекс {i}): {result}")
        logging.info("Фоновые задачи обработаны.")

        session_to_close = getattr(bot_instance, 'session', None)
        underlying_session = getattr(session_to_close, 'session', None)

        if underlying_session and not underlying_session.closed:
            logging.info("Закрытие сессии бота...")
            await session_to_close.close()
            logging.info("Сессия бота закрыта.")
        elif session_to_close:
             logging.info("Сессия бота уже была закрыта.")
        else:
             logging.info("Сессия бота не была инициализирована.")

    loop = asyncio.get_event_loop()
    try:
        signals = (signal.SIGINT, signal.SIGTERM)
        for s in signals:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(dp, bot)))
        logging.info("Обработчики сигналов SIGINT и SIGTERM установлены.")
    except NotImplementedError:
        logging.warning("Установка обработчиков сигналов не поддерживается на этой платформе.")

    try:
        logging.info(f"Бот запускается в режиме: {INSTALL_MODE.upper()}")
        await asyncio.to_thread(load_users)
        load_alerts_config()
        await refresh_user_names() # Обновляем имена при старте
        await initial_reboot_check()
        await initial_restart_check()

        # Запуск мониторов
        ssh_log_file_to_monitor = None
        if os.path.exists("/var/log/secure"): ssh_log_file_to_monitor = "/var/log/secure"
        elif os.path.exists("/var/log/auth.log"): ssh_log_file_to_monitor = "/var/log/auth.log"
        f2b_log_file_to_monitor = "/var/log/fail2ban.log"

        if ssh_log_file_to_monitor:
            task_logins = asyncio.create_task(reliable_tail_log_monitor(ssh_log_file_to_monitor, "logins", parse_ssh_log_line), name="LoginsMonitor")
            background_tasks.add(task_logins)
        else: logging.warning("Не найден лог SSH. Мониторинг SSH (logins) не запущен.")
            
        task_bans = asyncio.create_task(reliable_tail_log_monitor(f2b_log_file_to_monitor, "bans", parse_f2b_log_line), name="BansMonitor")
        background_tasks.add(task_bans)
        task_traffic = asyncio.create_task(traffic_monitor(), name="TrafficMonitor")
        background_tasks.add(task_traffic)
        task_resources = asyncio.create_task(resource_monitor(), name="ResourceMonitor")
        background_tasks.add(task_resources)
        
        logging.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        
    except (KeyboardInterrupt, SystemExit):
        logging.info("Получен KeyboardInterrupt/SystemExit в блоке try функции main.")
    except Exception as e:
        logging.critical(f"Критическая ошибка в главном цикле бота: {e}", exc_info=True)
        
    finally:
        session_to_check = getattr(bot, 'session', None)
        underlying_session_to_check = getattr(session_to_check, 'session', None)
        session_closed_attr = getattr(underlying_session_to_check, 'closed', True)

        if not session_closed_attr:
             logging.warning("Polling завершился неожиданно или shutdown не сработал полностью. Повторная попытка очистки...")
             await shutdown(dp, bot)
        
        logging.info("Функция main бота завершена.")


if __name__ == "__main__":
    import signal
    try:
        logging.info("Запуск asyncio.run(main())...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную (KeyboardInterrupt в __main__).")
    except Exception as e:
        logging.critical(f"Непредвиденное завершение вне цикла asyncio: {e}", exc_info=True)
    finally:
         logging.info("Скрипт bot.py завершает работу.")