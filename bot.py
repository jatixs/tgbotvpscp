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

# --- КОНФИГУРАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
# Используем переменные окружения для универсальности и безопасности
TOKEN = os.environ.get("TG_BOT_TOKEN")
INSTALL_MODE = os.environ.get("INSTALL_MODE", "secure") # 'root' or 'secure'. Default to secure.

try:
    ADMIN_USER_ID = int(os.environ.get("TG_ADMIN_ID"))
except (ValueError, TypeError):
    # Если переменная не установлена или некорректна, выходим.
    print("Ошибка: Переменная окружения TG_ADMIN_ID должна быть установлена и быть числом.")
    sys.exit(1)

if not TOKEN:
    print("Ошибка: Переменная окружения TG_BOT_TOKEN не установлена.")
    sys.exit(1)

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ И НАСТРОЙКИ ---
# Пути к файлам теперь относительно директории бота
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# Убедимся, что файл пользователей будет в папке config
USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
REBOOT_FLAG_FILE = os.path.join(CONFIG_DIR, "reboot_flag.txt")

# Логгирование
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
logging.basicConfig(level=logging.INFO, filename=LOG_FILE, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
# Консольный логгер для отладки
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(console_handler)

# Прочие настройки
TRAFFIC_INTERVAL = 5
ALLOWED_USERS = {}
USER_NAMES = {}
TRAFFIC_PREV = {}
LAST_MESSAGE_IDS = {}
TRAFFIC_MESSAGE_IDS = {}

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- FSM СОСТОЯНИЯ ---
class GenerateVlessStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_name = State()

class ManageUsersStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()
    waiting_for_change_group = State()

class UpdateXrayStates(StatesGroup):
    waiting_for_version_choice = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_country_flag(ip: str) -> str:
    """
    Получает флаг страны по IP-адресу, используя внешний API.
    """
    if not ip or ip in ["localhost", "127.0.0.1", "::1"]:
        return "🏠"
    try:
        # Улучшенная обработка таймаута
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=2)
        if response.status_code == 200:
            data = response.json()
            country_code = data.get("countryCode")
            if country_code:
                # Преобразование кода страны в эмодзи-флаг
                flag = "".join(chr(ord(char) + 127397) for char in country_code.upper())
                return flag
    except requests.exceptions.RequestException as e:
        logging.warning(f"Ошибка при получении флага для IP {ip}: {e}")
        return "❓"
    return "🌍"

def escape_html(text):
    """Экранирование символов для HTML разметки в Telegram."""
    if text is None:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def load_users():
    """Загружает список разрешенных пользователей и их имена."""
    global ALLOWED_USERS, USER_NAMES
    try:
        # Убедимся, что папка config существует
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                # Конвертируем ID в int для ALLOWED_USERS
                ALLOWED_USERS = {int(user["id"]): user["group"] for user in data.get("allowed_users", [])}
                USER_NAMES = data.get("user_names", {})

        # Гарантируем, что ADMIN_USER_ID всегда присутствует
        if ADMIN_USER_ID not in ALLOWED_USERS:
            ALLOWED_USERS[ADMIN_USER_ID] = "Админы"
            USER_NAMES[str(ADMIN_USER_ID)] = "Главный Админ"
            save_users() # Сохраняем, если добавили админа

        logging.info(f"Пользователи загружены. Разрешено ID: {list(ALLOWED_USERS.keys())}")
    except Exception as e:
        logging.error(f"Критическая ошибка загрузки users.json: {e}")
        # Если загрузка не удалась, оставляем только админа
        ALLOWED_USERS = {ADMIN_USER_ID: "Админы"}
        USER_NAMES = {str(ADMIN_USER_ID): "Главный Админ"}
        save_users() # Пересоздаем файл с минимальными данными

def save_users():
    """Сохраняет список разрешенных пользователей."""
    try:
        user_names_to_save = {str(k): v for k, v in USER_NAMES.items()}
        data = {
            "allowed_users": [{"id": uid, "group": group} for uid, group in ALLOWED_USERS.items()],
            "user_names": user_names_to_save
        }
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        # Устанавливаем права 664, чтобы бот мог читать/писать
        os.chmod(USERS_FILE, 0o664)
        logging.info(f"Успешно сохранено users.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения users.json: {e}")

def is_allowed(user_id, command=None):
    """Проверяет, разрешен ли пользователь и имеет ли он доступ к команде."""
    if user_id not in ALLOWED_USERS:
        return False

    # Команды, доступные ВСЕМ авторизованным пользователям
    user_commands = ["start", "menu", "back_to_menu", "uptime", "traffic", "selftest", "get_id", "get_id_inline"]
    if command in user_commands:
        return True

    # Является ли пользователь админом?
    is_admin_group = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    if not is_admin_group:
        return False # Если не админ и команда не из общего списка, то доступ запрещен

    # Команды, требующие ТОЛЬКО прав админа (безопасны в secure режиме)
    admin_only_commands = [
        "manage_users", "generate_vless", "speedtest", "top", "updatexray", "adduser"
    ]
    if command in admin_only_commands:
        return True # Доступ разрешен для админов в любом режиме

    # Команды, требующие ROOT (опасные, только в root режиме)
    root_only_commands = [
        "reboot_confirm", "reboot", "fall2ban", "sshlog", "logs", "restart", "update"
    ]
    if command in root_only_commands:
        return INSTALL_MODE == "root" # Разрешаем только если админ и режим 'root'

    # Для колбэков, связанных с управлением пользователями
    if command and any(cmd in command for cmd in ["delete_user", "set_group", "change_group", "xray_install"]):
        return True

    return False # Запрещаем все остальное по умолчанию

async def refresh_user_names():
    """Обновляет имена пользователей, используя API Telegram."""
    needs_save = False
    for uid in list(ALLOWED_USERS.keys()):
        # Обновляем только тех, у кого нет имени или стоит заглушка "Главный Админ"
        if str(uid) not in USER_NAMES or USER_NAMES.get(str(uid)) == "Главный Админ":
            try:
                chat = await bot.get_chat(uid)
                new_name = chat.first_name or chat.username or f"Пользователь_{uid}"
                if USER_NAMES.get(str(uid)) != new_name:
                    USER_NAMES[str(uid)] = new_name
                    needs_save = True
            except Exception as e:
                logging.warning(f"Не удалось обновить имя для {uid}: {e}")
                USER_NAMES[str(uid)] = f"ID: {uid}" # Установим ID как заглушку

    if needs_save:
        save_users()

