# 🧩 Инструкция по добавлению модуля

Проект построен на модульной архитектуре. Каждый функциональный блок (например, `uptime`, `speedtest`) — это отдельный Python-файл в папке `modules/`. Чтобы добавить новую функцию, нужно выполнить 4 простых шага.

---

### 📂 Шаг 1: Создание файла модуля

Создайте новый файл в директории `modules/`. Например, назовем его `my_feature.py`.

**Путь:** `/opt/tg-bot/modules/my_feature.py`

Вставьте в него следующий шаблон. Это актуальная структура, совместимая с ядром версии 1.15.x.

```python
import asyncio
import logging
from aiogram import Dispatcher, types
from aiogram.types import KeyboardButton

# Импорты ядра
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS

# 1. Уникальный ключ кнопки (должен быть добавлен в i18n)
BUTTON_KEY = "btn_my_feature"

# 2. Функция, возвращающая кнопку для клавиатуры
def get_button() -> KeyboardButton:
    # Возвращает кнопку с текстом на дефолтном языке (текст подменится фильтром при нажатии)
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

# 3. Регистрация обработчиков
def register_handlers(dp: Dispatcher):
    # I18nFilter перехватывает нажатие кнопки на любом языке
    dp.message(I18nFilter(BUTTON_KEY))(my_feature_handler)

# 4. Основная логика
async def my_feature_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    
    # Имя команды для проверки прав (должно совпадать с ключом в allowed_commands, если используется)
    # Или просто уникальный идентификатор для удаления старых сообщений
    command = "my_feature"

    # --- Проверка прав ---
    # Проверяет, есть ли у пользователя доступ к этой команде или группе (admins/users)
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    # --- Очистка чата ---
    # Удаляет предыдущее сообщение от этой же команды, чтобы не спамить
    await delete_previous_message(user_id, command, chat_id, message.bot)

    # --- Ваша логика ---
    try:
        # Пример работы
        result_data = "Работа выполнена успешно!"
        
        # Получаем текст ответа из i18n
        response_text = _("my_feature_response", lang, data=result_data)
    except Exception as e:
        logging.error(f"Error in my_feature: {e}")
        response_text = _("error_with_details", lang, error=str(e))

    # --- Отправка ответа ---
    sent_message = await message.answer(response_text, parse_mode="HTML")

    # Сохраняем ID сообщения для будущего удаления
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

```

---

### 🌐 Шаг 2: Добавление переводов (i18n)

Добавьте тексты для кнопки и ответов в словарь переводов.

**Файл:** `/opt/tg-bot/core/i18n.py`

Найдите словарь `STRINGS` и добавьте ключи для русского (`ru`) и английского (`en`) языков.

```python
STRINGS = {
    'ru': {
        # ... (существующие строки) ...
        "btn_my_feature": "✨ Моя Функция",
        "my_feature_response": "✅ Результат:\n<b>{data}</b>",
    },
    'en': {
        # ... (existing strings) ...
        "btn_my_feature": "✨ My Feature",
        "my_feature_response": "✅ Result:\n<b>{data}</b>",
    }
}

```

---

### ⚙️ Шаг 3: Регистрация модуля в боте

Сообщите боту о новом файле.

**Файл:** `/opt/tg-bot/bot.py`

1. **Найдите блок импортов** `from modules import (...)` и добавьте туда ваш модуль:
```python
from modules import (
    selftest, traffic, uptime, notifications, users, vless,
    speedtest, top, xray, sshlog, fail2ban, logs, update, reboot, restart,
    optimize, nodes,
    my_feature  # <--- Добавьте это (не забудьте запятую выше)
)

```


2. **Найдите функцию** `load_modules()` и зарегистрируйте модуль:
```python
def load_modules():
    logging.info("Loading modules...")
    register_module(selftest)
    register_module(uptime)
    # ... другие модули ...

    # ВАРИАНТ 1: Доступно всем (кто прошел авторизацию в боте)
    register_module(my_feature)

    # ВАРИАНТ 2: Только для Админов
    # register_module(my_feature, admin_only=True)

    # ВАРИАНТ 3: Только для Root (требует прав суперпользователя)
    # register_module(my_feature, root_only=True)

```



---

### 🔄 Шаг 4: Перезапуск бота

Примените изменения, перезапустив службу.

**Systemd:**

```bash
sudo systemctl restart tg-bot

```

**Docker:**

```bash
docker compose restart
# или точечно:
docker compose restart bot-secure

```

### ⌨️ Шаг 5 (Опционально): Добавление кнопки в меню

Если вы хотите, чтобы кнопка появилась в **главном меню** или **подменю**, вам нужно отредактировать файл раскладок.

**Файл:** `/opt/tg-bot/core/keyboards.py`

Найдите функцию `get_subcategory_keyboard` (или `get_main_reply_keyboard`, если хотите кнопку на главном экране) и добавьте вызов `my_feature.get_button()` в соответствующий список.

```python
# Пример добавления в категорию "Инструменты"
elif category == "cat_tools":
    kb = [
        [speedtest.get_button(), top.get_button()],
        [my_feature.get_button()], # <--- Ваша кнопка
        [i18n.get_text_button("btn_back_to_menu", user_id)]
    ]

```

✅ **Готово!** Ваша функция теперь часть бота.