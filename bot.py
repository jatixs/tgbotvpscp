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

LOG_FILE = os.path.join(LOG_DIR, "bot.log")
logging.basicConfig(level=logging.INFO, filename=LOG_FILE, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

TRAFFIC_INTERVAL = 5
ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}

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
        os.chmod(USERS_FILE, 0o664)
        logging.info(f"Успешно сохранено users.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}")

def is_allowed(user_id, command=None):
    if user_id not in ALLOWED_USERS:
        return False

    user_commands = ["start", "menu", "back_to_menu", "uptime", "traffic", "selftest", "get_id", "get_id_inline"]
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

    if command and any(cmd in command for cmd in ["delete_user", "set_group", "change_group", "xray_install"]):
        return True

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
        [KeyboardButton(text="⏱ Аптайм"), KeyboardButton(text="🆔 Мой ID")]
    ]

    if is_admin:
        if INSTALL_MODE == 'secure':
            buttons = [
                [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                [KeyboardButton(text="🚀 Скорость сети"), KeyboardButton(text="🔥 Топ процессов")],
                [KeyboardButton(text="🩻 Обновление X-ray")],
            ] + buttons
        elif INSTALL_MODE == 'root':
            buttons = [
                [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                [KeyboardButton(text="🛠 Сведения о сервере"), KeyboardButton(text="📡 Трафик сети")],
                [KeyboardButton(text="🔥 Топ процессов"), KeyboardButton(text="📜 SSH-лог")],
                [KeyboardButton(text="🔒 Fail2Ban Log"), KeyboardButton(text="📜 Последние события")],
                [KeyboardButton(text="🚀 Скорость сети"), KeyboardButton(text="⏱ Аптайм")],
                [KeyboardButton(text="🔄 Обновление VPS"), KeyboardButton(text="🩻 Обновление X-ray")],
                [KeyboardButton(text="🔄 Перезагрузка сервера"), KeyboardButton(text="♻️ Перезапуск бота")]
            ]

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
    await delete_previous_message(user_id, ["start", "menu", "manage_users", "reboot_confirm", "generate_vless", "adduser"], chat_id)
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
    if user_id not in ALLOWED_USERS:
        await send_access_denied_message(user_id, message.chat.id, command)
        return
    await delete_previous_message(user_id, command, message.chat.id)
    group = ALLOWED_USERS.get(user_id, 'не авторизован')
    sent_message = await message.answer(f"🆔 Ваш ID: <code>{user_id}</code>\nГруппа: <b>{group}</b>", parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    command = callback.data
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    permission_check_command = command
    if command.startswith(("delete_user_", "set_group_", "select_user_change_group_", "request_self_delete_", "confirm_self_delete_", "back_to_delete_users", "xray_install_")):
       permission_check_command = "manage_users"

    if command not in ["back_to_menu", "back_generate_vless", "back_to_manage_users"] and not is_allowed(user_id, permission_check_command):
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
        elif command == "back_to_manage_users":
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
        elif command == "back_generate_vless":
            await state.clear()
            await callback.message.delete()
        elif command == "back_to_menu":
           await callback.message.delete()
           sent_message = await bot.send_message(chat_id=chat_id, text="📋 Главное меню:", reply_markup=get_main_reply_keyboard(user_id))
           LAST_MESSAGE_IDS.setdefault(user_id, {})["menu"] = sent_message.message_id
    except TelegramRetryAfter as e:
        logging.error(f"TelegramRetryAfter в callback_handler: {e.retry_after} секунд")
        await callback.message.answer(f"⚠️ Telegram ограничивает запросы. Повторите через {e.retry_after} секунд.")
    except TelegramBadRequest as e:
         if "message to edit not found" in str(e) or "message can't be edited" in str(e):
             logging.warning(f"Message edit failed in callback_handler (likely deleted): {e}")
         else:
             logging.warning(f"TelegramBadRequest в callback_handler: {e}")
    except Exception as e:
        logging.error(f"Ошибка в callback_handler: {e}")
        try:
            await bot.send_message(chat_id, f"⚠️ Ошибка при выполнении команды: {str(e)}")
        except Exception as send_e:
            logging.error(f"Failed to send error message: {send_e}")


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


@dp.message(Command("uptime"))
@dp.message(F.text == "⏱ Аптайм")
async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "uptime"
    if user_id not in ALLOWED_USERS:
        if isinstance(message.text, str) and message.text == "⏱ Аптайм":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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

@dp.message(Command("update"))
@dp.message(F.text == "🔄 Обновление VPS")
async def update_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "update"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "🔄 Обновление VPS":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


@dp.message(Command("restart"))
@dp.message(F.text == "♻️ Перезапуск бота")
async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "restart"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "♻️ Перезапуск бота":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


async def reboot_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    command = "reboot"
    if is_allowed(user_id, command):
        try:
            await bot.edit_message_text("✅ Подтверждено. <b>Запускаю перезагрузку VPS</b>...", chat_id=chat_id, message_id=message_id, parse_mode="HTML")
        except TelegramBadRequest:
            pass
        try:
            with open(REBOOT_FLAG_FILE, "w") as f:
                f.write(str(user_id))
        except Exception as e:
            logging.error(f"Не удалось записать флаг перезагрузки: {e}")
        reboot_cmd = "sudo reboot"
        process = await asyncio.create_subprocess_shell(reboot_cmd)
        await process.wait()
        logging.info("Reboot command sent.")
    else:
        await bot.edit_message_text("⛔ Отказано. Только администраторы могут перезагрузить сервер.", chat_id=chat_id, message_id=message_id)


async def detect_xray_client():
    clients = {
        "marzban": "marzban",
        "amnezia": "amnezia-xray"
    }
    for client_name, container_filter in clients.items():
        cmd = f"docker ps -a --filter name={container_filter} --format '{{{{.Names}}}}' | head -n 1"
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await process.communicate()
        container_name = stdout.decode().strip()
        if container_name:
            logging.info(f"Обнаружен клиент Xray: {client_name} (контейнер: {container_name})")
            return client_name, container_name
    logging.info("Поддерживаемый клиент Xray не обнаружен.")
    return None, None

@dp.message(Command("updatexray"))
@dp.message(F.text == "🩻 Обновление X-ray")
async def updatexray_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "updatexray"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "🩻 Обновление X-ray":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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

        await bot.edit_message_text(f"✅ Обнаружен: <b>{client_name_display}</b>. Начинаю обновление...", chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

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


@dp.message(Command("traffic"))
@dp.message(F.text == "📡 Трафик сети")
async def traffic_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "traffic"
    if user_id not in ALLOWED_USERS:
        if isinstance(message.text, str) and message.text == "📡 Трафик сети":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
            await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, command, chat_id)

    def get_initial_counters():
        return psutil.net_io_counters()

    try:
        counters = await asyncio.to_thread(get_initial_counters)
        TRAFFIC_PREV[user_id] = (counters.bytes_recv, counters.bytes_sent)
        msg_text = ("📡 <b>Мониторинг трафика включен</b>...\n\n<i>Обновление каждые 5 секунд. Чтобы остановить, выберите любую другую команду.</i>")
        sent_message = await message.answer(msg_text, parse_mode="HTML")
        TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Error starting traffic monitor for {user_id}: {e}")
        await message.answer(f"⚠️ Не удалось запустить мониторинг трафика: {e}")


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


@dp.message(Command("selftest"))
@dp.message(F.text == "🛠 Сведения о сервере")
async def selftest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "selftest"

    if user_id not in ALLOWED_USERS:
        if isinstance(message.text, str) and message.text == "🛠 Сведения о сервере":
            await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


@dp.message(Command("speedtest"))
@dp.message(F.text == "🚀 Скорость сети")
async def speedtest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "speedtest"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "🚀 Скорость сети":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


@dp.message(Command("top"))
@dp.message(F.text == "🔥 Топ процессов")
async def top_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "top"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "🔥 Топ процессов":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


@dp.message(Command("logs"))
@dp.message(F.text == "📜 Последние события")
async def logs_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "logs"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "📜 Последние события":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


@dp.message(Command("fall2ban"))
@dp.message(F.text == "🔒 Fail2Ban Log")
async def fall2ban_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "fall2ban"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "🔒 Fail2Ban Log":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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


@dp.message(Command("sshlog"))
@dp.message(F.text == "📜 SSH-лог")
async def sshlog_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "sshlog"
    if not is_allowed(user_id, command):
        if isinstance(message.text, str) and message.text == "📜 SSH-лог":
             await message.answer("⛔ У вас нет прав для выполнения этой команды.")
        else:
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
        await refresh_user_names()
        await initial_reboot_check()
        await initial_restart_check()
        asyncio.create_task(traffic_monitor())
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