async def get_user_name(user_id):
    """Получает имя пользователя по ID, используя API Telegram."""
    try:
        # Сначала проверим в кэше
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
    """Отправляет сообщение об отказе в доступе."""
    await delete_previous_message(user_id, command, chat_id)
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        admin_link = f"https://t.me/{bot_username}?start={user_id}"
    except Exception:
        admin_link = f"https://t.me/user?id={ADMIN_USER_ID}&text=Мой ID для доступа: {user_id}"


    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить свой ID администратору", url=admin_link)]
    ])
    sent_message = await bot.send_message(
        chat_id,
        f"⛔ Вы не являетесь пользователем бота. Ваш ID: **`{user_id}`**.\n"
        "К командам нет доступа, обратитесь к администратору.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

def get_main_reply_keyboard(user_id):
    """Создает основное меню в зависимости от прав пользователя и режима установки."""
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"

    # Меню для обычного пользователя (минимальный набор)
    buttons = [
        [KeyboardButton(text="🛠 Сведения о сервере"), KeyboardButton(text="📡 Трафик сети")],
        [KeyboardButton(text="⏱ Аптайм"), KeyboardButton(text="🆔 Мой ID")]
    ]

    if is_admin:
        # Меню для Админа в режиме SECURE (расширенный безопасный набор)
        if INSTALL_MODE == 'secure':
            buttons = [
                [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
                [KeyboardButton(text="🚀 Скорость сети"), KeyboardButton(text="🔥 Топ процессов")],
                [KeyboardButton(text="🩻 Обновление X-ray")],
            ] + buttons # Добавляем базовые кнопки в конец
        # Меню для Админа в режиме ROOT (полный доступ)
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
    """Меню управления пользователями."""
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
    """Клавиатура для выбора пользователя для удаления."""
    buttons = []
    # Сортировка для удобства
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
    """Клавиатура для выбора пользователя для изменения группы."""
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
    """Клавиатура для выбора группы (Админы/Пользователи)."""
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
    """Подтверждение самоудаления."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_self_delete_{user_id}"),
            InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_delete_users")
        ]
    ])
    return keyboard

def get_reboot_confirmation_keyboard():
    """Подтверждение перезагрузки сервера."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, перезагрузить", callback_data="reboot"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_menu")
        ]
    ])
    return keyboard

