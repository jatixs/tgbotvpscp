# 🧩 Guide to Adding a Module

The project is built on a modular architecture. Each functional block (e.g., `uptime`, `speedtest`, `backups`) is a separate Python file in the `modules/` folder. To add a new feature, follow these 5 steps.

---

### 📂 Step 1: Create Module File

Create a new file in the `modules/` directory. For example: `my_feature.py`.

**Path:** `/opt/tg-bot/modules/my_feature.py`

Insert the following template, compatible with the current architecture:

```python
import asyncio
import logging
from aiogram import Dispatcher, types
from aiogram.types import KeyboardButton

# Core imports
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS

# 1. Unique button key (must be added to i18n)
BUTTON_KEY = "btn_my_feature"

# 2. Menu category (monitoring / management / security / tools)
CATEGORY = "tools"

# 3. Button function
def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

# 4. Subcategory
def get_subcategory() -> str:
    return CATEGORY

def has_subcategory() -> bool:
    return True

# 5. Register handlers
def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(my_feature_handler)

# 6. Main logic
async def my_feature_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "my_feature"

    # --- Permission check ---
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    # --- Chat cleanup ---
    await delete_previous_message(user_id, command, chat_id, message.bot)

    # --- Your logic ---
    try:
        result_data = "Task completed successfully!"
        response_text = _("my_feature_response", lang, data=result_data)
    except Exception as e:
        logging.error(f"Error in my_feature: {e}")
        response_text = _("error_with_details", lang, error=str(e))

    # --- Send response ---
    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
```

---

### 🌐 Step 2: Add Translations (i18n)

Add texts for the button and responses to the translation dictionary.

**File:** `/opt/tg-bot/core/i18n.py`

Find the `STRINGS` dictionary and add your keys:

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
    # ... (existing strings) ...
}
```

---

### ⚙️ Step 3: Register Module in Bot

**File:** `/opt/tg-bot/bot.py`

Find the `MODULE_CONFIG` dictionary and add your module:

```python
MODULE_CONFIG = {
    # ... other modules ...
    "modules.my_feature": {"tier": ModuleTier.ON_DEMAND},  # <--- your module
}
```

*Note:* The Orchestrator (`core/orchestrator.py`) will automatically discover your module, lazy-load it on the first call, and register its handlers. This approach helps save RAM.

---

### ⌨️ Step 4: Add Button to Menu

**File:** `/opt/tg-bot/core/keyboards.py`

Find the `get_subcategory_keyboard` function and add the button to the desired category:

```python
elif category == "cat_tools":
    kb = [
        [speedtest.get_button(), top.get_button()],
        [my_feature.get_button()],  # <--- your button
        [i18n.get_text_button("btn_back_to_menu", user_id)]
    ]
```

Don't forget to import the module at the top of `keyboards.py`:
```python
from modules import my_feature
```

---

### 🔄 Step 5: Restart Bot

**Systemd:**
```bash
sudo systemctl restart tg-bot
```

**Docker:**
```bash
docker compose restart
```

---

### 🧩 Optional: Background Tasks

If your module needs a periodic task (e.g., check every 60 seconds):

```python
def start_background_tasks(bot) -> list:
    task = asyncio.create_task(_my_background_loop(bot))
    return [task]

async def _my_background_loop(bot):
    while True:
        try:
            # Your logic
            pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Background task error: {e}")
        await asyncio.sleep(60)
```

✅ **Done!** Your module is now part of the bot.
