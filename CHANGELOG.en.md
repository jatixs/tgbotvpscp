<p align="center">
  English Version | <a href="CHANGELOG.md">Русская Версия</a>
</p>

<h1 align="center">📝 Telegram VPS Management Bot — Changelog</h1>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.10.12-blue?style=flat-square" alt="Version 1.10.12"/>
  <img src="https://img.shields.io/badge/build-38-purple?style=flat-square" alt="Build 38"/>
  <img src="https://img.shields.io/badge/date-October%202025-green?style=flat-square" alt="Date October 2025"/>
  <img src="https://img.shields.io/badge/status-stable-success?style=flat-square" alt="Status Stable"/>
</p>

---

## [1.10.12] - 2025-10-22

### What's new?

#### 🚀 Added:
* **Multilingual Support (i18n):**
    * Added full support for Russian and English languages for all bot messages, including buttons, menus, errors, and notifications.
    * Users can now select their preferred language using the new "🇷🇺 Язык" / "🇬🇧 Language" button in the main menu.
    * Language settings are saved for each user in `config/user_settings.json`.
    * Created a new module `core/i18n.py` to manage translations and language settings.
* **Updated Documentation:** Added English versions of `README.md` and `CHANGELOG.md` with links to switch between languages.

#### ✨ Improved:
* **Code Structure:** All user-facing text strings have been moved from the modules and core code into the central translation dictionary `core/i18n.py`, simplifying the addition of new languages and text editing.
* **Watchdog Error Handling:** Improved error handling and message output in `watchdog.py` using the i18n system (in the default language).
* **Navigation:** Minor improvements to message deletion logic and returning to the main menu in some modules (`traffic`, `vless`).

#### 🔧 Fixed:
* **Watchdog:** Fixed potential JSON decoding error when receiving response from Telegram API. Specified exception types for network errors. Corrected `inactive`/`failed` state detection logic.
* **i18n:** Fixed handling of non-integer `user_id` and string formatting errors. Added checks for translation key existence.

---

<p align="center">
  <i>Version 1.10.12 (Build 38) — Added full support for Russian and English languages (i18n).</i>
</p>

---
## [1.10.12] - 2025-10-22

### What's new?

#### 🚀 Added:
* **Multilingual Support (i18n):**
    * Added full support for Russian and English languages for all bot messages, including buttons, menus, errors, and notifications.
    * Users can now select their preferred language using the new "🇷🇺 Язык" / "🇬🇧 Language" button in the main menu.
    * Language settings are saved for each user in `config/user_settings.json`.
    * Created a new module `core/i18n.py` to manage translations and language settings.
* **Updated Documentation:** Added English versions of `README.md` and `CHANGELOG.md` with links to switch between languages.

#### ✨ Improved:
* **Code Structure:** All user-facing text strings have been moved from the modules and core code into the central translation dictionary `core/i18n.py`, simplifying the addition of new languages and text editing.
* **Watchdog Error Handling:** Improved error handling and message output in `watchdog.py` using the i18n system (in the default language).
* **Navigation:** Minor improvements to message deletion logic and returning to the main menu in some modules (`traffic`, `vless`).

#### 🔧 Fixed:
* **Watchdog:** Fixed potential JSON decoding error when receiving response from Telegram API. Specified exception types for network errors. Corrected `inactive`/`failed` state detection logic.
* **i18n:** Fixed handling of non-integer `user_id` and string formatting errors. Added checks for translation key existence.

---

<p align="center">
  <i>Version 1.10.12 (Build 38) — Added full support for Russian and English languages (i18n).</i>
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