def get_back_keyboard(callback_data="back_to_manage_users"):
    """Кнопка 'Назад' для FSM-состояний."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)
        ]
    ])
    return keyboard

def convert_json_to_vless(json_data, custom_name):
    """Конвертирует JSON-конфигурацию Xray в VLESS-ссылку с Reality."""
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
    """Форматирует байты в МБ, ГБ, ТБ, ПБ."""
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"]
    value = float(bytes_value)
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    return f"{value:.2f} {units[unit_index]}"

def format_uptime(seconds):
    """Форматирует время работы (аптайм) в удобный вид."""
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
    if seconds < 60 or not parts: # Для короткого аптайма всегда показываем секунды
         parts.append(f"{secs}с")

    return " ".join(parts) if parts else "0с"

async def delete_previous_message(user_id: int, command, chat_id: int):
    """Удаляет предыдущее сообщение, связанное с командой, чтобы не засорять чат."""
    # Прекращаем мониторинг трафика, если переключаемся на другую команду
    if command != "traffic" and user_id in TRAFFIC_MESSAGE_IDS:
        del TRAFFIC_MESSAGE_IDS[user_id]

    cmds_to_delete = [command] if not isinstance(command, list) else command

    for cmd in cmds_to_delete:
        try:
            if user_id in LAST_MESSAGE_IDS and cmd in LAST_MESSAGE_IDS[user_id]:
                msg_id = LAST_MESSAGE_IDS[user_id].pop(cmd)
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest as e:
            # Игнорируем ошибки "message to delete not found"
            if "message to delete not found" not in str(e):
                 logging.error(f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")
        except Exception as e:
            logging.error(f"Ошибка при удалении предыдущего сообщения для {user_id}/{cmd}: {e}")


# --- START AND MENU HANDLERS ---
@dp.message(Command("start", "menu"))
@dp.message(F.text == "🔙 Назад в меню")
async def start_or_menu_handler(message: types.Message, state: FSMContext):
    """Обработчик команд /start и /menu и кнопки "Назад в меню"."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "start" if message.text == "/start" else "menu"

    await state.clear() # Сброс состояния FSM при входе в меню

    if user_id not in ALLOWED_USERS:
        await send_access_denied_message(user_id, chat_id, command)
        return

    await delete_previous_message(user_id, ["start", "menu", "manage_users", "reboot_confirm", "generate_vless", "adduser"], chat_id)

    # Обновляем имя пользователя при первом входе
    if str(user_id) not in USER_NAMES:
         await refresh_user_names()

    sent_message = await message.answer(
        "👋 Привет! Выбери команду на клавиатуре ниже. Чтобы вызвать меню снова, используй /menu.",
        reply_markup=get_main_reply_keyboard(user_id)
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

# --- TEXT-BASED MENU HANDLERS ---

@dp.message(F.text == "👤 Пользователи")
async def manage_users_handler(message: types.Message):
    user_id = message.from_user.id
    command = "manage_users"
    if not is_allowed(user_id, command):
        # Это сообщение не должно появляться, так как кнопка скрыта, но оставляем для безопасности
        await bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    await delete_previous_message(user_id, command, message.chat.id)

    # Показываем список текущих пользователей для удобства
    user_list = "\n".join([
        f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (**{group}**)"
        for uid, group in ALLOWED_USERS.items()
    ])

    sent_message = await message.answer(
        f"👤 **Управление пользователями**:\n\n{user_list}\n\nВыберите действие:",
        reply_markup=get_manage_users_keyboard(),
        parse_mode="Markdown"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

# --- HANDLERS FOR ADMIN COMMANDS (TEXT BUTTONS) ---
@dp.message(F.text == "🔄 Перезагрузка сервера")
async def reboot_confirm_handler(message: types.Message):
    user_id = message.from_user.id
    command = "reboot_confirm"
    if not is_allowed(user_id, command):
        await bot.send_message(message.chat.id, "⛔ Эта функция доступна только в режиме 'root'.")
        return
    await delete_previous_message(user_id, command, message.chat.id)
    sent_message = await message.answer("⚠️ Вы уверены, что хотите **перезагрузить сервер**? Все активные соединения будут разорваны.", reply_markup=get_reboot_confirmation_keyboard(), parse_mode="Markdown")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(F.text == "🔗 VLESS-ссылка")
async def generate_vless_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    await delete_previous_message(user_id, command, message.chat.id)
    sent_message = await message.answer("📤 **Отправьте файл конфигурации Xray (JSON)**\n\n_Важно: файл должен содержать рабочую конфигурацию outbound с Reality._", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="Markdown")
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
    sent_message = await message.answer(f"🆔 Ваш ID: **`{user_id}`**\nГруппа: **{group}**", parse_mode="Markdown")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


# --- CALLBACK (INLINE BUTTONS) HANDLER ---
@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    command = callback.data
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id

    # Проверка разрешений
    permission_check_command = command
    if command.startswith(("delete_user_", "set_group_", "select_user_change_group_", "request_self_delete_", "confirm_self_delete_", "back_to_delete_users", "xray_install_")):
         permission_check_command = "manage_users"

    # Для базовых команд, типа "назад в меню", проверка не нужна, если пользователь уже авторизован
    if command not in ["back_to_menu", "back_generate_vless", "back_to_manage_users"] and not is_allowed(user_id, permission_check_command):
        if user_id not in ALLOWED_USERS:
            await send_access_denied_message(user_id, chat_id, command)
        else:
            await callback.message.answer(f"⛔ Команда '{command}' недоступна для вашей группы ({ALLOWED_USERS[user_id]}) или в текущем режиме установки.")
        return

    try:
        # --- User Management Callbacks ---
        if command == "add_user":
            await delete_previous_message(user_id, "manage_users", chat_id)
            sent_message = await callback.message.answer("📝 Введите ID или Alias пользователя (например, `@username`):", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")
            LAST_MESSAGE_IDS.setdefault(user_id, {})["add_user"] = sent_message.message_id
            await state.set_state(ManageUsersStates.waiting_for_user_id)

        elif command == "delete_user":
            await callback.message.edit_text("➖ Выберите пользователя для удаления:", reply_markup=get_delete_users_keyboard(user_id))

        elif command == "change_group":
            await callback.message.edit_text("🔄 Выберите пользователя для изменения группы:", reply_markup=get_change_group_keyboard())

        elif command.startswith("select_user_change_group_"):
            target_user_id = int(command.split("_")[4])
            if target_user_id not in ALLOWED_USERS:
                await callback.message.edit_text(f"⚠️ Пользователь ID **`{target_user_id}`** не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")
            else:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                await callback.message.edit_text(f"👤 Пользователь: **{user_name}**\nТекущая группа: **{ALLOWED_USERS[target_user_id]}**\nВыберите новую группу:", reply_markup=get_group_selection_keyboard(target_user_id), parse_mode="Markdown")

        elif command.startswith("set_group_"):
            parts = command.split("_")
            target_user_id = int(parts[2])
            new_group = parts[3]
            if target_user_id == ADMIN_USER_ID:
                await callback.message.edit_text("⚠️ Нельзя изменить группу главного администратора", reply_markup=get_back_keyboard("back_to_manage_users"))
            elif target_user_id not in ALLOWED_USERS:
                await callback.message.edit_text(f"⚠️ Пользователь ID **`{target_user_id}`** не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")
            else:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                ALLOWED_USERS[target_user_id] = new_group
                save_users()
                await callback.message.edit_text(f"✅ Группа пользователя **{user_name}** изменена на **{new_group}**", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")
                if INSTALL_MODE == "root":
                    os.system(f"sudo systemctl restart tg-bot.service")
                else:
                    # В secure режиме просто уведомляем, что нужен рестарт
                    await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")

        elif command == "back_to_manage_users":
            # Собираем актуальный список пользователей
            user_list = "\n".join([
                f" • {USER_NAMES.get(str(uid), f'ID: {uid}')} (**{group}**)"
                for uid, group in ALLOWED_USERS.items()
            ])
            # Редактируем текущее сообщение, чтобы оно стало главным меню управления
            await callback.message.edit_text(
                f"👤 **Управление пользователями**:\n\n{user_list}\n\nВыберите действие:",
                reply_markup=get_manage_users_keyboard(),
                parse_mode="Markdown"
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
                    await callback.message.edit_text(f"✅ Пользователь **{user_name}** удалён. Вы потеряли доступ к боту.", parse_mode="Markdown")
                    if INSTALL_MODE == "root":
                        os.system(f"sudo systemctl restart tg-bot.service")
                    else:
                        # В secure режиме просто уведомляем, что нужен рестарт
                        await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")
                else:
                    await callback.message.edit_text(f"⚠️ Пользователь ID **`{target_user_id}`** уже был удален.", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")

        elif command.startswith("delete_user_"):
            target_user_id = int(command.split("_")[2])
            if target_user_id == ADMIN_USER_ID:
                await callback.message.edit_text("⚠️ Нельзя удалить главного администратора", reply_markup=get_back_keyboard("back_to_manage_users"))
            elif target_user_id in ALLOWED_USERS:
                user_name = USER_NAMES.get(str(target_user_id), f"ID: {target_user_id}")
                del ALLOWED_USERS[target_user_id]
                USER_NAMES.pop(str(target_user_id), None)
                save_users()
                await callback.message.edit_text(f"✅ Пользователь **{user_name}** удалён", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")
                if INSTALL_MODE == "root":
                    os.system(f"sudo systemctl restart tg-bot.service")
                else:
                    # В secure режиме просто уведомляем, что нужен рестарт
                    await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")
            else:
                await callback.message.edit_text(f"⚠️ Пользователь ID **`{target_user_id}`** не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")

        elif command == "get_id_inline":
             await callback.message.answer(f"🆔 Ваш ID: {user_id}\nГруппа: {ALLOWED_USERS.get(user_id, 'не авторизован')}")

        # --- Other Callbacks ---
        elif command == "reboot":
             await reboot_handler(callback)

        elif command == "back_generate_vless":
            await state.clear()
            await callback.message.delete()

        elif command == "back_to_menu":
             await callback.message.delete()
             sent_message = await bot.send_message(
                 chat_id=chat_id,
                 text="📋 Главное меню:",
                 reply_markup=get_main_reply_keyboard(user_id)
             )
             LAST_MESSAGE_IDS.setdefault(user_id, {})["menu"] = sent_message.message_id

        else:
            # Для неизвестных или не требующих действия колбэков
            pass

    except TelegramRetryAfter as e:
        logging.error(f"TelegramRetryAfter в callback_handler: {e.retry_after} секунд")
        await callback.message.answer(f"⚠️ Telegram ограничивает запросы. Повторите через {e.retry_after} секунд.")
    except TelegramBadRequest as e:
        # Часто возникает, когда пытаемся изменить уже удаленное сообщение
        logging.warning(f"TelegramBadRequest в callback_handler: {e}")
    except Exception as e:
        logging.error(f"Ошибка в callback_handler: {e}")
        # Отправляем новое сообщение, если редактирование старого не удалось
        await bot.send_message(chat_id, f"⚠️ Ошибка при выполнении команды: {str(e)}")


@dp.message(Command("adduser"))
async def adduser_command_handler(message: types.Message, state: FSMContext):
    """Обработчик команды /adduser."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "adduser"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer(
        "📝 Введите ID или Alias пользователя (например, `@username`):",
        reply_markup=get_back_keyboard("back_to_manage_users"),
        parse_mode="Markdown"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    await state.set_state(ManageUsersStates.waiting_for_user_id)

@dp.message(StateFilter(ManageUsersStates.waiting_for_user_id))
async def handle_user_id(message: types.Message, state: FSMContext):
    """Обработка введенного ID или Alias для добавления."""
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
        # Проверка на Alias (@username)
        if input_text.startswith("@"):
            if not re.match(r'^@[\w_]{5,}$', input_text):
                raise ValueError("Неверный формат никнейма.")

            chat = await bot.get_chat(input_text)
            target_user_id = chat.id
            user_name = chat.first_name or chat.username or f"Неизвестный_{target_user_id}"
        # Проверка на User ID (число)
        else:
            try:
                target_user_id = int(input_text)
                user_name = await get_user_name(target_user_id)
            except ValueError:
                raise ValueError("Введите корректный ID (число) или Alias (@username).")

        if target_user_id in ALLOWED_USERS:
            await state.clear()
            await delete_previous_message(user_id, command, chat_id)
            sent_message = await message.answer(
                f"⚠️ Пользователь **{user_name}** (ID: **`{target_user_id}`**) уже в списке разрешённых.",
                reply_markup=get_back_keyboard("back_to_manage_users"),
                parse_mode="Markdown"
            )
            LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
            return

        # Временно добавляем пользователя как "Пользователи" и переходим к выбору группы
        ALLOWED_USERS[target_user_id] = "Пользователи"
        USER_NAMES[str(target_user_id)] = user_name
        save_users() # Сохраняем, чтобы пользователь мог получить первое сообщение

        await state.update_data(target_user_id=target_user_id, user_name=user_name)
        await delete_previous_message(user_id, command, chat_id)

        sent_message = await message.answer(
            f"👤 Пользователь: **{user_name}** (ID: **`{target_user_id}`**)\nТекущая группа: **Пользователи**\nВыберите группу:",
            reply_markup=get_group_selection_keyboard(target_user_id),
            parse_mode="Markdown"
        )
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.set_state(ManageUsersStates.waiting_for_group)

    except (TelegramBadRequest, ValueError) as e:
        error_text = str(e)
        if "Bad Request: chat not found" in error_text or "Неверный формат" in error_text:
             error_text = (
                 f"❌ **Не удалось найти пользователя `{input_text}`.**\n\n"
                 "Возможные причины:\n"
                 "1. Пользователь не существует или закрыл личку.\n"
                 "2. Пользователь должен **сначала написать боту команду /start**.\n\n"
                 "💡 **Решение:** Добавляйте по **User ID** (число) или попросите пользователя написать /start."
             )
        else:
            error_text = f"⚠️ Произошла непредвиденная ошибка: {escape_html(str(e))}"

        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(
            error_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard("back_to_manage_users")
        )
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.clear()
    except Exception as e:
        logging.error(f"Непредвиденная ошибка при добавлении пользователя: {e}")
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(
            f"⚠️ Произошла непредвиденная ошибка: {escape_html(str(e))}",
            reply_markup=get_back_keyboard("back_to_manage_users"),
            parse_mode="HTML"
        )
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.clear()


@dp.callback_query(StateFilter(ManageUsersStates.waiting_for_group))
async def handle_group_selection_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора группы через inline-кнопку."""
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    command = "adduser"

    # Разрешение уже проверено в общем callback_handler, но FSM-состояние требует еще одной проверки
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
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
             # Это не должно произойти при нормальном ходе, но на всякий случай
            await callback.message.edit_text("⚠️ Ошибка: Несоответствие ID пользователя.", reply_markup=get_back_keyboard("back_to_manage_users"))
            await state.clear()
            return

        ALLOWED_USERS[target_user_id] = new_group
        save_users()
        await state.clear()

        await callback.message.edit_text(
            f"✅ Пользователь **{user_name}** (ID: **`{target_user_id}`**) добавлен в группу **{new_group}**",
            reply_markup=get_back_keyboard("back_to_manage_users"),
            parse_mode="Markdown"
        )
        if INSTALL_MODE == "root":
            os.system(f"sudo systemctl restart tg-bot.service")
        else:
            # В secure режиме просто уведомляем, что нужен рестарт
            await callback.message.answer("ℹ️ Для полного применения изменений рекомендуется перезапустить бота вручную.")

    elif callback.data == "back_to_manage_users":
        # Пользователь отменил выбор группы, возвращаем его в меню управления
        await state.clear()
        await callback.message.edit_text(
             "👤 Управление пользователями:",
             reply_markup=get_manage_users_keyboard()
        )

# --- ACTION HANDLERS ---

@dp.message(Command("uptime"))
async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "uptime"
    if user_id not in ALLOWED_USERS:
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    try:
        with open("/proc/uptime") as f:
            uptime_sec = float(f.readline().split()[0])
        uptime_str = format_uptime(uptime_sec)
        sent_message = await message.answer(f"⏱ Время работы: **{uptime_str}**", parse_mode="Markdown")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
         logging.error(f"Ошибка в uptime_handler: {e}")
         sent_message = await message.answer(f"⚠️ Ошибка при получении аптайма: {str(e)}")
         LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("update"))
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

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    output = stdout.decode('utf-8', errors='ignore')
    error_output = stderr.decode('utf-8', errors='ignore')

    await delete_previous_message(user_id, command, chat_id)

    if process.returncode == 0:
        response_text = f"✅ Обновление завершено:\n<pre>{escape_html(output[-4000:])}</pre>"
    else:
        response_text = f"❌ Ошибка при обновлении (Код: {process.returncode}):\n<pre>{escape_html(error_output[-4000:])}</pre>"

    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("restart"))
async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "restart"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)

    sent_msg = await message.answer("♻️ Бот ушел перезагружаться…")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id

    try:
        # Эта команда вызовет остановку скрипта, systemd перезапустит его
        os.system(f"sudo systemctl restart tg-bot.service")
    except Exception as e:
        logging.error(f"Ошибка в restart_handler: {e}")
        await bot.edit_message_text(
            text=f"⚠️ Ошибка при попытке перезапуска сервиса: {str(e)}",
            chat_id=chat_id,
            message_id=sent_msg.message_id
        )

async def reboot_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    command = "reboot"

    if is_allowed(user_id, command):
        try:
            await bot.edit_message_text(
                "✅ Подтверждено. **Запускаю перезагрузку VPS**...",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="Markdown"
            )
        except TelegramBadRequest:
            pass

        try:
            with open(REBOOT_FLAG_FILE, "w") as f:
                f.write(str(user_id))
        except Exception as e:
             logging.error(f"Не удалось записать флаг перезагрузки: {e}")

        os.system("sudo reboot")
    else:
        await bot.edit_message_text(
            "⛔ Отказано. Только администраторы могут перезагрузить сервер.",
            chat_id=chat_id,
            message_id=message_id
        )


# =================================================================================
# === НОВЫЙ УЛУЧШЕННЫЙ БЛОК ОБНОВЛЕНИЯ XRAY ===
# =================================================================================

async def detect_xray_client():
    """
    Определяет установленный Xray клиент и его контейнер.
    Возвращает кортеж (client_name, container_name) или (None, None).
    """
    # Конфигурации для более надежного обнаружения
    client_configs = {
        "marzban": {"image": "gozargah/marzban", "name_filter": "marzban"},
        "amnezia": {"image": None, "name_filter": "amnezia-xray"},
        "3x-ui": {"image": None, "name_filter": "3x-ui"}
    }

    for client_name, config in client_configs.items():
        container_name = None
        # Приоритет 1: Обнаружение по образу Docker (наиболее надежно для Marzban)
        if config["image"]:
            cmd = f"docker ps -a --filter \"ancestor={config['image']}\" --format '{{{{.Names}}}}' | head -n 1"
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            container_name = stdout.decode().strip()
            if container_name:
                logging.info(f"Обнаружен клиент {client_name} по образу Docker. Имя контейнера: {container_name}")
                return client_name, container_name

        # Приоритет 2: Поиск по имени контейнера (для других клиентов)
        cmd = f"docker ps -a --filter name={config['name_filter']} --format '{{{{.Names}}}}' | head -n 1"
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        container_name = stdout.decode().strip()
        if container_name:
            logging.info(f"Обнаружен клиент {client_name} по имени контейнера: {container_name}")
            return client_name, container_name

    logging.info("Поддерживаемый клиент Xray не обнаружен.")
    return None, None


@dp.message(Command("updatexray"))
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
            await bot.edit_message_text(
                "❌ Не удалось определить поддерживаемый клиент Xray (Marzban, Amnezia, 3x-UI). Обновление невозможно.",
                chat_id=chat_id, message_id=sent_msg.message_id
            )
            return

        # --- Логика для Amnezia и 3x-UI (без изменений) ---
        if client in ["amnezia", "3x-ui"]:
            await bot.edit_message_text(
                f"✅ Обнаружен клиент: **{client.upper()}**. Начинаю стандартное обновление Xray...",
                chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="Markdown"
            )
            
            update_cmd, version_cmd = "", ""
            if client == "amnezia":
                update_cmd = (
                    f'docker exec {container_name} /bin/bash -c "'
                    'rm -f Xray-linux-64.zip xray && '
                    'wget -q -O Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip && '
                    'unzip -o Xray-linux-64.zip && '
                    'cp xray /usr/bin/xray && '
                    'rm Xray-linux-64.zip xray" && '
                    f'docker restart {container_name}'
                )
                version_cmd = f"docker exec {container_name} /usr/bin/xray version"
            elif client == "3x-ui":
                update_cmd = "bash <(curl -L https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh) xray"
                version_cmd = "/usr/local/x-ui/xray version"
            
            process_update = await asyncio.create_subprocess_shell(
                update_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout_update, stderr_update = await process_update.communicate()

            if process_update.returncode != 0:
                error_details = stderr_update.decode() or stdout_update.decode()
                raise Exception(f"Команда обновления завершилась с ошибкой:\n<pre>{escape_html(error_details)}</pre>")
            
            process_version = await asyncio.create_subprocess_shell(version_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout_version, _ = await process_version.communicate()
            version_output = stdout_version.decode()
            version_match = re.search(r'Xray\s+([\d\.]+)', version_output)
            version = version_match.group(1) if version_match else "неизвестной версии"
            final_message = (
                f"✅ **Xray для клиента `{client.upper()}` успешно обновлен до версии `{version}`!**\n\n"
                f"📃 **Лог выполнения:**\n<pre>{escape_html(stdout_update.decode()[-1000:])}</pre>"
            )
            await bot.edit_message_text(final_message, chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")

        # --- ИНТЕРАКТИВНАЯ ЛОГИКА ДЛЯ MARZBAN ---
        elif client == "marzban":
            await bot.edit_message_text(
                f"✅ Обнаружен **Marzban** (контейнер: `{container_name}`). Получаю список версий Xray с GitHub...",
                chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="Markdown"
            )
            
            api_url = "https://api.github.com/repos/XTLS/Xray-core/releases?per_page=5"
            response = requests.get(api_url, timeout=10)
            if response.status_code != 200:
                raise Exception("Не удалось получить список версий с GitHub API.")
            
            releases = response.json()
            versions = [release['tag_name'] for release in releases]
            
            buttons = []
            for version in versions:
                buttons.append([InlineKeyboardButton(text=f"🚀 {version}", callback_data=f"xray_install_{version}")])
            buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="xray_install_cancel")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await bot.edit_message_text(
                "👇 **Выберите версию Xray для установки на Marzban:**",
                chat_id=chat_id, message_id=sent_msg.message_id, reply_markup=keyboard, parse_mode="Markdown"
            )
            # Сохраняем имя контейнера в FSM для следующего шага
            await state.update_data(marzban_container_name=container_name)
            await state.set_state(UpdateXrayStates.waiting_for_version_choice)

    except Exception as e:
        logging.error(f"Ошибка в updatexray_handler: {e}")
        await bot.edit_message_text(f"⚠️ **Ошибка:**\n\n{str(e)}", chat_id=chat_id, message_id=sent_msg.message_id, parse_mode="HTML")
        await state.clear()

# --- ОБРАБОТЧИК ДЛЯ ВЫБОРА ВЕРСИИ MARZBAN ---
@dp.callback_query(UpdateXrayStates.waiting_for_version_choice)
async def handle_xray_version_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    
    try:
        if callback.data == "xray_install_cancel":
            await bot.edit_message_text("❌ Обновление отменено.", chat_id=chat_id, message_id=message_id)
            await state.clear()
            return
            
        fsm_data = await state.get_data()
        container_name = fsm_data.get("marzban_container_name")
        if not container_name:
            raise Exception("Не удалось определить имя контейнера Marzban. Процесс прерван.")
        
        await state.clear()

        selected_version = callback.data.split("_")[2]
        await bot.edit_message_text(
            f"⚙️ Выбрана версия **{selected_version}**. Начинаю установку для контейнера `{container_name}`...",
            chat_id=chat_id, message_id=message_id, parse_mode="Markdown"
        )
        
        # Команды извлечены и адаптированы из скрипта change.sh
        # 1. Создание папки, скачивание, распаковка и удаление архива
        download_cmd = (
            f"sudo mkdir -p /var/lib/marzban/xray-core && "
            f"cd /var/lib/marzban/xray-core && "
            f"sudo wget -O Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/download/{selected_version}/Xray-linux-64.zip && "
            f"sudo unzip -o Xray-linux-64.zip && "
            f"sudo rm Xray-linux-64.zip"
        )
        
        # 2. Прописывание пути в .env (идемпотентно - удаляем старую строку и добавляем новую)
        env_file = "/opt/marzban/.env"
        config_cmd = (
            f"sudo sed -i '/^XRAY_EXECUTABLE_PATH=/d' {env_file} && "
            f"echo 'XRAY_EXECUTABLE_PATH=\"/var/lib/marzban/xray-core/xray\"' | sudo tee -a {env_file}"
        )
        
        # 3. Перезапуск Marzban с использованием динамического имени контейнера
        restart_cmd = f"sudo docker restart {container_name}"
        
        full_cmd = f"{download_cmd} && {config_cmd} && {restart_cmd}"
        
        process = await asyncio.create_subprocess_shell(
            full_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_details = stderr.decode() or stdout.decode()
            raise Exception(f"Процесс установки завершился с ошибкой:\n<pre>{escape_html(error_details)}</pre>")
        
        # Проверка версии после установки
        version_cmd = "sudo /var/lib/marzban/xray-core/xray version"
        process_version = await asyncio.create_subprocess_shell(
            version_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_version, _ = await process_version.communicate()
        version_output = stdout_version.decode()
        version_match = re.search(r'Xray\s+([\d\.]+)', version_output)
        final_version = version_match.group(1) if version_match else selected_version

        final_message = f"✅ **Xray для Marzban успешно обновлен до версии `{final_version}`!**"
        await bot.edit_message_text(final_message, chat_id=chat_id, message_id=message_id, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Ошибка при установке Xray для Marzban: {e}")
        error_msg = f"⚠️ **Ошибка при обновлении Xray для Marzban:**\n\n{str(e)}"
        await bot.edit_message_text(error_msg, chat_id=chat_id, message_id=message_id, parse_mode="HTML")
    finally:
        await state.clear()


@dp.message(Command("traffic"))
async def traffic_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "traffic"
    if user_id not in ALLOWED_USERS:
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)

    counters = psutil.net_io_counters()
    TRAFFIC_PREV[user_id] = (counters.bytes_recv, counters.bytes_sent)

    msg_text = ("📡 **Мониторинг трафика включен**...\n\n_Обновление каждые 5 секунд. Чтобы остановить, выберите любую другую команду._")
    sent_message = await message.answer(msg_text, parse_mode="Markdown")

    TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

async def traffic_monitor():
    """Асинхронный цикл для мониторинга и обновления сообщений о трафике."""
    await asyncio.sleep(5)
    while True:
        for user_id in list(TRAFFIC_MESSAGE_IDS.keys()):
            if user_id not in TRAFFIC_MESSAGE_IDS:
                 continue

            try:
                counters = psutil.net_io_counters()
                rx = counters.bytes_recv
                tx = counters.bytes_sent

                prev_rx, prev_tx = TRAFFIC_PREV.get(user_id, (rx, tx))

                rx_speed = (rx - prev_rx) * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                tx_speed = (tx - prev_tx) * 8 / 1024 / 1024 / TRAFFIC_INTERVAL

                TRAFFIC_PREV[user_id] = (rx, tx)

                msg_text = (
                    f"📡 Общий трафик:\n"
                    f"=========================\n"
                    f"⬇️ RX: {format_traffic(rx)}\n"
                    f"⬆️ TX: {format_traffic(tx)}\n\n"
                    f"⚡️ Скорость соединения:\n"
                    f"=========================\n"
                    f"⬇️ RX: {rx_speed:.2f} Мбит/с\n"
                    f"⬆️ TX: {tx_speed:.2f} Мбит/с"
                )

                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=TRAFFIC_MESSAGE_IDS[user_id],
                    text=msg_text
                )
            except TelegramRetryAfter as e:
                logging.warning(f"Ошибка TelegramRetryAfter для {user_id}: Подождите {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                elif user_id in TRAFFIC_MESSAGE_IDS:
                    logging.warning(f"Ошибка TelegramBadRequest (удаление) для {user_id}: {e}")
                    del TRAFFIC_MESSAGE_IDS[user_id]
            except Exception as e:
                logging.error(f"Критическая ошибка обновления авто-трафика для {user_id}: {e}")
                if user_id in TRAFFIC_MESSAGE_IDS:
                    del TRAFFIC_MESSAGE_IDS[user_id]

        await asyncio.sleep(TRAFFIC_INTERVAL)

@dp.message(Command("selftest"))
async def selftest_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "selftest"
    if user_id not in ALLOWED_USERS:
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)

    cpu = psutil.cpu_percent()
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    with open("/proc/uptime") as f:
        uptime_sec = float(f.readline().split()[0])
    uptime_str = format_uptime(uptime_sec)

    ping_result = os.popen("ping -c 1 -W 2 8.8.8.8").read()
    ping_match = re.search(r'time=([\d\.]+) ms', ping_result)
    ping_time = ping_match.group(1) if ping_match else "N/A"
    internet = "✅ Интернет доступен" if ping_match else "❌ Нет интернета"
    external_ip = os.popen("curl -4 -s ifconfig.me").read().strip()

    last_login = "**N/A** (Нет файла логов)"
    if INSTALL_MODE == "root":
        try:
            cmd = "journalctl -u ssh --no-pager -n 100 -g 'Accepted' | tail -n 1"
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            line = stdout.decode().strip()

            if "Accepted" in line:
                date_match = re.search(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line)
                user_match = re.search(r'for (\S+)', line)
                ip_match = re.search(r'from (\S+)', line)

                if date_match and user_match and ip_match:
                    log_timestamp = datetime.strptime(date_match.group(1), '%b %d %H:%M:%S')
                    current_year = datetime.now().year
                    dt_object = log_timestamp.replace(year=current_year)

                    user = user_match.group(1)
                    ip = ip_match.group(1)
                    flag = get_country_flag(ip)

                    if dt_object > datetime.now():
                         dt_object = dt_object.replace(year=current_year - 1)

                    formatted_time = dt_object.strftime('%H:%M')
                    formatted_date = dt_object.strftime('%d.%m.%Y')

                    last_login = (f"👤 **{user}**\n"
                                  f"🌍 IP: **{flag} {ip}**\n"
                                  f"⏰ Время: **{formatted_time}**\n"
                                  f"🗓️ Дата: **{formatted_date}**")
        except Exception as e:
            logging.error(f"Ошибка при получении последнего SSH входа: {e}")
            last_login = f"**N/A** (Ошибка: {str(e)})"

    counters = psutil.net_io_counters()
    rx = counters.bytes_recv
    tx = counters.bytes_sent

    response_text = (
        f"🛠 **Состояние сервера:**\n\n"
        f"✅ Бот работает\n"
        f"📊 Процессор: **{cpu}%**\n"
        f"💾 ОЗУ: **{mem}%**\n"
        f"💽 ПЗУ: **{disk}%**\n"
        f"⏱ Время работы: **{uptime_str}**\n"
        f"{internet}\n"
        f"⌛ Задержка (8.8.8.8): **{ping_time} мс**\n"
        f"🌐 Внешний IP: **`{external_ip}`**\n"
        f"📡 Трафик⬇ **{format_traffic(rx)}** / ⬆ **{format_traffic(tx)}**"
    )

    if INSTALL_MODE == "root":
        response_text += f"\n\n📄 **Последний успешный вход SSH:**\n{last_login}"


    sent_message = await message.answer(response_text, parse_mode="Markdown")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("speedtest"))
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
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    await delete_previous_message(user_id, command, chat_id)
    if process.returncode == 0:
        output = stdout.decode('utf-8', errors='ignore')
        try:
            data = json.loads(output)
            download_speed = data.get("download", {}).get("bandwidth", 0) / 125000
            upload_speed = data.get("upload", {}).get("bandwidth", 0) / 125000
            result_url = data.get("result", {}).get("url", "N/A")

            response_text = (f"🚀 Ваша скорость соединения:\n"
                             f"⬇ Входящая: {download_speed:.2f} Мбит/с\n"
                             f"⬆ Исходящая: {upload_speed:.2f} Мбит/с\n"
                             f"Ссылка на результат:\n{result_url}")
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка парсинга JSON от speedtest: {e}")
            response_text = f"❌ Ошибка при обработке результатов speedtest: <pre>{escape_html(str(e))}</pre>"
    else:
        error_output = stderr.decode('utf-8', errors='ignore')
        response_text = f"❌ Ошибка при запуске speedtest:\n<pre>{escape_html(error_output)}</pre>"

    sent_message = await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=True)
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("top"))
async def top_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "top"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)

    cmd = "ps aux --sort=-%cpu | head -n 15"
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        output = escape_html(stdout.decode())
        response_text = f"🔥 **Топ 14 процессов по загрузке CPU:**\n<pre>{output}</pre>"
    else:
        error_output = escape_html(stderr.decode())
        response_text = f"❌ Ошибка при получении списка процессов:\n<pre>{error_output}</pre>"

    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("logs"))
async def logs_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "logs"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    try:
        cmd = "journalctl -n 20 --no-pager"
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(stderr.decode())

        log_output = escape_html(stdout.decode())
        sent_message = await message.answer(f"📜 **Последние системные журналы:**\n<pre>{log_output}</pre>", parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при чтении журналов: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журналов: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("fall2ban"))
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
        if not os.path.exists(F2B_LOG_FILE):
             sent_message = await message.answer(f"⚠️ Файл лога Fail2Ban не найден: `{F2B_LOG_FILE}`", parse_mode="Markdown")
             LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
             return

        with open(F2B_LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-20:]

        log_entries = []
        for line in reversed(lines):
            if "Ban" in line:
                ip_match = re.search(r'Ban (\S+)', line)
                date_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                if ip_match and date_match:
                    ip = ip_match.group(1)
                    flag = get_country_flag(ip)

                    dt = datetime.strptime(date_match.group(1), "%Y-%m-%d %H:%M:%S")
                    formatted_time = dt.strftime('%H:%M')
                    formatted_date = dt.strftime('%d.%m.%Y')

                    log_entries.append(f"🌍 IP: **{flag} {ip}**\n⏰ Время: **{formatted_time}**\n🗓️ Дата: **{formatted_date}**")

                if len(log_entries) >= 10:
                    break

        if log_entries:
            log_output = "\n\n".join(log_entries)
            sent_message = await message.answer(f"🔒 **Последние 10 блокировок IP (Fail2Ban):**\n\n{log_output}", parse_mode="Markdown")
        else:
            sent_message = await message.answer("🔒 Нет недавних блокировок IP в логах.")

        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при чтении журнала Fail2Ban: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журнала Fail2Ban: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(Command("sshlog"))
async def sshlog_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "sshlog"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    try:
        cmd = "journalctl -u ssh -n 50 --no-pager --since '1 month ago'"
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(stderr.decode())

        lines = stdout.decode().strip().split('\n')
        log_entries = []
        for line in reversed(lines):
            if "Accepted" in line:
                user_match = re.search(r'for (\S+)', line)
                ip_match = re.search(r'from (\S+)', line)
                date_match = re.search(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line)

                if date_match and user_match and ip_match:
                    try:
                        date_str = date_match.group(1)
                        dt_object = datetime.strptime(f"{datetime.now().year} {date_str}", '%Y %b %d %H:%M:%S')
                        if dt_object > datetime.now():
                             dt_object = dt_object.replace(year=datetime.now().year - 1)

                        user = user_match.group(1)
                        ip = ip_match.group(1)
                        flag = get_country_flag(ip)

                        formatted_time = dt_object.strftime('%H:%M')
                        formatted_date = dt_object.strftime('%d.%m.%Y')

                        log_entries.append(f"👤 Пользователь: **{user}**\n🌍 IP: **{flag} {ip}**\n⏰ Время: **{formatted_time}**\n🗓️ Дата: **{formatted_date}**")
                        if len(log_entries) >= 10:
                            break
                    except (ValueError, IndexError) as e:
                        logging.warning(f"Ошибка парсинга строки SSH лога: {e} | {line.strip()}")
                        continue

        if log_entries:
            log_output = "\n\n".join(log_entries)
            sent_message = await message.answer(f"🔐 **Последние 10 успешных входов SSH:**\n\n{log_output}", parse_mode="Markdown")
        else:
            sent_message = await message.answer("🔐 Нет недавних успешных входов SSH в логах.")

        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при чтении журнала SSH: {e}")
        sent_message = await message.answer(f"⚠️ Ошибка при чтении журнала SSH: {str(e)}")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(StateFilter(GenerateVlessStates.waiting_for_file), F.document)
async def handle_vless_file(message: types.Message, state: FSMContext):
    """Обработка загруженного JSON файла конфигурации."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "generate_vless"

    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return

    if not message.document or not message.document.file_name.endswith(".json"):
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("❌ Пожалуйста, отправьте корректный **JSON файл**.", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="Markdown")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        return

    try:
        file = await bot.get_file(message.document.file_id)
        file_path = file.file_path
        file_content = await bot.download_file(file_path)
        json_data = file_content.read().decode('utf-8')

        try:
             json.loads(json_data)
        except json.JSONDecodeError:
             raise ValueError("Содержимое файла не является корректным JSON.")

        await state.update_data(json_data=json_data)

        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("📝 Введите **имя** для VLESS ссылки:", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="Markdown")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.set_state(GenerateVlessStates.waiting_for_name)

    except Exception as e:
        logging.error(f"Ошибка при обработке файла VLESS: {e}")
        await state.clear()
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(f"⚠️ Ошибка при обработке файла: **{str(e)}**", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="Markdown")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(StateFilter(GenerateVlessStates.waiting_for_file))
async def handle_vless_file_wrong_type(message: types.Message, state: FSMContext):
    """Обработка не-файла, пока ожидаем файл."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return

    await delete_previous_message(user_id, command, chat_id)
    sent_message = await message.answer("❌ Ожидается отправка **JSON файла**. Попробуйте еще раз или нажмите Назад.", reply_markup=get_back_keyboard("back_generate_vless"), parse_mode="Markdown")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


@dp.message(StateFilter(GenerateVlessStates.waiting_for_name))
async def handle_vless_name(message: types.Message, state: FSMContext):
    """Обработка введенного имени и генерация QR-кода."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "generate_vless"

    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        await state.clear()
        return

    custom_name = message.text.strip()
    if not custom_name:
         custom_name = f"VLESS_Config_by_{message.from_user.first_name or user_id}"

    data = await state.get_data()
    json_data = data.get("json_data")
    await state.clear()

    if not json_data:
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("⚠️ Ошибка: JSON данные не найдены, начните сначала.", reply_markup=get_back_keyboard("back_to_menu"))
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        return

    vless_url = convert_json_to_vless(json_data, custom_name)

    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
        qr.add_data(vless_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        img_byte_arr = io.BytesIO()
        qr_img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        photo = BufferedInputFile(img_byte_arr.getvalue(), filename="vless_qr.png")

        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer_photo(
            photo=photo,
            caption=f"🔗 **VLESS ссылка для «{escape_html(custom_name)}»:**\n\n"
                    f"Код:\n<code>{escape_html(vless_url)}</code>",
            parse_mode="HTML"
        )
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    except Exception as e:
        logging.error(f"Ошибка при генерации QR-кода или отправке фото: {e}")
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer(
            f"🔗 **VLESS ссылка для «{escape_html(custom_name)}»:**\n\n"
            f"Код:\n<code>{escape_html(vless_url)}</code>\n\n"
            f"⚠️ Ошибка при генерации QR-кода или отправке: {escape_html(str(e))}",
            parse_mode="HTML",
        )
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id


async def initial_reboot_check():
    """Проверяет флаг перезагрузки при старте и отправляет уведомление."""
    if os.path.exists(REBOOT_FLAG_FILE):
        try:
            with open(REBOOT_FLAG_FILE, "r") as f:
                user_id = int(f.read().strip())

            await bot.send_message(
                chat_id=user_id,
                text="✅ **Сервер успешно перезагружен! Бот снова в сети.**",
                parse_mode="Markdown"
            )
            logging.info(f"Отправлено уведомление о перезагрузке пользователю ID: {user_id}")
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления о перезагрузке: {e}")
        finally:
            os.remove(REBOOT_FLAG_FILE)

async def main():
    """Основная функция запуска бота."""
    try:
        logging.info(f"Бот запускается в режиме: {INSTALL_MODE.upper()}")
        load_users()
        await refresh_user_names()
        await initial_reboot_check()

        # Запускаем мониторинг трафика
        asyncio.create_task(traffic_monitor())

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except Exception as e:
        logging.critical(f"Критическая ошибка запуска бота: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")
    except Exception as e:
        logging.error(f"Непредвиденное завершение: {e}")