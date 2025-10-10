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

# Системные файлы (пути к ним обычно фиксированы)
SSH_LOG_FILE = "/var/log/auth.log"
F2B_LOG_FILE = "/var/log/fail2ban.log"
SYSLOG_FILE = "/var/log/syslog"

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

class GenerateVlessStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_name = State()

class ManageUsersStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()
    waiting_for_change_group = State()

def is_allowed(user_id, command=None):
    """Проверяет, разрешен ли пользователь и имеет ли он доступ к команде."""
    if user_id not in ALLOWED_USERS:
        return False
    
    # Всегда разрешенные команды (даже для не-админов)
    allowed_for_all = ["start", "menu", "back_to_menu", "uptime", "traffic", "selftest", "get_id", "manage_users"]
    if command in allowed_for_all:
        return True
    
    # Команды только для Администраторов
    admin_commands = [
        "manage_users", "reboot_confirm", "generate_vless", "fall2ban", 
        "sshlog", "logs", "restart", "speedtest", "top", "update", "updatexray",
        "adduser" # Включено для совместимости с /adduser
    ]
    if command in admin_commands:
        return user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
        
    # Если команда не определена или это callback, предполагаем, что она для админов, 
    # если только она не была явно разрешена выше
    return user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"

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
    # Используем t.me/bot_username?start=... чтобы получить User ID 
    # Но для универсальности оставим ссылку на админа
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
    """Создает основное меню."""
    is_admin = user_id == ADMIN_USER_ID or ALLOWED_USERS.get(user_id) == "Админы"
    
    if is_admin:
        buttons = [
            [KeyboardButton(text="👤 Пользователи"), KeyboardButton(text="🔗 VLESS-ссылка")],
            [KeyboardButton(text="🛠 Сведения о сервере"), KeyboardButton(text="📡 Трафик сети")],
            [KeyboardButton(text="🔥 Топ процессов"), KeyboardButton(text="📜 SSH-лог")],
            [KeyboardButton(text="🔒 Fail2Ban Log"), KeyboardButton(text="📜 Последние события")],
            [KeyboardButton(text="🚀 Скорость сети"), KeyboardButton(text="⏱ Аптайм")],
            [KeyboardButton(text="🔄 Обновление VPS"), KeyboardButton(text="🩻 Обновление X-ray")],
            [KeyboardButton(text="🔄 Перезагрузка сервера"), KeyboardButton(text="♻️ Перезапуск бота")]
        ]
    else:
        buttons = [
            [KeyboardButton(text="🛠 Сведения о сервере"), KeyboardButton(text="📡 Трафик сети")],
            [KeyboardButton(text="⏱ Аптайм"), KeyboardButton(text="🆔 Мой ID")]
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
        
        # Проверяем наличие realitySettings
        if 'realitySettings' not in outbound['streamSettings']:
             raise ValueError("Отсутствуют realitySettings в конфигурации streamSettings.")
             
        reality = outbound['streamSettings']['realitySettings']

        vless_params = {
            'id': user['id'],
            'address': vnext['address'],
            'port': vnext['port'],
            'security': outbound['streamSettings']['security'],
            'host': reality.get('serverName', 'none'),
            'fp': reality.get('fingerprint', 'none'),
            'pbk': reality.get('publicKey', 'none'),
            'sid': reality.get('shortId', 'none'),
            'type': outbound['streamSettings']['network'],
            'flow': user.get('flow', 'none'),
            'encryption': user.get('encryption', 'none'),
            'headerType': 'none'
        }
        
        # Улучшенная логика формирования URL для Reality (xtls-rprx-vision/tls)
        query_params = {
            'security': vless_params['security'],
            'encryption': vless_params['encryption'],
            'pbk': vless_params['pbk'],
            'fp': vless_params['fp'],
            'type': vless_params['type'],
        }

        if vless_params['flow'] != 'none' and vless_params['flow']:
             query_params['flow'] = vless_params['flow']
        
        if vless_params['type'] == 'grpc':
            # Добавляем gRPC-специфичные параметры
            query_params['serviceName'] = outbound['streamSettings'].get('grpcSettings', {}).get('serviceName', '')
            query_params['mode'] = outbound['streamSettings'].get('grpcSettings', {}).get('mode', '')
            
        # Параметры Reality
        query_params['sni'] = vless_params['host']
        query_params['host'] = vless_params['host'] # дублируем для совместимости
        query_params['sid'] = vless_params['sid']
        
        # Преобразование параметров в строку запроса
        query_string = urllib.parse.urlencode({k: v for k, v in query_params.items() if v and v != 'none'}, quote_via=urllib.parse.quote)

        # Формирование VLESS-ссылки
        vless_url = (f"vless://{vless_params['id']}@{vless_params['address']}:{vless_params['port']}?"
                     f"{query_string}"
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
    
    if not is_allowed(user_id, command):
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
        await send_access_denied_message(user_id, message.chat.id, command)
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
        await send_access_denied_message(user_id, message.chat.id, command)
        return
    await delete_previous_message(user_id, command, message.chat.id)
    sent_message = await message.answer("⚠️ Вы уверены, что хотите **перезагрузить сервер**? Все активные соединения будут разорваны.", reply_markup=get_reboot_confirmation_keyboard(), parse_mode="Markdown")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

@dp.message(F.text == "🔗 VLESS-ссылка")
async def generate_vless_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, message.chat.id, command)
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
async def text_updatexray_handler(message: types.Message):
    await updatexray_handler(message)
    
@dp.message(F.text == "🆔 Мой ID")
async def get_id_handler(message: types.Message):
    user_id = message.from_user.id
    command = "get_id"
    if not is_allowed(user_id, command):
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
    if command.startswith("delete_user_") or command.startswith("set_group_") or command.startswith("select_user_change_group_"):
         permission_check_command = "manage_users"
    elif command.startswith("request_self_delete_") or command.startswith("confirm_self_delete_") or command == "back_to_delete_users":
         permission_check_command = "manage_users"
    elif command in ["reboot", "back_generate_vless"]:
         permission_check_command = command
    else:
         permission_check_command = command

    if not is_allowed(user_id, permission_check_command):
        if user_id not in ALLOWED_USERS:
            await send_access_denied_message(user_id, chat_id, command)
        else:
            await callback.message.answer(f"⛔ Команда '{command}' недоступна для вашей группы ({ALLOWED_USERS[user_id]}).")
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
                # Перезапуск, чтобы обновить права доступа без задержки
                os.system(f"sudo systemctl restart tg-bot.service")

        elif command == "back_to_manage_users":
            # Удаляем предыдущее сообщение с кнопкой 'Назад' и отправляем новое меню управления
            await bot.delete_message(chat_id, message_id)
            await manage_users_handler(callback.message)
            
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
                    os.system(f"sudo systemctl restart tg-bot.service")
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
                os.system(f"sudo systemctl restart tg-bot.service")
            else:
                await callback.message.edit_text(f"⚠️ Пользователь ID **`{target_user_id}`** не найден", reply_markup=get_back_keyboard("back_to_manage_users"), parse_mode="Markdown")
        
        # --- Other Callbacks ---
        elif command == "reboot":
             await reboot_handler(callback)
             
        elif command == "back_generate_vless":
            await state.clear()
            await callback.message.edit_text("🔗 VLESS-ссылка", reply_markup=None)
            
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
        os.system(f"sudo systemctl restart tg-bot.service")
        
    elif callback.data == "back_to_manage_users":
        # Пользователь отменил выбор группы, возвращаем его в меню управления
        await state.clear()
        await callback.message.edit_text(
             "👤 Управление пользователями:",
             reply_markup=get_manage_users_keyboard()
        )


# --- ACTION HANDLERS (CALLED BY TEXT OR COMMANDS) ---
# ... (Остальные обработчики команд uptime, update, restart, reboot_handler, updatexray, traffic_handler, selftest, speedtest, top_handler, logs_handler, fall2ban_handler, sshlog_handler, handle_vless_file, handle_vless_name)
# Я скопирую их ниже, но не буду их комментировать здесь, чтобы не увеличивать объем файла

@dp.message(Command("uptime"))
async def uptime_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "uptime"
    if not is_allowed(user_id, command):
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

    # Используем nohup и & для неблокирующего выполнения в фоновом режиме, 
    # а затем считываем статус после завершения (этот подход более надежен)
    cmd = "sudo DEBIAN_FRONTEND=noninteractive apt update && sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y && sudo apt autoremove -y"
    
    # Создаем временный файл для вывода
    temp_output_file = f"/tmp/update_output_{user_id}_{datetime.now().timestamp()}.txt"

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
        # Берем последние 4000 символов, чтобы не превысить лимит Telegram
        response_text = f"✅ Обновление завершено:\n<pre>{escape_html(output[-4000:])}</pre>"
    else:
        # Показываем ошибку
        response_text = f"❌ Ошибка при обновлении (Код: {process.returncode}):\n<pre>{escape_html(error_output[-4000:])}</pre>"

    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    
    # Удаляем временный файл
    try:
        if os.path.exists(temp_output_file):
             os.remove(temp_output_file)
    except Exception as e:
         logging.warning(f"Не удалось удалить временный файл {temp_output_file}: {e}")

@dp.message(Command("restart"))
async def restart_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "restart"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    
    sent_msg = await message.answer("♻️ Бот ушел перезагружаться... Ожидайте.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id
    
    # Отправляем сообщение о перезапуске
    # Очистка лога не требуется, так как systemd перезапускает службу
    try:
        # Даем время, чтобы Telegram отправил сообщение
        await asyncio.sleep(2) 
        # Перезапуск сервиса через systemctl
        os.system("sudo systemctl restart tg-bot.service") 
    except Exception as e:
        logging.error(f"Ошибка при попытке перезапуска: {e}")
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
            pass # Игнорируем ошибку, если сообщение уже изменено/удалено

        # Записываем ID пользователя, чтобы после перезагрузки ему пришло уведомление
        try:
            with open(REBOOT_FLAG_FILE, "w") as f:
                f.write(str(user_id))
        except Exception as e:
             logging.error(f"Не удалось записать флаг перезагрузки: {e}")
             
        # Перезагрузка
        os.system("sudo reboot")
    else:
        await bot.edit_message_text(
            "⛔ Отказано. Только администраторы могут перезагрузить сервер.",
            chat_id=chat_id,
            message_id=message_id
        )

@dp.message(Command("updatexray"))
async def updatexray_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "updatexray"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    sent_msg = await message.answer("🔄 Обновление Xray начато... Ожидайте.")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id

    try:
        # Проверяем, запущен ли контейнер amnezia-xray
        check_container_cmd = "docker ps --filter name=amnezia-xray --format '{{.Names}}'"
        process_check = await asyncio.create_subprocess_shell(
            check_container_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_check, _ = await process_check.communicate()
        container_check = stdout_check.decode().strip()

        if "amnezia-xray" not in container_check:
            raise Exception("Контейнер `amnezia-xray` не найден или не запущен. Обновление невозможно.")

        # Команда для обновления Xray внутри контейнера (с использованием wget, unzip)
        update_cmd = (
            'docker exec amnezia-xray /bin/bash -c "'
            'export XRAY_VERSION=$(curl -s "https://api.github.com/repos/XTLS/Xray-core/releases/latest" | grep -Po \'"tag_name": "\K[vV]?([0-9.]+)"\') && '
            'echo "Найдена версия $XRAY_VERSION" && '
            'rm -f Xray-linux-64.zip xray && '
            'wget -q -O Xray-linux-64.zip https://github.com/XTLS/Xray-core/releases/download/$XRAY_VERSION/Xray-linux-64.zip && '
            'unzip -o Xray-linux-64.zip && '
            'cp xray /usr/bin/xray && '
            'rm Xray-linux-64.zip xray" && '
            'docker restart amnezia-xray'
        )
        
        process_update = await asyncio.create_subprocess_shell(
            update_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        # Ждем завершения и считываем весь вывод
        stdout_update, stderr_update = await process_update.communicate()
        update_output = stdout_update.decode()
        update_error = stderr_update.decode()

        if process_update.returncode != 0:
            raise Exception(f"Команда обновления завершилась с ошибкой: {update_error[-500:]}")

        # Проверка версии после обновления
        version_cmd = "docker exec amnezia-xray /usr/bin/xray version"
        process_version = await asyncio.create_subprocess_shell(
            version_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_version, stderr_version = await process_version.communicate()

        if process_version.returncode != 0:
            raise Exception(f"Не удалось получить версию Xray после обновления: {stderr_version.decode()[-500:]}")

        version_output = stdout_version.decode()
        version_match = re.search(r'Xray\s+([\d\.]+)', version_output)
        version = version_match.group(1) if version_match else "неизвестной версии"

        await delete_previous_message(user_id, command, chat_id)
        sent_msg = await message.answer(f"✅ Ваша версия Xray обновлена до **`{version}`**", parse_mode="Markdown")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id

    except Exception as e:
        logging.error(f"Ошибка в updatexray_handler: {e}")
        error_msg = f"⚠️ Ошибка при обновлении Xray: {escape_html(str(e))}"
        await delete_previous_message(user_id, command, chat_id)
        sent_msg = await message.answer(error_msg, parse_mode="HTML")
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_msg.message_id

@dp.message(Command("traffic"))
async def traffic_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    command = "traffic"
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    
    # Инициализация первого значения для расчета скорости
    counters = psutil.net_io_counters()
    TRAFFIC_PREV[user_id] = (counters.bytes_recv, counters.bytes_sent)
    
    msg_text = ("📡 **Мониторинг трафика включен**...\n\n_Обновление каждые 5 секунд. Чтобы остановить, выберите любую другую команду._")
    sent_message = await message.answer(msg_text, parse_mode="Markdown")
    
    # Сохраняем ID сообщения для обновления в асинхронной задаче
    TRAFFIC_MESSAGE_IDS[user_id] = sent_message.message_id
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    # Запускать traffic_monitor уже не нужно, так как он запущен в main()
    # Теперь он будет обновлять только те сообщения, ID которых есть в TRAFFIC_MESSAGE_IDS

async def traffic_monitor():
    """Асинхронный цикл для мониторинга и обновления сообщений о трафике."""
    await asyncio.sleep(5) # Ждем, чтобы другие задачи успели выполниться
    while True:
        # Создаем копию ключей, чтобы избежать ошибки изменения словаря во время итерации
        for user_id in list(TRAFFIC_MESSAGE_IDS.keys()): 
            # Проверяем, что мониторинг все еще нужен
            if user_id not in TRAFFIC_MESSAGE_IDS:
                 continue
                 
            try:
                counters = psutil.net_io_counters()
                rx = counters.bytes_recv
                tx = counters.bytes_sent
                
                # Защита от отсутствия предыдущих значений
                prev_rx, prev_tx = TRAFFIC_PREV.get(user_id, (rx, tx))
                
                # Расчет скорости в Мбит/с (бит / 1024^2 / 5 секунд)
                rx_speed = (rx - prev_rx) * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                tx_speed = (tx - prev_tx) * 8 / 1024 / 1024 / TRAFFIC_INTERVAL
                
                TRAFFIC_PREV[user_id] = (rx, tx)
                
                msg_text = (
                    f"📡 **Общий трафик VPS:**\n"
                    f"⬇️ RX (Принято): **{format_traffic(rx)}**\n"
                    f"⬆️ TX (Отправлено): **{format_traffic(tx)}**\n\n"
                    f"⚡️ **Текущая скорость (Обновляется каждые {TRAFFIC_INTERVAL}с):**\n"
                    f"⬇️ RX: **{rx_speed:.2f} Мбит/с**\n"
                    f"⬆️ TX: **{tx_speed:.2f} Мбит/с**"
                )
                
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=TRAFFIC_MESSAGE_IDS[user_id],
                    text=msg_text,
                    parse_mode="Markdown"
                )
            except TelegramRetryAfter as e:
                logging.warning(f"Ошибка TelegramRetryAfter для {user_id}: Подождите {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                # Скорее всего, пользователь удалил сообщение
                if "message is not modified" in str(e):
                    # Игнорируем, если сообщение не изменилось
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
    if not is_allowed(user_id, command):
        await send_access_denied_message(user_id, chat_id, command)
        return
    await delete_previous_message(user_id, command, chat_id)
    
    # Получение метрик
    cpu = psutil.cpu_percent()
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    with open("/proc/uptime") as f:
        uptime_sec = float(f.readline().split()[0])
    uptime_str = format_uptime(uptime_sec)
    
    # Проверка пинга и внешнего IP
    ping_result = os.popen("ping -c 1 -W 2 8.8.8.8").read()
    ping_match = re.search(r'time=([\d\.]+) ms', ping_result)
    ping_time = ping_match.group(1) if ping_match else "N/A"
    internet = "✅ Интернет доступен" if ping_match else "❌ Нет интернета"
    external_ip = os.popen("curl -4 -s ifconfig.me").read().strip()
    
    # Поиск последнего SSH входа
    last_login = "**N/A** (Нет файла логов)"
    if os.path.exists(SSH_LOG_FILE):
        try:
            cmd = f"sudo tail -n 50 {SSH_LOG_FILE} | grep 'Accepted' | tail -n 1"
            process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await process.communicate()
            last_line = stdout.decode('utf-8', errors='ignore').strip()
            
            if last_line:
                # Извлечение данных из последней строки лога
                date_match = re.search(r'(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', last_line)
                user_match = re.search(r'for (\S+)', last_line)
                ip_match = re.search(r'from (\S+)', last_line)

                if date_match and user_match and ip_match:
                    # Преобразуем дату, добавляем текущий год, если его нет (для старых логов)
                    log_timestamp = datetime.strptime(date_match.group(1), '%b %d %H:%M:%S')
                    # Предполагаем, что это текущий год
                    current_year = datetime.now().year
                    dt_object = log_timestamp.replace(year=current_year)
                    
                    user = user_match.group(1)
                    ip = ip_match.group(1)
                    flag = get_country_flag(ip)
                    
                    # Проверяем, не прошло ли событие в прошлом году
                    if dt_object > datetime.now():
                         dt_object = dt_object.replace(year=current_year - 1)
                         
                    formatted_time = dt_object.strftime('%H:%M')
                    formatted_date = dt_object.strftime('%d.%m.%Y')
                    
                    last_login = (f"👤 **{user}**\n"
                                  f"🌍 IP: **{flag} {ip}**\n"
                                  f"⏰ Время: **{formatted_time}**\n"
                                  f"🗓️ Дата: **{formatted_date}**")
                else:
                    last_login = "**N/A** (Ошибка парсинга лога)"
            else:
                 last_login = "**N/A** (Нет успешных входов)"
        except Exception as e:
            logging.error(f"Ошибка при получении последнего SSH входа: {e}")
            last_login = f"**N/A** (Ошибка: {str(e)})"
            
    # Общий трафик
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
        f"📡 Трафик⬇ **{format_traffic(rx)}** / ⬆ **{format_traffic(tx)}**\n\n"
        f"📄 **Последний успешный вход SSH:**\n{last_login}"
    )

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

    # Используем speedtest-cli с форматом JSON
    cmd = "speedtest --format=json"
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
            # Bandwidth в байтах/с. Переводим в Мбит/с (МБит/с = (Байт * 8) / (1024 * 1024))
            # Или просто делим на 125000, т.к. 125000 Байт/с = 1 Мбит/с
            download_speed = data.get("download", {}).get("bandwidth", 0) / 125000
            upload_speed = data.get("upload", {}).get("bandwidth", 0) / 125000
            ping_latency = data.get("ping", {}).get("latency", "N/A")
            isp = data.get("isp", "N/A")
            server_name = data.get("server", {}).get("name", "N/A")
            result_url = data.get("result", {}).get("url", "N/A")
            
            response_text = (f"🚀 **Результаты Speedtest:**\n"
                             f"⬇ Входящая: **{download_speed:.2f} Мбит/с**\n"
                             f"⬆ Исходящая: **{upload_speed:.2f} Мбит/с**\n"
                             f"⏱ Пинг: **{ping_latency:.2f} мс**\n"
                             f"📡 Провайдер: **{isp}**\n"
                             f"🌐 Тестовый сервер: **{server_name}**\n\n"
                             f"🔗 [Посмотреть полный результат]({result_url})")
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка парсинга JSON от speedtest: {e}")
            response_text = f"❌ Ошибка при обработке результатов speedtest: <pre>{escape_html(str(e))}</pre>"
    else:
        error_output = stderr.decode('utf-8', errors='ignore')
        response_text = f"❌ Ошибка при запуске speedtest:\n<pre>{escape_html(error_output)}</pre>"

    sent_message = await message.answer(response_text, parse_mode="Markdown" if process.returncode == 0 else "HTML", disable_web_page_preview=False if process.returncode == 0 else True)
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

    cmd = "ps aux --sort=-%cpu | head -n 15" # Увеличим до 15 строк для большей информативности
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
        log_file = SYSLOG_FILE
        if not os.path.exists(log_file):
             log_file = SSH_LOG_FILE
             
        cmd = f"sudo tail -n 25 {log_file}"
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            log_output = escape_html(stdout.decode('utf-8', errors='ignore'))
            sent_message = await message.answer(f"📜 **Последние системные журналы ({os.path.basename(log_file)}):**\n<pre>{log_output}</pre>", parse_mode="HTML")
        else:
             error_output = escape_html(stderr.decode())
             sent_message = await message.answer(f"❌ Ошибка при чтении журналов: <pre>{error_output}</pre>", parse_mode="HTML")
             
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
        if not os.path.exists(F2B_LOG_FILE):
             sent_message = await message.answer(f"⚠️ Файл лога Fail2Ban не найден: `{F2B_LOG_FILE}`", parse_mode="Markdown")
             LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
             return

        # Ищем последние 20 строк, содержащих "Ban"
        cmd = f"sudo grep 'Ban ' {F2B_LOG_FILE} | tail -n 20"
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await process.communicate()
        lines = stdout.decode('utf-8', errors='ignore').splitlines()
        
        log_entries = []
        for line in reversed(lines):
            ip_match = re.search(r'Ban (\S+)', line)
            date_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if ip_match and date_match:
                ip = ip_match.group(1)
                flag = get_country_flag(ip)
                
                # Парсим дату и время
                dt = datetime.strptime(date_match.group(1), "%Y-%m-%d %H:%M:%S")
                # Для логов Fail2Ban, скорее всего, нужна локальная временная зона, 
                # но для универсальности оставлю без смещения, если оно не было введено ранее.
                
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
        if not os.path.exists(SSH_LOG_FILE):
             sent_message = await message.answer(f"⚠️ Файл лога SSH не найден: `{SSH_LOG_FILE}`", parse_mode="Markdown")
             LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
             return
             
        # Ищем последние 20 строк, содержащих "Accepted"
        cmd = f"sudo grep 'Accepted' {SSH_LOG_FILE} | tail -n 20"
        process = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await process.communicate()
        lines = stdout.decode('utf-8', errors='ignore').splitlines()
        
        log_entries = []
        for line in reversed(lines):
            # Парсинг логов (формат /var/log/auth.log может отличаться)
            # Пример: Oct 10 10:00:00 hostname sshd[1234]: Accepted publickey for user from 1.1.1.1 port 50000 ssh2: RSA SHA256:....
            # Или: 2023-10-10T10:00:00+03:00 hostname sshd[1234]: Accepted... (если используется rsyslog с ISO-форматом)
            
            # Попытка парсинга стандартного формата
            user_match = re.search(r'for (\S+)', line)
            ip_match = re.search(r'from (\S+)', line)
            
            # Поиск даты (более сложная задача)
            # Для универсальности, ищем дату в начале строки (Oct 10 10:00:00 или ISO-формат)
            date_match = re.search(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line) # стандартный syslog
            if not date_match:
                 date_match = re.search(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line) # ISO
            
            if date_match and user_match and ip_match:
                try:
                    date_str = date_match.group(1)
                    if 'T' in date_str: # ISO format
                        dt_object = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S')
                    else: # Syslog format
                         # Добавляем текущий год для парсинга
                        dt_object = datetime.strptime(f"{datetime.now().year} {date_str}", '%Y %b %d %H:%M:%S')
                        # Корректируем год, если время в будущем (значит, событие из прошлого года)
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
        
        # Предварительная проверка JSON
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
    await state.clear() # Сразу очищаем состояние FSM

    if not json_data:
        await delete_previous_message(user_id, command, chat_id)
        sent_message = await message.answer("⚠️ Ошибка: JSON данные не найдены, начните сначала.", reply_markup=get_back_keyboard("back_to_menu"))
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        return

    vless_url = convert_json_to_vless(json_data, custom_name)

    try:
        # Генерация QR-кода
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
            
            # Отправляем уведомление, но только если это не ADMIN_USER_ID, чтобы избежать дублирования
            # Хотя, лучше отправить всем, кто запросил.
            await bot.send_message(
                chat_id=user_id, 
                text="✅ **Сервер успешно перезагружен! Бот снова в сети.**",
                parse_mode="Markdown"
            )
            logging.info(f"Отправлено уведомление о перезагрузке пользователю ID: {user_id}")
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления о перезагрузке: {e}")
        finally:
            # Удаляем флаг
            os.remove(REBOOT_FLAG_FILE)

async def main():
    """Основная функция запуска бота."""
    try:
        load_users()
        await refresh_user_names()
        # Проверяем, был ли ребут, и уведомляем
        await initial_reboot_check()
        
        # Запускаем фоновый мониторинг трафика
        asyncio.create_task(traffic_monitor())
        
        # Регистрируем функцию загрузки пользователей на старт
        dp.startup.register(load_users) 
        
        # Запуск бота
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except Exception as e:
        logging.error(f"Критическая ошибка запуска бота: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")
    except Exception as e:
        logging.error(f"Непредвиденное завершение: {e}")
