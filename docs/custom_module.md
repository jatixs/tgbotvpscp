# 🧩 Инструкция по добавлению модуля

Проект построен на модульной архитектуре. Каждый функциональный блок (например, `uptime`, `speedtest`, `backups`) — это отдельный Python-файл в папке `modules/`. Чтобы добавить новую функцию, выполните 5 шагов.

---

### 📂 Шаг 1: Создание файла модуля

Создайте новый файл в директории `modules/`. Например: `my_feature.py`.

**Путь:** `/opt/tg-bot/modules/my_feature.py`

Вставьте следующий шаблон, совместимый с текущей архитектурой:

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

# 2. Категория в меню (monitoring / management / security / tools)
CATEGORY = "tools"

# 3. Функция для кнопки
def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

# 4. Категория подменю
def get_subcategory() -> str:
    return CATEGORY

def has_subcategory() -> bool:
    return True

# 5. Регистрация обработчиков
def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(my_feature_handler)

# 6. Основная логика
async def my_feature_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "my_feature"

    # --- Проверка прав ---
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    # --- Очистка чата ---
    await delete_previous_message(user_id, command, chat_id, message.bot)

    # --- Ваша логика ---
    try:
        result_data = "Работа выполнена успешно!"
        response_text = _("my_feature_response", lang, data=result_data)
    except Exception as e:
        logging.error(f"Error in my_feature: {e}")
        response_text = _("error_with_details", lang, error=str(e))

    # --- Отправка ответа ---
    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
```

---

### 🌐 Шаг 2: Добавление переводов (i18n)

Добавьте тексты для кнопки и ответов в словарь переводов.

**Файл:** `/opt/tg-bot/core/i18n.py`

Найдите словарь `STRINGS` и добавьте ваши ключи:

```python
STRINGS = {
    "btn_my_feature": {
        "ru": "✨ Моя Функция",
        "en": "✨ My Feature"
    },
    "my_feature_response": {
        "ru": "✅ Результат:\n<b>{data}</b>",
        "en": "✅ Result:\n<b>{data}</b>"
    },
    # ... (существующие строки) ...
}
```

---

### ⚙️ Шаг 3: Регистрация модуля в боте

**Файл:** `/opt/tg-bot/bot.py`

Найдите словарь `MODULE_CONFIG` и добавьте ваш модуль:

```python
MODULE_CONFIG = {
    # ... другие модули ...
    "modules.my_feature": {"tier": ModuleTier.ON_DEMAND},  # <--- ваш модуль
}
```

*Примечание:* Оркестратор (`core/orchestrator.py`) автоматически найдет ваш модуль, загрузит его при первом вызове (Lazy Loading) и зарегистрирует обработчики. Это позволяет экономить оперативную память.

---

### ⌨️ Шаг 4: Добавление кнопки в меню

**Файл:** `/opt/tg-bot/core/keyboards.py`

Найдите функцию `get_subcategory_keyboard` и добавьте кнопку в нужную категорию:

```python
elif category == "cat_tools":
    kb = [
        [speedtest.get_button(), top.get_button()],
        [my_feature.get_button()],  # <--- ваша кнопка
        [i18n.get_text_button("btn_back_to_menu", user_id)]
    ]
```

Не забудьте импортировать модуль в начале файла `keyboards.py`:
```python
from modules import my_feature
```

---

### 🔄 Шаг 5: Перезапуск бота

**Systemd:**
```bash
sudo systemctl restart tg-bot
```

**Docker:**
```bash
docker compose restart
```

---

### 🧩 Опционально: Фоновые задачи

Если вашему модулю нужна периодическая задача (например, проверка каждые 60 секунд):

```python
def start_background_tasks(bot) -> list:
    task = asyncio.create_task(_my_background_loop(bot))
    return [task]

async def _my_background_loop(bot):
    while True:
        try:
            # Ваша логика
            pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Background task error: {e}")
        await asyncio.sleep(60)
```

✅ **Готово!** Ваш модуль теперь часть бота.
