<p align="center">
  English Version | <a href="README.md">Русская Версия</a>
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b >v1.10.12</b> — a reliable Telegram bot for monitoring and managing your VPS or dedicated server, now with a <b>modular architecture</b>, support for <b>multiple languages</b>, and an improved deployment process.
</p>

<p align="center">
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.10.12-blue?style=flat-square" alt="Version 1.10.12"/></a>
  <a href="CHANGELOG.en.md"><img src="https://img.shields.io/badge/build-38-purple?style=flat-square" alt="Build 38"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+"/></a>
  <a href="https://choosealicense.com/licenses/gpl-3.0/"><img src="https://img.shields.io/badge/license-GPL--3.0-lightgrey?style=flat-square" alt="License GPL-3.0"/></a>
  <a href="https://github.com/aiogram/aiogram"><img src="https://img.shields.io/badge/aiogram-3.x-orange?style=flat-square" alt="Aiogram 3.x"/></a>
  <a href="https://releases.ubuntu.com/focal/"><img src="https://img.shields.io/badge/platform-Ubuntu%2020.04%2B-important?style=flat-square" alt="Platform Ubuntu 20.04+"/></a>
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
6. [Author](#-author)

---

## 🧩 Project Description

**VPS Manager Telegram Bot** is a Telegram bot for remote monitoring and management of your **Virtual Private Server (VPS)** or dedicated server. The bot provides a convenient interface via Telegram for performing administrative tasks, checking system status, and managing users.

The project has a **modular structure**, which allows for easy addition, modification, or disabling of features, making it flexible and easy to maintain.

---

### 🐍 Development

It is developed in **Python** using the **aiogram (v3)** framework and is optimized for deployment as a **systemd service with auto-start** and a separate **watchdog service (Alert system)** for enhanced reliability.

---

## ⚡ Key Features

* 🌐 **Multilingual (i18n):** Full support for Russian and English with user selection.
* 🏗️ **Modular Architecture:** Easy extension and customization of functionality.
* 💻 **Resource Monitoring:** Check CPU, RAM, Disk, Uptime.
* 📡 **Network Statistics:** Total traffic and real-time connection speed.
* 🔔 **Flexible Notifications:** Configure alerts for resource threshold breaches, SSH logins, and Fail2Ban bans.
* 🧭 **Administration:** Update VPS (`apt upgrade`), optimize system, reboot server, restart bot service.
* ✨ **Smart Installer/Updater (`deploy.sh`/`deploy_en.sh`):**
    * **Interactive Menu:** Installation, update, integrity check, and removal.
    * **Management via `git`:** Reliable code retrieval from GitHub (including `core/` and `modules/`).
    * **Integrity Check:** Automatic installation diagnosis before showing the menu.
    * **Branch Selection:** Install/update from `main` or another specified branch.
    * **Data Protection:** Automatic `.gitignore` creation to preserve `.env`, `config/`, `logs/`.
* 🚀 **Diagnostics:** Ping check, run speed test (**iperf3**), view top processes by CPU.
* 🛡️ **Security and Logs:** View recent SSH logins and blocked IPs (Fail2Ban).
* 🔑 **VLESS Management:** Generate links and QR codes from Xray JSON configuration (Reality).
* ⚙️ **X-ray Update:** Automatic detection and update of X-ray Core for Marzban and Amnezia panels.
* 👥 **Flexible Access Control:** Add/remove users and assign groups (Admins/Users).
* ✨ **Reliability:** Alert system (`watchdog.py`) monitors the main bot process and restarts it in case of failure.

---

## 🚀 Deployment on VPS (Quick Start)

To deploy the bot on your VPS, you need **Ubuntu 20.04+** or a similar system with `sudo` access.

### 1. Preparation

1.  Get your Telegram bot token from **[@BotFather](https://t.me/BotFather)**.
2.  Find your numeric **User ID** in Telegram (e.g., using the [@userinfobot](https://t.me/userinfobot) bot).
3.  Ensure `curl` and `git` are installed on your VPS:
    ```bash
    sudo apt update && sudo apt install -y curl git
    ```

---

### 2. Running Installation / Management

Copy and execute the following command. It will download the **latest version** of the `deploy.sh` script from the `main` branch and run it:

```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy_en.sh)
```
The script will **first check the integrity** of an existing installation:
* **If the bot is not installed or corrupted:** You will be prompted to choose an installation mode (`Secure` or `Root`).
* **If the installation is OK:** You will see the management menu (Update, Reinstall, Remove).

During the **first installation** or **reinstallation**, the script will ask you to enter:
* `Telegram Bot Token`
* `Telegram User ID` (main administrator)
* `Telegram Username` (optional)

The script will automatically install dependencies, clone the repository from the correct branch (`git clone`), configure `venv`, `.env`, `.gitignore`, and `systemd` services.

---

### 3. Verification and Completion

After the script finishes successfully:
* The bot will be running as a **systemd service** `tg-bot.service`.
* The Alert system will be running as `tg-watchdog.service`.
* Send the `/start` command to your bot in Telegram. The main menu should appear.

---

### 🧰 Useful Commands

| Command                               | Description                 |
| :------------------------------------ | :-------------------------- |
| `sudo systemctl status tg-bot`        | Bot status                  |
| `sudo systemctl restart tg-bot`       | Restart bot                 |
| `sudo journalctl -u tg-bot -f -n 50`    | View bot logs (live)        |
| `sudo systemctl status tg-watchdog`   | Alert system status         |
| `sudo systemctl restart tg-watchdog`  | Restart Alert system      |
| `sudo journalctl -u tg-watchdog -f -n 50` | View Alert system logs (live) |



---

## ⚙️ Project Structure

```
/opt/tg-bot/          # Installation directory (default)
├── bot.py            # Entry point, module loader
├── watchdog.py       # Alert system code (monitoring)
├── deploy.sh         # Installation/management script (Русский)
├── deploy_en.sh      # Installation/management script (English)
├── requirements.txt  # Python dependencies
├── .env              # Environment variables (TOKEN, ID, etc.) - DO NOT COMMIT!
├── .gitignore        # File to exclude .env, config/, logs/, venv/ from git
├── venv/             # Python virtual environment
│
├── core/             # Bot core: common functions and utilities
│   ├── config.py     # Configuration, constants, paths
│   ├── auth.py       # Authorization, user management
│   ├── keyboards.py  # Keyboard generation
│   ├── messaging.py  # Sending/deleting messages, alerts
│   ├── shared_state.py # Managing "global" variables
│   ├── i18n.py       # Localization (translations)
│   └── utils.py      # Helper functions
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

---

## 👤 Author
**Version:** 1.10.12 (Build 38) <br>
**Author:** Jatix <br>
📜 **License:** GPL-3.0 license <br>
