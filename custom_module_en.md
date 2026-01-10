# 🧩 Guide to Adding a Module

The project is built on a modular architecture. Each functional block (e.g., `uptime`, `speedtest`) is a separate Python file in the `modules/` folder. To add a new feature, follow these 4 simple steps.

---

### 📂 Step 1: Create Module File

Create a new file in the `modules/` directory. For example, let's call it `my_feature.py`.

**Path:** `/opt/tg-bot/modules/my_feature.py`

Insert the following template. This is the current structure compatible with core version 1.15.x.

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

# 2. Function returning the keyboard button
def get_button() -> KeyboardButton:
    # Returns a button with text in the default language (text is handled by the filter)
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

# 3. Register handlers
def register_handlers(dp: Dispatcher):
    # I18nFilter intercepts the button press in any language
    dp.message(I18nFilter(BUTTON_KEY))(my_feature_handler)

# 4. Main logic
async def my_feature_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    
    # Command name for permission check (must match key in allowed_commands if used)
    # Or simply a unique identifier for deleting old messages
    command = "my_feature"

    # --- Permission check ---
    # Checks if the user has access to this command or group (admins/users)
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return

    # --- Chat cleanup ---
    # Deletes the previous message from this command to avoid spam
    await delete_previous_message(user_id, command, chat_id, message.bot)

    # --- Your logic ---
    try:
        # Example operation
        result_data = "Task completed successfully!"
        
        # Get response text from i18n
        response_text = _("my_feature_response", lang, data=result_data)
    except Exception as e:
        logging.error(f"Error in my_feature: {e}")
        response_text = _("error_with_details", lang, error=str(e))

    # --- Send response ---
    sent_message = await message.answer(response_text, parse_mode="HTML")

    # Save message ID for future deletion
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id

```

---

### 🌐 Step 2: Add Translations (i18n)

Add texts for the button and responses to the translation dictionary.

**File:** `/opt/tg-bot/core/i18n.py`

Find the `STRINGS` dictionary and add keys for Russian (`ru`) and English (`en`) languages.

```python
STRINGS = {
    'ru': {
        # ... (existing strings) ...
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

### ⚙️ Step 3: Register Module in Bot

Inform the bot about the new file.

**File:** `/opt/tg-bot/bot.py`

1. **Find the import block** `from modules import (...)` and add your module there:
```python
from modules import (
    selftest, traffic, uptime, notifications, users, vless,
    speedtest, top, xray, sshlog, fail2ban, logs, update, reboot, restart,
    optimize, nodes,
    my_feature  # <--- Add this (don't forget the comma above)
)

```


2. **Find the function** `load_modules()` and register the module:
```python
def load_modules():
    logging.info("Loading modules...")
    register_module(selftest)
    register_module(uptime)
    # ... other modules ...

    # OPTION 1: Available to everyone (who passed bot auth)
    register_module(my_feature)

    # OPTION 2: Admins only
    # register_module(my_feature, admin_only=True)

    # OPTION 3: Root only (requires superuser privileges)
    # register_module(my_feature, root_only=True)

```



---

### 🔄 Step 4: Restart Bot

Apply changes by restarting the service.

**Systemd:**

```bash
sudo systemctl restart tg-bot

```

**Docker:**

```bash
docker compose restart
# or specifically:
docker compose restart bot-secure

```

### ⌨️ Step 5 (Optional): Add Button to Menu

If you want the button to appear in the **main menu** or a **submenu**, you need to edit the keyboard layout file.

**File:** `/opt/tg-bot/core/keyboards.py`

Find the function `get_subcategory_keyboard` (or `get_main_reply_keyboard` if you want the button on the main screen) and add the call `my_feature.get_button()` to the appropriate list.

```python
# Example of adding to the "Tools" category
elif category == "cat_tools":
    kb = [
        [speedtest.get_button(), top.get_button()],
        [my_feature.get_button()], # <--- Your button
        [i18n.get_text_button("btn_back_to_menu", user_id)]
    ]

```

✅ **Done!** Your feature is now part of the bot.