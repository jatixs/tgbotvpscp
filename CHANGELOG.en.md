<p align="center">
  English Version | <a href="CHANGELOG.md">Русская Версия</a>
</p>

<h1 align="center">📝 Telegram VPS Management Bot — Changelog</h1>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.10.14-blue?style=flat-square" alt="Version 1.10.14"/>
  <img src="https://img.shields.io/badge/build-41-purple?style=flat-square" alt="Build 41"/>
  <img src="https://img.shields.io/badge/date-Ноябрь%202025-green?style=flat-square" alt="Date November 2025"/>
  <img src="https://img.shields.io/badge/status-stabile-green?style=flat-square" alt="Status Stabile"/>
</p>

---
## [1.10.14] - 2025-11-03

### 🚀 Added:

* **Full Docker Support:** Added the ability to install and run the bot in Docker containers (`root` and `secure` modes).
* **Docker Deployment Scripts:** `deploy.sh` and `deploy_en.sh` have been completely refactored to support selection between `Systemd (Classic)` and `Docker (Isolated)` installations.
* **Docker Dependency:** The `docker` Python library has been added to `requirements.txt` for the watchdog to interact with the Docker API.
* **Docker Configuration:** New environment variables (`DEPLOY_MODE`, `TG_BOT_NAME`, `TG_BOT_CONTAINER_NAME`) added to `.env.example` for Docker deployment.
* **`get_host_path` Utility:** Added a function to `core/utils.py` to correctly resolve paths to host system files (e.g., `/proc/`, `/var/log/`) when running in `docker-root` mode.

### ✨ Improved:

* **Watchdog (`watchdog.py`):** Completely rewritten to support `DEPLOY_MODE`. It can now monitor the status of both `systemd` services and Docker containers using the Docker SDK.
* **Module Docker Compatibility:** Modules `selftest`, `uptime`, `fail2ban`, `logs`, `notifications`, and `sshlog` updated to use `get_host_path()` for host file access, ensuring functionality in `docker-root` mode.
* **Server Management from Docker:**
    * The `reboot.py` module now correctly executes a host reboot (`chroot /host /sbin/reboot`) from `docker-root` mode.
    * The `restart.py` module now executes `docker restart <container_name>` if the bot is running in Docker.
* **Docker Install Reliability:** Applied a `cgroups` fix (creating `daemon.json`) in `deploy.sh` for stable Docker startup on modern OSes (e.g., Debian 12) and improved `docker-compose` installation logic.
* **Deployment Scripts (`deploy.sh`, `deploy_en.sh`):** Functions `update_bot`, `uninstall_bot`, and `check_integrity` now correctly detect and manage both Systemd and Docker installations.

### 🔧 Fixed:

* **Authentication (`core/auth.py`):** Fixed a critical bug in `load_users` and `is_allowed` where admin rights were checked using the localized string ("Админы") from the `main` branch instead of the "admins" key.
* **Permissions (`core/auth.py`):** Clarified the logic for `root_only_commands` to always require administrator privileges (`is_admin_group`) in addition to `INSTALL_MODE="root"`.
* **Security (`modules/logs.py`):** Fixed an XSS (HTML-injection) vulnerability in the "Recent Events" module by adding `escape_html` to the `journalctl` output (escaping was missing in `main`).

---

## [1.10.13] - 2025-10-26

### ✨ Improved:

* **Speedtest Localization:**
    * Results now display the country flag and city (instead of `Location`).
    * The `Server` field has been renamed to `Provider` for clarity.
