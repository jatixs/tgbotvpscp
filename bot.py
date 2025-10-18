import asyncio
import os
import psutil
import re
import json
import urllib.parse
import logging
import requests
import sys
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
ALERTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "alerts_config.json") # Added alerts config file path

LOG_FILE = os.path.join(LOG_DIR, "bot.log")
logging.basicConfig(level=logging.INFO, filename=LOG_FILE, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

TRAFFIC_INTERVAL = 5
RESOURCE_CHECK_INTERVAL = 300 # Проверять ресурсы каждые 5 минут (300 секунд)
CPU_THRESHOLD = 90.0         # %
RAM_THRESHOLD = 90.0         # %
DISK_THRESHOLD = 95.0        # %

ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}
ALERTS_CONFIG = {} # Словарь для хранения настроек уведомлений {user_id: {"resources": bool, "logins": bool, "bans": bool}}
RESOURCE_ALERT_STATE = {"cpu": False, "ram": False, "disk": False} # Словарь для отслеживания состояния ресурсов


bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class GenerateVlessStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_name = State()

class ManageUsersStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()
    waiting_for_change_group = State()

# --- Alert Config Functions ---
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

load_alerts_config() # Load config on start

# --- Helper Functions ---
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
        # os.chmod(USERS_FILE, 0o664) # Permissions handled by deploy.sh potentially
        logging.info(f"Успешно сохранено users.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}")

def is_allowed(user_id, command=None):
    if user_id not in ALLOWED_USERS:
        return False

    # Allow basic commands and notifications menu for all allowed users
    user_commands = ["start", "menu", "back_to_menu", "uptime", "traffic", "selftest", "get_id", "get_id_inline", "notifications_menu", "toggle_alert_resources", "toggle_alert_logins", "toggle_alert_bans", "alert_downtime_stub"]
    if command in user_commands:
        return True

    is_admin_group = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    if not is_admin_group:
        return False # Rest are admin only or root only

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

    # Allow callback commands related to admin actions
    if command and any(cmd in command for cmd in ["delete_user", "set_group", "change_group", "xray_install"]):
        return True

    # Default deny for unknown commands if not covered above
    return False


