<p align="center">
  English Version | <a href="README.md">Русская Версия</a>
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b >v1.10.14</b> — a reliable Telegram bot for monitoring and managing your VPS or dedicated server, now with a <b>modular architecture</b>, support for <b>multiple languages</b>, and <b>Docker</b> deployment.
</p>

<p align="center">
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.10.14-blue?style=flat-square" alt="Version 1.10.14"/></a>
  <a href="CHANGELOG.en.md"><img src="https://img.shields.io/badge/build-41-purple?style=flat-square" alt="Build 41"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+"/></a>
  <a href="https://choosealicense.com/licenses/gpl-3.0/"><img src="https://img.shields.io/badge/license-GPL--3.0-lightgrey?style=flat-square" alt="License GPL-3.0"/></a>
  <a href="https://github.com/aiogram/aiogram"><img src="https://img.shields.io/badge/aiogram-3.x-orange?style=flat-square" alt="Aiogram 3.x"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-required-blueviolet?style=flat-square" alt="Docker"/></a>
  <a href="https://releases.ubuntu.com/focal/"><img src="https://img.shields.io/badge/platform-Ubuntu%2020.04%2B-important?style=flat-square" alt="Platform Ubuntu 20.04+"/></a>
  <a href="https://github.com/jatixs/tgbotvpscp/actions/workflows/security.yml/"><img src="https://github.com/jatixs/tgbotvpscp/actions/workflows/security.yml/badge.svg" alt="Security Scan"/></a>
</p>

---