* **Speedtest Server Lists:**
    * When the VPS geolocation is determined as Russia (`RU`), the bot will now attempt to use a list of Russian iperf3 servers from [GitHub](https://github.com/itdoginfo/russian-iperf3-servers) (in YAML format).
    * Added YAML file parsing for the Russian server list.
    * Added error handling for YAML list download/parsing with a fallback to the main JSON list.
    * The `deploy.sh`/`deploy_en.sh` scripts now install the `python3-yaml` system dependency.
* **Spam Protection:** Added a middleware handler (`core/middlewares.py`) that prevents overly frequent button presses (5-second cooldown).
* **Error Handling:** Improved exception handling in the `get_country_flag` function (`core/utils.py`) for more accurate detection and logging of network/API errors.
* **Logging:** Enhanced logging of unexpected errors using `logging.exception` to automatically include stack traces.
* **i18n Structure:** Keys within the translation dictionaries (`core/i18n.py`) have been sorted alphabetically for easier navigation.

### 🔧 Fixed:

* **Dependencies:** `PyYAML` added to `requirements.txt`. `python3-yaml` added to `deploy.sh`/`deploy_en.sh`.
* **Formatting:** Minor fixes to formatting and imports.

### 📝 Documentation:

* **Adding a Module:** Added a section with instructions on how to create and integrate custom modules in `README.md` and `README.en.md`.
* Updated version and build numbers.

---
<details>
<summary><h2>🧩 How to Add a Custom Module (Template):</h2></summary>

1.  **Create file:** `modules/my_module.py`
2.  **Write code:**
```
    # /opt/tg-bot/modules/my_module.py
    from aiogram import Dispatcher, types
    from aiogram.types import KeyboardButton
    from core.i18n import _, I18nFilter, get_user_lang
    from core import config
    from core.auth import is_allowed
    from core.messaging import delete_previous_message

    # 1. Unique key for the button in i18n
    BUTTON_KEY = "btn_my_command"

    # 2. Function to get the button
    def get_button() -> KeyboardButton:
        return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

    # 3. Function to register handlers
    def register_handlers(dp: Dispatcher):
        # Register handler for the button text (language aware)
        dp.message(I18nFilter(BUTTON_KEY))(my_command_handler)
        # Add other handlers (callback, state...) if needed

    # 4. Main command handler
    async def my_command_handler(message: types.Message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        lang = get_user_lang(user_id)
        command_name_for_auth = "my_command" # Name for permission check

        # Check permissions
        if not is_allowed(user_id, command_name_for_auth):
            # await send_access_denied_message(message.bot, user_id, chat_id, command_name_for_auth)
            await message.reply(_("access_denied_generic", lang)) # Simple message
            return

        # Delete previous message from this command (if any)
        await delete_previous_message(user_id, command_name_for_auth, chat_id, message.bot)

        # --- Your logic here ---
        response_text = _("my_module_response", lang, data="some data")
        # ---

        # Send the response
        sent_message = await message.answer(response_text)
        # Optional: save message ID for future deletion
        # core.shared_state.LAST_MESSAGE_IDS.setdefault(user_id, {})[command_name_for_auth] = sent_message.message_id

    # Optional: background tasks
    # def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    #     task = asyncio.create_task(my_background_job(bot))
    #     return [task]
    # async def my_background_job(bot: Bot):
    #     while True: ... await asyncio.sleep(interval)
```
3.  **Add translations:** In `core/i18n.py`, add `"btn_my_command": "My Command"` to `'en'` and `"btn_my_command": "Моя Команда"` to `'ru'`, as well as `"my_module_response": "Result: {data}"`, etc. Remember to run `sort_strings()` in `i18n.py` or sort manually.
4.  **Register module:** In `bot.py`, add `from modules import my_module` and `register_module(my_module)`.
5.  **Restart bot:** `sudo systemctl restart tg-bot`.
</details>

---

<p align="center">
  <i>Version 1.10.13 (Build 40) — Speedtest improvements (YAML, RU servers, localization), spam protection, code cleanup, and documentation updates.</i>
</p>

---

## [1.10.12] - 2025-10-22

### What's new?

#### 🚀 Added:

* **Multilingual Support (i18n):**
    * Added full support for **Russian and English languages** for all bot messages, buttons, menus, errors, and notifications.
    * Introduced a new `core/i18n.py` module to manage translations, including the `STRINGS` dictionary, functions for loading/saving settings (`load_user_settings`, `save_user_settings`), determining (`get_user_lang`) and setting (`set_user_lang`) user language, and the main translation function `get_text` (alias `_`).
    * Users can now select their language via the new "🇷🇺 Язык" / "🇬🇧 Language" button in the main menu, with settings saved in `config/user_settings.json`.
    * Added `I18nFilter` for Aiogram, allowing handlers to react to text commands regardless of language.
    * Added an inline keyboard for language selection (`get_language_keyboard`).
* **Documentation:** Added English versions `README.en.md` and `CHANGELOG.en.md` with switching links.
* **Deployment Script:** Added an English version of the deployment script `deploy_en.sh`.
* **Dependencies:** `iperf3` is now added as a dependency installed via `deploy.sh` / `deploy_en.sh`.

#### ✨ Improved:

* **Code Structure:** All user-facing strings have been externalized from module and core code into `core/i18n.py`.
* **`speedtest` Module:**
    * Completely rewritten to use `iperf3` instead of `speedtest-cli`.
    * Implemented finding the closest `iperf3` server by ping, prioritizing based on VPS country/continent.
    * Added message editing to display test status updates (locating, pinging, downloading, uploading).
    * Implemented multiple connection attempts to different servers in case of errors.
* **`traffic` Module:**
    * Added an inline "⏹ Stop" button to the traffic monitoring message.
    * Pressing the main button again no longer stops monitoring; the inline button must be used.
* **Watchdog (`watchdog.py`):**
    * All error and status messages now use the i18n system (in the default language).
    * Improved handling of network errors (`requests.exceptions.RequestException`) and JSON decoding errors when sending/editing Telegram messages.
    * Improved logic for detecting `inactive`/`failed` status from `systemctl` errors.
    * Added distinct statuses/messages for planned restarts of the bot and the watchdog itself.
* **Logging:**
    * Implemented daily log rotation for `bot.py` and `watchdog.py` logs.
    * Bot and watchdog logs are now saved in separate subdirectories (`logs/bot/`, `logs/watchdog/`).
* **`users` Module:** When deleting a user, their language and notification settings are now also removed.
* **`xray` Module:** Adjusted Xray update commands for Amnezia (added `wget`/`unzip` installation) and Marzban (added check for `.env` file existence).
* **Utilities (`core/utils.py`):** `format_traffic` and `format_uptime` functions now support i18n for units (B, KB, y, d, etc.).
* **Keyboards (`core/keyboards.py`):** All button texts are now translated into the user's language.

#### 🔧 Fixed:

* **i18n:**
    * Fixed handling of non-integer `user_id` when setting language.
    * Added error handling for string formatting and checks for translation key existence in `get_text`.
* **`users` Module:** Fixed the use of string keys (`admins`/`users`) instead of localized names in `callback_data` when changing groups.
* **Circular Imports:** Resolved potential circular import issues between `core/shared_state.py` and `core/i18n.py`.
* **Imports:** Corrected relative imports (`from . import ...`) within the core package for proper functionality.
* **`selftest` Module:** Moved the import of `_` inside the handler function to avoid potential i18n initialization issues.

---

<p align="center">
  <i>Version 1.10.12 (Build 38) — Added full support for Russian and English languages (i18n), rewrote Speedtest module using iperf3.</i>
</p>

---

## [1.10.11] - 2025-10-21

### What's new?

#### 🚀 Added:
* **"⚡️ Optimize" Button:** Added a new module (`optimize.py`) to execute a set of system cleanup and optimization commands (root admins only).
* **Log Check by Watchdog:** `watchdog.py` now checks `bot.log` for errors (`ERROR`/`CRITICAL`) after the bot service starts.
* **Update Notifications:**
    * `watchdog.py` now periodically checks GitHub Releases and notifies about new versions.
    * `bot.py` now checks for updates on startup and notifies the administrator.
* **Version Display in `deploy.sh`:** The installation/update script now shows the locally installed and latest available versions from GitHub.
* **Bot Name in Watchdog:** `watchdog.py` now uses the bot name from the `TG_BOT_NAME` variable (if set in `.env`) in its notifications.

#### ✨ Improved:
* **Watchdog Status Logic:** Improved tracking and display of bot service statuses ("Unavailable" 🔴 -> "Starting" 🟡 -> "Active" 🟢 / "Active with errors" 🟠).
* **Log Monitoring:** Reworked the `reliable_tail_log_monitor` function in `modules/notifications.py` for greater stability and elimination of `asyncio` errors.
* **`deploy.sh` Script:**
    * Improved detection of the target branch when run with an argument or via `bash <(wget ...)`.
    * Added clearer information about branches and versions in the menu.
* Minor changes in code formatting and message texts.

#### 🔧 Fixed:
* **`AssertionError: feed_data after feed_eof` Error:** Resolved an `asyncio` race condition error when reading logs (`tail -f`) in `modules/notifications.py`.
* **`NameError: name 're' is not defined` Error:** Added the missing `import re` in the `modules/optimize.py` module.
* **`unexpected EOF while looking for matching }'` Error:** Fixed bash syntax (missing parenthesis) in the `run_with_spinner` function in `deploy.sh`.
* **User Saving Error:** Corrected the user loading logic in `core/auth.py` so that added users are correctly saved to `users.json`.
* **New User Name Display:** New users are now immediately displayed with the name obtained from the Telegram API, rather than the temporary "New\_ID".

---

<p align="center">
  <i>Version 1.10.11 (Build 37) — Added optimization feature, improved Watchdog, fixed monitoring and user saving errors.</i>
</p>

---

## [1.10.10] - 2025-10-20

### 💥 Breaking Changes

-   **Complete Modularization:** The bot's code (`bot.py`) has been completely reorganized. Logic is divided into the core (`core/`) and function modules (`modules/`). The old structure is no longer supported.
-   **Reworked `deploy.sh`:** The installation/update script (`deploy.sh`) now uses `git clone` / `git reset` for file management and includes an installation integrity check. The old installation method via `curl` has been removed. **A clean (re)installation using the new `deploy.sh` is required.**

### 🚀 Added

-   **Integrity Check in `deploy.sh`:** The `deploy.sh` script now automatically checks for the presence of all necessary files (`core/`, `modules/`, `.git`, `venv/`, `.env`, `systemd` services) before displaying the menu.
-   **"Smart" Routing in `deploy.sh`:** Depending on the integrity check result (OK, PARTIAL, NOT_FOUND), `deploy.sh` directs the user to the appropriate menu (Installation, Management, or Error Message/Reinstallation suggestion).
-   **Automatic `.gitignore` Creation:** The `deploy.sh` script now creates a `.gitignore` file to protect user files (`.env`, `config/`, `logs/`, `venv/`) from being overwritten during updates via `git`.

### ✨ Improved

-   **Project Structure:** The new modular architecture (`core/`, `modules/`) significantly improves code readability, simplifies maintenance, and makes adding new features easier.
-   **Installation/Update Reliability:** Using `git` in `deploy.sh` instead of `curl` ensures all current project files are obtained and simplifies the update process.
-   **Menu Button Grouping:** Buttons in the main `ReplyKeyboard` menu are now grouped into logical categories for better navigation (although submenus were removed in favor of a single menu).

### 🔧 Fixed

-   **User ID Error in "Back to Menu" Callback:** Fixed an issue where pressing the inline "Back to Menu" button used the bot's ID instead of the user's ID, resulting in access denial.
-   **`NameError: name 'KeyboardButton' is not defined` Error:** Resolved a missing import of `KeyboardButton` in `bot.py`.
-   **`systemd` Service Parsing Error:** Corrected incorrect formatting of the `[Service]` section in `.service` files created by `deploy.sh` (all directives were on one line).

---

<p align="center">
  <i>Version 1.10.10 (Build 36) — Major refactoring to improve structure, stability, and deployment process.</i>
</p>

---

## [1.10.9] - 2025-10-19

### 🔧 Fixed (Hotfixes)

-   **Freezing on Shutdown/Restart:** Completely resolved the issue where the bot would hang for 90 seconds (`SIGTERM timeout`) when stopping the service. Implemented correct signal handling (`SIGINT`/`SIGTERM`) and shutdown sequence: stop polling, cancel background tasks (including `tail`) with timeouts, close session. Fixed `RuntimeError: Event loop is closed` and `AttributeError` during session closure.
-   **False Alert System Trigger:** The Alert system (`watchdog.py`) now correctly ignores planned restarts initiated by the bot (checks `restart_flag.txt`).
-   **Duplicate Resource Alerts:** Resource checking has been completely removed from the Alert system (`watchdog.py`) and is now performed only by the bot (`bot.py`), respecting user settings.

### 🚀 Added

-   **Log Monitoring:** The bot now monitors SSH login events (`auth.log`/`secure`) and Fail2Ban bans (`fail2ban.log`) in the background using `tail -f`.
-   **Notification Settings:**
    -   Added a "🔔 Notifications" menu allowing users to enable/disable alerts for resources (CPU/RAM/Disk), SSH logins, and Fail2Ban bans.
    -   Settings are saved in `config/alerts_config.json`.
-   **Repeat Resource Alerts:** The resource monitor now sends repeat notifications if the load remains high for longer than the set cooldown period (`RESOURCE_ALERT_COOLDOWN`).
-   **Branch Selection in `deploy.sh`:** The installation/update script now allows selecting the GitHub branch (`main` or `develop`) before downloading files.
-   **Service Status Editing:** The Alert system (`watchdog.py`) now edits a single message to display status changes: Unavailable 🔴 -> Activating 🟡 -> Active 🟢.

### ✨ Improved

-   **Button Navigation:**
    -   The "🔙 Back to Menu" button now edits the message to "Returning to menu...", providing a smoother transition.
    -   "🔙 Back" buttons in submenus use `edit_text` to navigate one step back within the same message.
    -   Added a "❌ Cancel" button for VLESS link generation.
-   **Alert System (`watchdog.py`):**
    -   Renamed to "Alert System" with a 🚨 emoji in messages.
    -   Improved service status detection (`activating`) using `systemctl status`.
    -   Standardized status texts.

---

## [1.10.8] - 2025-10-17

# 🎉 Release VPS Manager Bot v1.10.8 (Build 31)

We are pleased to introduce a new version of our bot! This release focuses on intelligent automation and significantly improving the user experience during installation and usage.

---

### 🚀 What's new

-   **X-ray Panel Support:** The bot now automatically detects popular control panels (Marzban, Amnezia) and can update their X-ray Core directly from the menu! *(Note: 3x-UI functionality was not explicitly added in the previously provided code)*

### ✨ Improvements

-   **New Graphical Installer:** The `deploy.sh` script has been completely redesigned. Installation, updating, and removal of the bot now occur in a beautiful and intuitive interactive mode with colors and animations.

### 🔧 Fixes

-   **Correct Restart:** Fixed the issue where the bot would get "stuck" on the message «Bot is restarting». You will now always receive a notification upon successful completion of the process.

---

Thank you for using our bot! We hope you enjoy the new features. Please use our improved script for installation or updating.

---
---

## [1.10.7] - 2025-10-15

# 🎉 First release: Telegram bot for managing your VPS!

Hello everyone!

I am pleased to present the first public release of a multifunctional Telegram bot for monitoring and administering your VPS/VDS server. This project was created to make server management as convenient, fast, and secure as possible, allowing key operations to be performed directly from the messenger.

The main feature of the project is not only the functional bot but also the powerful `deploy.sh` script, which makes installing, configuring, and maintaining the bot incredibly simple.

---

### 🚀 Key bot features (v1.10.7)

The bot provides different levels of access to commands depending on the user's role and the installation mode.

#### For all authorized users:
* 📊 **System Information:** View CPU, RAM, disk load, and server uptime.
* 📡 **Traffic Monitoring:** Display total and current network traffic in real time.
* 🆔 **Get ID:** A quick way to find out your Telegram ID for authorization.

#### For administrators:
* 👤 **User Management:** Add, remove, and assign roles (Admin/User) directly through the bot interface.
* 🔗 **VLESS Generator:** Create VLESS links and QR codes by sending an X-ray JSON config.
* 🚀 **Speed Test:** Run Speedtest to check the server's internet connection speed.
* 🔥 **Top Processes:** View the list of most resource-intensive processes.
* 🩻 **Update X-ray:** Quickly update the X-ray core in a Docker container.

#### Features available only in `Root` mode:
* 🔄 **Server Management:** Safely reboot the VPS and restart the bot itself.
* 🛡️ **Security:** View Fail2Ban logs and recent successful SSH logins.
* 📜 **System Logs:** Display recent events from the system journal.
* ⚙️ **System Update:** Run a full package update on the server (`apt update && apt upgrade`).

---

### 🛠️ Management script (`deploy.sh`) (v1.10.7)

Installing and managing the bot has never been easier!

* **All-in-One Menu:** Install, update, check integrity, and remove the bot through a convenient console menu.
* **Two Installation Modes:**
    * **Secure:** The bot runs as a separate system user with limited privileges. Safe and ideal for most tasks.
    * **Root:** The bot gets full system control, unlocking access to all administrative commands.
* **Automatic Setup:** The script automatically creates a `systemd` service for auto-start and reliable bot operation.
* **Dependency Installation:** The script installs all necessary software, including Python, `venv`, Fail2Ban, and Speedtest-CLI.

---

### 📝 Future plans (as of v1.10.7)
* Expand the list of supported commands and system metrics.
* Add Docker support for deploying the bot itself.
* More flexible role and permission system.

I welcome your feedback, suggestions, and bug reports in the **Issues** section on GitHub!

Thank you for your interest!

**Full Changelog**: https://github.com/jatixs/tgbotvpscp/blob/main/CHANGELOG.md