async def refresh_user_names():
    needs_save = False
    for uid in list(ALLOWED_USERS.keys()):
        if str(uid) not in USER_NAMES or USER_NAMES.get(str(uid)) == "Главный Админ":
            try:
                chat = await bot.get_chat(uid)
                new_name = chat.first_name or chat.username or f"Пользователь_{uid}"
                if USER_NAMES.get(str(uid)) != new_name:
                    USER_NAMES[str(uid)] = new_name
                    needs_save = True
            except Exception as e:
                logging.warning(f"Не удалось обновить имя для {uid}: {e}")
                USER_NAMES[str(uid)] = f"ID: {uid}"

    if needs_save:
        save_users()

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
        [KeyboardButton(text="⏱ Аптайм"), KeyboardButton(text="🆔 Мой ID")],
        [KeyboardButton(text="🔔 Уведомления")]
    ]

    admin_buttons_flat = [btn.text for row in buttons for btn in row] # Existing button texts

    if is_admin:
        if INSTALL_MODE == 'secure':
            secure_admin_buttons = [
                [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                [KeyboardButton(text="🚀 Скорость сети"), KeyboardButton(text="🔥 Топ процессов")],
                [KeyboardButton(text="🩻 Обновление X-ray")],
            ]
            # Add only new buttons
            for row in reversed(secure_admin_buttons):
                new_row = [btn for btn in row if btn.text not in admin_buttons_flat]
                if new_row:
                    buttons.insert(0, new_row)
                    admin_buttons_flat.extend([btn.text for btn in new_row]) # Update flat list


        elif INSTALL_MODE == 'root':
             root_admin_buttons = [
                 [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                 [KeyboardButton(text="🔥 Топ процессов"), KeyboardButton(text="📜 SSH-лог")],
                 [KeyboardButton(text="🔒 Fail2Ban Log"), KeyboardButton(text="📜 Последние события")],
                 [KeyboardButton(text="🚀 Скорость сети")],
                 [KeyboardButton(text="🔄 Обновление VPS"), KeyboardButton(text="🩻 Обновление X-ray")],
                 [KeyboardButton(text="🔄 Перезагрузка сервера"), KeyboardButton(text="♻️ Перезапуск бота")]
             ]
             # Add only new buttons
             for row in reversed(root_admin_buttons):
                 new_row = [btn for btn in row if btn.text not in admin_buttons_flat]
                 if new_row:
                     buttons.insert(0, new_row)
                     admin_buttons_flat.extend([btn.text for btn in new_row]) # Update flat list


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
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), "Я"), reverse=False)

    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID:
            continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
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
    sorted_users = sorted(ALLOWED_USERS.items(), key=lambda item: USER_NAMES.get(str(item[0]), "Я"), reverse=False)
    for uid, group in sorted_users:
        if uid == ADMIN_USER_ID:
            continue
        user_name = USER_NAMES.get(str(uid), f"ID: {uid}")
        buttons.append([InlineKeyboardButton(text=f"{user_name} ({group})", callback_data=f"select_user_change_group_{uid}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_manage_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_selection_keyboard(user_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👑 Админы", callback_data=f"set_group_{user_id}_Админы"),
            InlineKeyboardButton(text="👤 Пользователи", callback_data=f"set_group_{user_id}_Пользователи")
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
    if command != "traffic" and user_id in TRAFFIC_MESSAGE_IDS:
        if TRAFFIC_MESSAGE_IDS.get(user_id):
            try:
                await bot.delete_message(chat_id=user_id, message_id=TRAFFIC_MESSAGE_IDS.pop(user_id))
            except (TelegramBadRequest, KeyError) as e:
                 logging.warning(f"Could not delete traffic message for {user_id}: {e}")
        else:
             TRAFFIC_MESSAGE_IDS.pop(user_id, None)

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
    # Собираем список ID пользователей, которым нужно отправить
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
            await asyncio.sleep(0.1) # Небольшая задержка между отправками
        except TelegramBadRequest as e:
            if "chat not found" in str(e) or "bot was blocked by the user" in str(e):
                logging.warning(f"Не удалось отправить алерт пользователю {user_id}: чат не найден или бот заблокирован.")
            else:
                logging.error(f"Неизвестная ошибка TelegramBadRequest при отправке алерта {user_id}: {e}")
        except Exception as e:
            logging.error(f"Ошибка при отправке алерта пользователю {user_id}: {e}")

    logging.info(f"Алерт типа '{alert_type}' отправлен {sent_count} пользователям.")


# --- Command Handlers ---
@dp.message(Command("start", "menu"))
@dp.message(F.text == "🔙 Назад в меню")
async def start_or_menu_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "start" if message.text == "/start" else "menu"
    await state.clear()
    if user_id not in ALLOWED_USERS:
        await send_access_denied_message(user_id, chat_id, command)
        return
    # Include potential alert menu message ID for deletion
    await delete_previous_message(user_id, ["start", "menu", "manage_users", "reboot_confirm", "generate_vless", "adduser", "notifications_menu"], chat_id)
    if str(user_id) not in USER_NAMES:
       await refresh_user_names()
    sent_message = await message.answer(
        "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu.",
        reply_markup=get_main_reply_keyboard(user_id)
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

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
    sent_message = await message.answer("📤 <b>Отправьте файл конфигурации Xray (JSON)</b>\n\n<i>Важно: файл должен содержать рабочую конфигурацию outbound с Reality.</i>", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    await state.set_state(GenerateVlessStates.waiting_for_file)

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
async def get_id_handler(message: types.Message):
    user_id = message.from_user.id
    command = "get_id"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, message.chat.id, command)
        return
    await delete_previous_message(user_id, command, message.chat.id)
    group = ALLOWED_USERS.get(user_id, 'не авторизован')
    sent_message = await message.answer(f"🆔 Ваш ID: <code>{user_id}</code>\nГруппа: <b>{group}</b>", parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(F.text == "🔔 Уведомления")
async def notifications_handler(message: types.Message):
    user_id = message.from_user.id
    command = "notifications_menu"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, message.chat.id, command)
        return

    await delete_previous_message(user_id, command, message.chat.id)

    sent_message = await message.answer(
        "🔔 <b>Настройка уведомлений</b>\nВыберите, какие оповещения вы хотите получать:",
        reply_markup=get_alerts_menu_keyboard(user_id),
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


# --- Callback Handlers ---
@dp.callback_query(F.data.startswith("toggle_alert_"))
async def toggle_alert_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_allowed(user_id, callback.data): # Check permission for the specific toggle action
        await callback.answer("⛔ У вас нет прав изменять эти настройки.", show_alert=True)
        return

    alert_type = callback.data.split("_")[2] # resources, logins, bans

    user_config = ALERTS_CONFIG.setdefault(user_id, {"resources": False, "logins": False, "bans": False})

    current_state = user_config.get(alert_type, False)
    user_config[alert_type] = not current_state
    new_state = user_config[alert_type]

    save_alerts_config()

    try:
        await callback.message.edit_reply_markup(reply_markup=get_alerts_menu_keyboard(user_id))
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.error(f"Ошибка обновления клавиатуры уведомлений: {e}")

    alert_name_map = {
        "resources": "о ресурсах (CPU/RAM/Disk)",
        "logins": "о входах/выходах SSH",
        "bans": "о банах Fail2Ban"
    }
    alert_name = alert_name_map.get(alert_type, alert_type)
    state_text = "ВКЛЮЧЕНЫ" if new_state else "ВЫКЛЮЧЕНЫ"
    await callback.answer(f"Уведомления {alert_name} {state_text}")


@dp.callback_query(F.data == "alert_downtime_stub")
async def alert_downtime_stub_callback(callback: types.CallbackQuery):
     if not is_allowed(callback.from_user.id, callback.data):
        await callback.answer("⛔ У вас нет прав.", show_alert=True)
        return
     await callback.answer("🕒 Функция мониторинга даунтайма находится в разработке.\nРекомендуется использовать внешние сервисы, например, UptimeRobot.", show_alert=True)


@dp.callback_query() # General callback handler (should be last)
async def callback_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    command = callback.data
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    # Handle specific back buttons or other actions not covered by prefixes
    if command == "back_to_menu":
        await callback.message.delete()
        # Ensure correct handling if called from alert menu context
        await delete_previous_message(user_id, ["notifications_menu", "menu"], chat_id)
        sent_message = await bot.send_message(chat_id=chat_id, text="📋 Главное меню:", reply_markup=get_main_reply_keyboard(user_id))
        LAST_MESSAGE_IDS.setdefault(user_id, {})["menu"] = sent_message.message_id
        return
    elif command == "back_generate_vless":
        if await state.get_state() is not None: # Only clear state if it exists
             await state.clear()
        await callback.message.delete()
        # Optionally send back to main menu or do nothing
        return
    elif command == "back_to_manage_users":
        if not is_allowed(user_id, "manage_users"):
            await callback.message.answer("⛔ У вас нет прав для этого действия.")
            return
        await state.clear() # Clear potential add user state
        user_list = "\n".join([
            f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
            for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
        ])
        if not user_list: user_list = "Других пользователей нет."
        try:
             await callback.message.edit_text(
                 f"👤 <b>Управление пользователями</b>:\n\n{user_list}\n\nВыберите действие:",
                 reply_markup=get_manage_users_keyboard(),
                 parse_mode="HTML"
             )
        except TelegramBadRequest as e:
             if "message to edit not found" not in str(e): raise e # Re-raise if other error
             logging.warning("Failed to edit back to user management, message likely deleted.")
        return


    # --- Rest of the previous callback_handler logic ---
    permission_check_command = command
    if command.startswith(("delete_user_", "set_group_", "select_user_change_group_", "request_self_delete_", "confirm_self_delete_", "back_to_delete_users", "xray_install_")):
       permission_check_command = "manage_users"

    if not is_allowed(user_id, permission_check_command):
        if user_id not in ALLOWED_USERS:
            await send_access_denied_message(user_id, chat_id, command)
        else:
            await callback.message.answer(f"⛔ Команда '{command}' недоступна для вашей группы ({ALLOWED_USERS[user_id]}) или в текущем режиме установки.")
        return

    try:
        if command == "add_user":
            await delete_previous_message(user_id, "manage_users", chat_id)
            sent_message = await callback.message.answer("📝 Введите ID или Alias пользователя (например, <code>@username</code>):", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
            LAST_MESSAGE_IDS.setdefault(user_id, {})["add_user"] = sent_message.message_id
            await state.set_state(ManageUsersStates.waiting_for_user_id)
        elif command == "delete_user":
            await callback.message.edit_text("➖ Выберите пользователя для удаления:", reply_markup=get_delete_users_keyboard(user_id))
        elif command == "change_group":
            await callback.message.edit_text("🔄 Выберите пользователя для изменения группы:", reply_markup=get_change_group_keyboard())
        elif command.startswith("select_user_change_group_"):
            target_user_id = int(command.split("_")[4])
            if target_user_id not in ALLOWED_USERS:
                await callback.message.edit_text(f"⚠️ Пользователь ID <code>{target_user_id}</code> не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
            else:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                await callback.message.edit_text(f"👤 Пользователь: <b>{user_name}</b>\nТекущая группа: <b>{ALLOWED_USERS[target_user_id]}</b>\nВыберите новую группу:", reply_markup=get_group_selection_keyboard(target_user_id), parse_mode="HTML")
        elif command.startswith("set_group_"):
            parts = command.split("_")
            target_user_id = int(parts[2])
            new_group = parts[3]
            if target_user_id == ADMIN_USER_ID:
                await callback.message.edit_text("⚠️ Нельзя изменить группу главного администратора", reply_markup=get_back_keyboard("back_to_manage_users"))
            elif target_user_id not in ALLOWED_USERS:
                await callback.message.edit_text(f"⚠️ Пользователь ID <code>{target_user_id}</code> не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
            else:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                ALLOWED_USERS[target_user_id] = new_group
                save_users()
                await callback.message.edit_text(f"✅ Группа пользователя <b>{user_name}</b> изменена на <b>{new_group}</b>", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
                await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную командой или кнопкой (если доступна).")
        # back_to_manage_users handled above
        elif command == "back_to_delete_users":
            await callback.message.edit_text("➖ Выберите пользователя для удаления:", reply_markup=get_delete_users_keyboard(user_id))
        elif command.startswith("request_self_delete_"):
            target_user_id = int(command.split("_")[3])
            if target_user_id != user_id:
                await callback.message.edit_text("⚠️ Вы можете запросить удаление только своего ID", reply_markup=get_back_keyboard("back_to_delete_users"))
            else:
                await callback.message.edit_text("⚠️ Ты точно уверен, что хочешь удалить самого себя из бота? Данное действие необратимо, ты можешь потерять доступ к боту", reply_markup=get_self_delete_confirmation_keyboard(user_id))
        elif command.startswith("confirm_self_delete_"):
            target_user_id = int(command.split("_")[3])
            if target_user_id != user_id:
                await callback.message.edit_text("⚠️ Вы можете подтвердить удаление только своего ID", reply_markup=get_back_keyboard("back_to_delete_users"))
            elif target_user_id == ADMIN_USER_ID:
                await callback.message.edit_text("⚠️ Нельзя удалить главного администратора", reply_markup=get_back_keyboard("back_to_manage_users"))
            else:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                if target_user_id in ALLOWED_USERS:
                    del ALLOWED_USERS[target_user_id]
                    USER_NAMES.pop(str(target_user_id), None)
                    save_users()
                    await callback.message.edit_text(f"✅ Пользователь <b>{user_name}</b> удалён. Вы потеряли доступ к боту.", parse_mode="HTML")
                    await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")
                else:
                    await callback.message.edit_text(f"⚠️ Пользователь ID <code>{target_user_id}</code> уже был удален.", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
        elif command.startswith("delete_user_"):
            target_user_id = int(command.split("_")[2])
            if target_user_id == ADMIN_USER_ID:
                await callback.message.edit_text("⚠️ Нельзя удалить главного администратора", reply_markup=get_back_keyboard("back_to_manage_users"))
            elif target_user_id in ALLOWED_USERS:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                del ALLOWED_USERS[target_user_id]
                USER_NAMES.pop(str(target_user_id), None)
                save_users()
                await callback.message.edit_text(f"✅ Пользователь <b>{user_name}</b> удалён", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
                await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")
            else:
                await callback.message.edit_text(f"⚠️ Пользователь ID <code>{target_user_id}</code> не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
        elif command == "get_id_inline":
           await callback.message.answer(f"🆔 Ваш ID: {user_id}\nГруппа: {ALLOWED_USERS.get(user_id, 'не авторизован')}")
        elif command == "reboot":
           await reboot_handler(callback)
        # back_generate_vless handled above
        # back_to_menu handled above
        else:
            logging.warning(f"Неизвестный callback_data: {command}")
            await callback.answer("Неизвестная команда.")


    except TelegramRetryAfter as e:
        logging.error(f"TelegramRetryAfter в callback_handler: {e.retry_after} секунд")
        await callback.message.answer(f"⚠️ Telegram ограничивает запросы. Повторите через {e.retry_after} секунд.")
    except TelegramBadRequest as e:
         if "message to edit not found" in str(e) or "message can't be edited" in str(e):
             logging.warning(f"Message edit failed in callback_handler (likely deleted): {e}")
         else:
             logging.warning(f"TelegramBadRequest в callback_handler: {e}")
    except Exception as e:
        logging.error(f"Ошибка в callback_handler: {e}", exc_info=True)
        try:
            # Send error without editing the original message if edit fails
            await bot.send_message(chat_id, f"⚠️ Ошибка при выполнении команды: {str(e)}")
        except Exception as send_e:
            logging.error(f"Failed to send error message: {send_e}")


# --- State Handlers ---
@dp.message(Command("adduser"))
async def adduser_command_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "adduser"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer(
        "📝 Введите ID или Alias пользователя (например, <code>@username</code>):",
        reply_markup=get_back_keyboard("back_to_manage_users"),
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    await state.set_state(ManageUsersStates.waiting_for_user_id)

@dp.message(StateFilter(ManageUsersStates.waiting_for_user_id))
async def handle_user_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "adduser"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return
    input_text = message.text.strip()
    target_user_id = None
    user_name = "Неизвестный"
    try:
        if input_text.startswith("@"):
            if not re.match(r'^@[\w_]{5,}$', input_text):
                raise ValueError("Неверный формат никнейма.")
            chat = await bot.get_chat(input_text)
            target_user_id = chat.id
            user_name = chat.first_name or chat.username or f"Неизвестный_{target_user_id}"
        else:
            try:
                target_user_id = int(input_text)
                user_name = await get_user_name(target_user_id)
            except ValueError:
                raise ValueError("Введите корректный ID (число) или Alias (@username).")
        if target_user_id in ALLOWED_USERS:
            await state.clear()
            await delete_previous_message(user_id, command, chat_id)
            sent_message = await message.answer(f"⚠️ Пользователь <b>{user_name}</b> (ID: <code>{target_user_id}</code>) уже в списке разрешённых.", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
            LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
            return
        ALLOWED_USERS[target_user_id] = "Пользователи"
        USER_NAMES[str(target_user_id)] = user_name
        save_users()
        await state.update_data(target_user_id=target_user_id, user_name=user_name)
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(f"👤 Пользователь: <b>{user_name}</b> (ID: <code>{target_user_id}</code>)\nТекущая группа: <b>Пользователи</b>\nВыберите группу:", reply_markup=get_group_selection_keyboard(target_user_id), parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.set_state(ManageUsersStates.waiting_for_group)
    except (TelegramBadRequest, ValueError) as e:
        error_text = str(e)
        if "Bad Request: chat not found" in error_text or "Неверный формат" in error_text or "user not found" in error_text:
             error_text = (f"❌ <b>Не удалось найти пользователя <code>{input_text}</code>.</b>\n\n" "Возможные причины:\n" "1. Пользователь не существует или закрыл личку.\n" "2. Пользователь должен <b>сначала написать боту команду /start</b>.\n\n" "💡 <b>Решение:</b> Добавляйте по <b>User ID</b> (число) или попросите пользователя написать /start.")
        else:
            error_text = f"⚠️ Произошла непредвиденная ошибка: {escape_html(str(e))}"
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(error_text, parse_mode="HTML", reply_markup=get_back_keyboard("back_to_manage_users"))
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.clear()
    except Exception as e:
        logging.error(f"Непредвиденная ошибка при добавлении пользователя: {e}")
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(f"⚠️ Произошла непредвиденная ошибка: {escape_html(str(e))}", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.clear()


@dp.callback_query(StateFilter(ManageUsersStates.waiting_for_group))
async def handle_group_selection_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    command = "adduser"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, callback.message.chat.id, command)
        await state.clear()
        return
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    user_name = data.get("user_name")
    if callback.data.startswith("set_group_"):
        parts = callback.data.split("_")
        selected_id = int(parts[2])
        new_group = parts[3]
        if selected_id != target_user_id:
            await callback.message.edit_text("⚠️ Ошибка: Несоответствие ID пользователя.", reply_markup=get_back_keyboard("back_to_manage_users"))
            await state.clear()
            return
        ALLOWED_USERS[target_user_id] = new_group
        save_users()
        await state.clear()
        await callback.message.edit_text(f"✅ Пользователь <b>{user_name}</b> (ID: <code>{target_user_id}</code>) добавлен в группу <b>{new_group}</b>", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="HTML")
        await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")
    elif callback.data == "back_to_manage_users":
        await state.clear()
        user_list = "\n".join([
            f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (<b>{group}</b>)"
            for uid, group in ALLOWED_USERS.items() if uid != ADMIN_USER_ID
        ])
        if not user_list:
            user_list = "Других пользователей нет."
        await callback.message.edit_text(
            f"👤 <b>Управление пользователями</b>:\n\n{user_list}\n\nВыберите действие:",
            reply_markup=get_manage_users_keyboard(),
            parse_mode="HTML"
        )

# --- Other Handlers (VLESS, etc.) ---
@dp.message(StateFilter(GenerateVlessStates.waiting_for_file), F.document)
async def handle_vless_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return
    if not message.document or not message.document.file_name.endswith(".json"):
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("❌ Пожалуйста, отправьте корректный <b>JSON файл</b>.", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        return
    try:
        file_info = await bot.get_file(message.document.file_id)
        file_content_stream = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=file_content_stream)
        file_content_stream.seek(0)
        json_data = file_content_stream.read().decode('utf-8')

        try:
            def validate_json(data):
                 json.loads(data)
            await asyncio.to_thread(validate_json, json_data)
        except json.JSONDecodeError:
            raise ValueError("Содержимое файла не является корректным JSON.")

        await state.update_data(json_data=json_data)
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("📝 Введите <b>имя</b> для VLESS ссылки:", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.set_state(GenerateVlessStates.waiting_for_name)
    except Exception as e:
        logging.error(f"Ошибка при обработке файла VLESS: {e}")
        await state.clear()
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(f"⚠️ Ошибка при обработке файла: <b>{str(e)}</b>", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


@dp.message(StateFilter(GenerateVlessStates.waiting_for_file))
async def handle_vless_file_wrong_type(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return
    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer("❌ Ожидается отправка <b>JSON файла</b>. Попробуйте еще раз или нажмите Назад.", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


@dp.message(StateFilter(GenerateVlessStates.waiting_for_name))
async def handle_vless_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return

    custom_name = message.text.strip()
    if not custom_name:
       custom_name = f"VLESS_Config_{user_id}"

    data = await state.get_data()
    json_data = data.get("json_data")
    await state.clear()

    if not json_data:
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("⚠️ Ошибка: JSON данные не найдены, начните сначала.", reply_markup=get_back_keyboard("back_to_menu"))
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        return

    await delete_previous_message(user_id, command, chat_id)

    try:
        def generate_vless_and_qr(data, name):
            vless_url_result = convert_json_to_vless(data, name)
            if vless_url_result.startswith("⚠️"):
                raise ValueError(vless_url_result)

            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
            qr.add_data(vless_url_result)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")

            img_byte_arr = io.BytesIO()
            qr_img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return vless_url_result, img_byte_arr.getvalue()

        vless_url, qr_data = await asyncio.to_thread(generate_vless_and_qr, json_data, custom_name)

        photo = BufferedInputFile(qr_data, filename="vless_qr.png")
        caption = f"🔗 <b>VLESS ссылка для «{escape_html(custom_name)}»</b>:\n\nКод:\n<code>{escape_html(vless_url)}</code>"

        sent_message = await message.answer_photo(photo=photo, caption=caption, parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

    except ValueError as ve:
        logging.error(f"Ошибка при конвертации JSON в VLESS: {ve}")
        error_caption = f"⚠️ Ошибка при генерации VLESS ссылки: {escape_html(str(ve))}"
        sent_message = await message.answer(error_caption, parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при генерации QR-кода или отправке фото VLESS: {e}")
        try:
             vless_url_fallback = convert_json_to_vless(json_data, custom_name)
             if vless_url_fallback.startswith("⚠️"): raise ValueError(vless_url_fallback)

             fallback_caption = f"🔗 <b>VLESS ссылка для «{escape_html(custom_name)}»</b>:\n\nКод:\n<code>{escape_html(vless_url_fallback)}</code>\n\n⚠️ Ошибка при генерации QR-кода: {escape_html(str(e))}"
             sent_message = await message.answer(fallback_caption, parse_mode="HTML")
        except Exception as fallback_e:
             logging.error(f"Fallback VLESS URL generation failed: {fallback_e}")
             sent_message = await message.answer(f"⚠️ Критическая ошибка при генерации VLESS: {escape_html(str(fallback_e))}")

        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

# --- Background Tasks ---
async def traffic_monitor():
    await asyncio.sleep(TRAFFIC_INTERVAL)
    while True:
        current_users = list(TRAFFIC_MESSAGE_IDS.keys())
        if not current_users:
            await asyncio.sleep(TRAFFIC_INTERVAL)
            continue

        for user_id in current_users:
            if user_id not in TRAFFIC_MESSAGE_IDS:
                continue

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
                if "message is not modified" in str(e):
                    pass
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


async def resource_monitor():
    global RESOURCE_ALERT_STATE
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

            if cpu_usage >= CPU_THRESHOLD and not RESOURCE_ALERT_STATE["cpu"]:
                alerts_to_send.append(f"⚠️ <b>Превышен порог CPU!</b>\nТекущее использование: <b>{cpu_usage:.1f}%</b> (Порог: {CPU_THRESHOLD}%)")
                RESOURCE_ALERT_STATE["cpu"] = True
            elif cpu_usage < CPU_THRESHOLD and RESOURCE_ALERT_STATE["cpu"]:
                 alerts_to_send.append(f"✅ <b>Нагрузка CPU нормализовалась.</b>\nТекущее использование: <b>{cpu_usage:.1f}%</b>")
                 RESOURCE_ALERT_STATE["cpu"] = False

            if ram_usage >= RAM_THRESHOLD and not RESOURCE_ALERT_STATE["ram"]:
                alerts_to_send.append(f"⚠️ <b>Превышен порог RAM!</b>\nТекущее использование: <b>{ram_usage:.1f}%</b> (Порог: {RAM_THRESHOLD}%)")
                RESOURCE_ALERT_STATE["ram"] = True
            elif ram_usage < RAM_THRESHOLD and RESOURCE_ALERT_STATE["ram"]:
                 alerts_to_send.append(f"✅ <b>Использование RAM нормализовалось.</b>\nТекущее использование: <b>{ram_usage:.1f}%</b>")
                 RESOURCE_ALERT_STATE["ram"] = False

            if disk_usage >= DISK_THRESHOLD and not RESOURCE_ALERT_STATE["disk"]:
                alerts_to_send.append(f"⚠️ <b>Превышен порог Disk!</b>\nТекущее использование: <b>{disk_usage:.1f}%</b> (Порог: {DISK_THRESHOLD}%)")
                RESOURCE_ALERT_STATE["disk"] = True
            elif disk_usage < DISK_THRESHOLD and RESOURCE_ALERT_STATE["disk"]:
                 alerts_to_send.append(f"✅ <b>Использование Disk нормализовалось.</b>\nТекущее использование: <b>{disk_usage:.1f}%</b>")
                 RESOURCE_ALERT_STATE["disk"] = False

            if alerts_to_send:
                full_alert_message = "\n\n".join(alerts_to_send)
                await send_alert(full_alert_message, "resources")

        except Exception as e:
            logging.error(f"Ошибка в мониторе ресурсов: {e}")

        await asyncio.sleep(RESOURCE_CHECK_INTERVAL)


# --- Startup and Shutdown ---
async def initial_restart_check():
    if os.path.exists(RESTART_FLAG_FILE):
        try:
            with open(RESTART_FLAG_FILE, "r") as f:
                content = f.read().strip()
                chat_id, message_id = map(int, content.split(':'))
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="✅ Бот успешно перезапущен.")
            logging.info(f"Изменено сообщение о перезапуске в чате ID: {chat_id}")
        except FileNotFoundError:
             logging.info("Restart flag file not found on startup.")
        except ValueError:
             logging.error("Invalid content in restart flag file.")
        except TelegramBadRequest as e:
             logging.warning(f"Failed to edit restart message (likely deleted or invalid): {e}")
        except Exception as e:
            logging.error(f"Ошибка при обработке флага перезапуска: {e}")
        finally:
            try:
                os.remove(RESTART_FLAG_FILE)
            except OSError as e:
                 if e.errno != 2:
                     logging.error(f"Error removing restart flag file: {e}")


async def initial_reboot_check():
    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                user_id_str = f.read().strip()
                if not user_id_str.isdigit():
                     raise ValueError("Invalid content in reboot flag file.")
                user_id = int(user_id_str)

            await bot.send_message(chat_id=user_id, text="✅ <b>Сервер успешно перезагружен! Бот снова в сети.</b>", parse_mode="HTML")
            logging.info(f"Отправлено уведомление о перезагрузке пользователю ID: {user_id}")

        except FileNotFoundError:
             logging.info("Reboot flag file not found on startup.")
        except ValueError as ve:
             logging.error(f"Error processing reboot flag file content: {ve}")
        except TelegramBadRequest as e:
             logging.warning(f"Failed to send reboot notification to user {user_id_str}: {e}")
        except Exception as e:
            logging.error(f"Ошибка при обработке флага перезагрузки: {e}")
        finally:
             try:
                 os.remove(REBOOT_FLAG_FILE)
             except OSError as e:
                  if e.errno != 2:
                      logging.error(f"Error removing reboot flag file: {e}")


async def main():
    try:
        logging.info(f"Бот запускается в режиме: {INSTALL_MODE.upper()}")
        await asyncio.to_thread(load_users)
        load_alerts_config() # Make sure alert config is loaded
        await refresh_user_names()
        await initial_reboot_check()
        await initial_restart_check()
        asyncio.create_task(traffic_monitor())
        asyncio.create_task(resource_monitor()) # Start resource monitor
        logging.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logging.critical(f"Критическая ошибка запуска бота: {e}", exc_info=True)
    finally:
        logging.info("Bot shutdown.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")
    except Exception as e:
        logging.critical(f"Непредвиденное завершение: {e}", exc_info=True)