## 📘 Table of Contents
1. [Project Description](#-project-description)
2. [Key Features](#-key-features)
3. [Deployment on VPS (Quick Start)](#-deployment-on-vps-quick-start)
   - [Preparation](#1-preparation)
   - [Running Installation / Management](#2-running-installation--management)
   - [Verification and Completion](#3-verification-and-completion)
   - [Useful Commands](#-useful-commands)
4. [Project Structure](#️-project-structure)
5. [Security](#-security)
6. [Adding Your Own Module](#-adding-your-own-module)
7. [Author](#-author)

---

## 🧩 Project Description

**VPS Manager Telegram Bot** is a Telegram bot for remote monitoring and management of your **Virtual Private Server (VPS)** or dedicated server. The bot provides a convenient interface via Telegram for performing administrative tasks, checking system status, and managing users.

The project has a **modular structure**, which allows for easy addition, modification, or disabling of features, making it flexible and easy to maintain.

---

### 🐍 Development

It is developed in **Python** using the **aiogram (v3)** framework and is optimized for deployment as a **systemd service** or in **Docker containers** with a separate **watchdog service (Alert system)** for enhanced reliability.

---

## ⚡ Key Features

* 🐳 **Full Docker Support:** One-click installation in isolated `docker-compose` containers (`secure` and `root` modes).
* 🌐 **Multilingual (i18n):** Full support for Russian and English with user selection.
* 🏗️ **Modular Architecture:** Easy extension and customization of functionality (see [guide](#-adding-your-own-module)).
* 💻 **Resource Monitoring:** Check CPU, RAM, Disk, Uptime (works correctly in Docker-root).
* 📡 **Network Statistics:** Total traffic and real-time connection speed (with spam protection).
* 🔔 **Flexible Notifications:** Configure alerts for resource threshold breaches, SSH logins, and Fail2Ban bans.
* 🧭 **Administration:** Update VPS (`apt upgrade`), optimize system, reboot server, restart bot service/container.
* ✨ **Smart Installer/Updater (`deploy_en.sh`):**
    * **Interactive Menu:** Installation, update, integrity check, and removal.
    * **Installation Mode Selection:** `Systemd` (classic) or `Docker` (isolated).
    * **Management via `git`:** Reliable code retrieval from GitHub.
    * **Integrity Check:** Automatic installation diagnosis (`systemd` or `docker`) before showing the menu.
    * **Data Protection:** Automatic `.gitignore` creation to preserve `.env`, `config/`, `logs/`.
* 🚀 **Diagnostics:** Ping check, run speed test (**iperf3**), view top processes by CPU.
* 🛡️ **Security and Logs:** View recent SSH logins and blocked IPs (Fail2Ban) (works correctly in Docker-root).
* 🔑 **VLESS Management:** Generate links and QR codes from Xray JSON configuration (Reality).
* ⚙️ **X-ray Update:** Automatic detection and update of X-ray Core for Marzban and Amnezia panels.
* 👥 **Flexible Access Control:** Add/remove users and assign groups (Admins/Users).
* ✨ **Reliability:** Alert system (`watchdog.py`) monitors the main bot process (both `systemd` and `docker`) and restarts it in case of failure.

---

## 🚀 Deployment on VPS (Quick Start)

To deploy the bot on your VPS, you need **Ubuntu 20.04+** or a similar system with `sudo` access.

### 1. Preparation

1.  Get your Telegram bot token from **[@BotFather](https://t.me/BotFather)**.
2.  Find your numeric **User ID** in Telegram (e.g., using the [@userinfobot](https://t.me/userinfobot) bot).
3.  Ensure `curl` and `git` are installed on your VPS.

---

### 2. Running Installation / Management

Copy and execute the following command. It will download the **latest version** of the `deploy_en.sh` script from the `main` branch and run it:

```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy_en.sh)
```

The script will **first check the integrity** of an existing installation:

* **If the bot is not installed or corrupted:** You will be prompted to choose an installation mode (`Systemd - Secure/Root` or `Docker - Secure/Root`).
* **If the installation is OK:** You will see the management menu (Update, Reinstall, Remove).

During the **first installation** or **reinstallation**, the script will ask you to enter:

* `Telegram Bot Token`
* `Telegram User ID` (main administrator)
* `Telegram Username` (optional)
* `Bot Name` (optional, for watchdog notifications)

The script will automatically install all system dependencies (including `docker`, `docker-compose`, `python3-venv`, `iperf3`), clone the repository (`git clone`), configure `venv`/`docker-compose`, Python dependencies, `.env`, `.gitignore`, and `systemd` services / `docker` containers.

---

### 3. Verification and Completion

After the script finishes successfully:

* The bot will be running as a **systemd service** `tg-bot.service` (for Systemd) or as **docker containers** (for Docker).
* The Alert system will be running (`tg-watchdog.service` or `tg-watchdog` container).
* Send the `/start` command to your bot in Telegram. The main menu should appear.

---

### 🧰 Useful Commands

| Command (Systemd) | Command (Docker) | Description |
| :--- | :--- | :--- |
| `sudo systemctl status tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml ps` | Bot status |
| `sudo systemctl restart tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml restart bot-root` | Restart bot |
| `sudo journalctl -u tg-bot -f` | `docker compose -f /opt/tg-bot/docker-compose.yml logs -f bot-root` | Bot logs (live) |
| `sudo systemctl status tg-watchdog` | `docker compose -f /opt/tg-bot/docker-compose.yml ps` | Alert system status |
| `sudo journalctl -u tg-watchdog -f` | `docker compose -f /opt/tg-bot/docker-compose.yml logs -f watchdog` | Alert system logs (live) |

*(Replace `bot-root` with `bot-secure` if you chose Docker Secure mode)*

---

## ⚙️ Project Structure
```
/opt/tg-bot/          # Installation directory (default)
├── bot.py            # Entry point, module loader
├── watchdog.py       # Alert system code (monitoring)
├── deploy.sh         # Installation/management script (Русский)
├── deploy_en.sh      # Installation/management script (English)
├── requirements.txt  # Python dependencies
├── Dockerfile        # Docker build instructions
├── docker-compose.yml # Docker container startup config
├── .env              # Environment variables (TOKEN, ID, etc.) - DO NOT COMMIT!
├── .gitignore        # File to exclude .env, config/, logs/, venv/ from git
├── venv/             # Python virtual environment (for Systemd)
│
├── core/             # Bot core: common functions and utilities
│   ├── config.py     # Configuration, constants, paths
│   ├── auth.py       # Authorization, user management
│   ├── keyboards.py  # Keyboard generation
│   ├── messaging.py  # Sending/deleting messages, alerts
│   ├── shared_state.py # Managing "global" variables
│   ├── i18n.py       # Localization (translations)
│   ├── middlewares.py # Middlewares (e.g., for throttling)
│   └── utils.py      # Helper functions (incl. get_host_path)
│
├── modules/          # Modules with logic for specific functions
│   ├── selftest.py   # Example: "Server Info" module
│   ├── traffic.py    # Example: "Network Traffic" module
│   └── ...           # Other modules...
│
├── config/           # Configuration files (created automatically)
│   ├── users.json
│   ├── alerts_config.json
│   ├── user_settings.json # User language settings
│   └── ..._flag.txt
│
└── logs/             # Log files (created automatically)
    ├── bot/          # Main bot logs (with rotation)
    │   └── bot.log...
    └── watchdog/     # Alert system logs (with rotation)
        └── watchdog.log...
```
---
## 🔒 Security

🔄 **Auto-start and restart:** `systemd` services ensure reliable operation. <br>
🛡️ **Alert system:** `watchdog.py` monitors the bot and notifies about failures. <br>
👤 **User isolation (Secure mode):** Bot runs as the `tgbot` user. <br>
🔐 **Confidentiality:** `.env` with `600` permissions, protected by `.gitignore`. <br>
👮 **Access control:** Users and groups in `users.json`. <br>
⏳ **Spam protection:** Built-in button press throttling mechanism. <br>

---

<details>
<summary><h2>🧩 Adding Your Own Module</h2></summary>

Want to add your own command or feature to the bot? It's easy thanks to the modular architecture!

1.  **Create a file:** In the `modules/` directory, create a new Python file (e.g., `my_module.py`).
2.  **Write the code:** Implement the necessary logic in this file. At a minimum, you'll need:
    * **Button localization key:** Define a unique key for the button text (e.g., `BUTTON_KEY = "btn_my_command"`).
    * **`get_button()` function:** Returns a `KeyboardButton` with text obtained via `_(BUTTON_KEY, config.DEFAULT_LANGUAGE)`.
    * **`register_handlers(dp: Dispatcher)` function:** Registers your message/callback handlers with the Aiogram Dispatcher. Use `dp.message(I18nFilter(BUTTON_KEY))(my_command_handler)` to react to the button press.
    * **Asynchronous handler:** A function (e.g., `async def my_command_handler(message: types.Message):`) that will be executed when the button is pressed. Remember to import `_`, `get_user_lang`, `is_allowed`, `delete_previous_message`, and other utilities from `core`.
3.  **Add translations:** In the `core/i18n.py` file, add your `BUTTON_KEY` and other necessary strings for Russian ('ru') and English ('en'). Don't forget to sort the dictionary after adding (the sorting command is called at the end of `i18n.py`).
4.  **Register the module:** In the `bot.py` file, import your module (e.g., `from modules import my_module`) and add it to the list of loaded modules in the `load_modules()` function, specifying the required access level (`admin_only=True` or `root_only=True` if needed).
```python
    # /opt/tg-bot/bot.py
    ...
    # Import modules
    from modules import (
        selftest, traffic, ..., my_module # Add your module
    )
    ...
    # Module toggles (optional)
    ENABLE_MY_MODULE = True
    ...
    def load_modules():
        ...
        if ENABLE_MY_MODULE:
             # Specify necessary access flags
             register_module(my_module, admin_only=False, root_only=False)
        ...
```

5.  **Restart the bot:** `sudo systemctl restart tg-bot`
</details>

Your new button and function will appear in the main menu! See existing modules (`modules/uptime.py`, `modules/top.py`, etc.) for detailed examples.

---

## 👤 Author
**Version:** 1.10.14 (Build 41) <br>
**Author:** Jatix <br>
📜 **License:** GPL-3.0 license <br>
