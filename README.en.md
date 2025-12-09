<p align="center">
  <a href="README.md">Русская Версия</a> | English Version
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b >v1.13.2</b> — a powerful Telegram bot for monitoring and managing your <b>server network</b>. Now powered by <b>SQLite</b> and a fully <b>asynchronous core</b> (AsyncIO). Features <b>multi-node support</b>, a web interface, and full <b>Docker</b> integration.
</p>

<p align="center">
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.13.2-blue?style=flat-square" alt="Version 1.13.2"/></a>
  <a href="CHANGELOG.en.md"><img src="https://img.shields.io/badge/build-54-purple?style=flat-square" alt="Build 54"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+"/></a>
  <a href="https://choosealicense.com/licenses/gpl-3.0/"><img src="https://img.shields.io/badge/license-GPL--3.0-lightgrey?style=flat-square" alt="License GPL-3.0"/></a>
  <a href="https://github.com/aiogram/aiogram"><img src="https://img.shields.io/badge/aiogram-3.x-orange?style=flat-square" alt="Aiogram 3.x"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-required-blueviolet?style=flat-square" alt="Docker"/></a>
  <a href="https://releases.ubuntu.com/focal/"><img src="https://img.shields.io/badge/platform-Ubuntu%2020.04%2B-important?style=flat-square" alt="Platform Ubuntu 20.04+"/></a>
  <a href="https://github.com/jatixs/tgbotvpscp/actions/workflows/security.yml/"><img src="https://github.com/jatixs/tgbotvpscp/actions/workflows/security.yml/badge.svg" alt="Security Scan"/></a>
</p>

---

## 📘 Table of Contents
1. [Description](#-description)
2. [Key Features](#-key-features)
3. [Deployment](#-deployment-quick-start)
   - [Preparation](#1-preparation)
   - [Install Agent (Master)](#2-installing-the-agent-main-bot)
   - [Connect Nodes (Clients)](#3-connecting-nodes-clients)
   - [Commands](#-useful-commands)
4. [Project Structure](#️-project-structure)
5. [Security](#-security)
6. [Custom Modules](#-adding-your-own-module)
7. [Author](#-author)

---

## 🧩 Description

**VPS Manager Telegram Bot** is a comprehensive solution for server administration via Telegram. It has evolved into a professional infrastructure management system, allowing you to control both the main server (**Agent**) and a network of remote nodes (**Nodes**) via a single interface.

The project operates in two modes:
1.  **Agent (Bot):** The main control center with Telegram UI, async API, SQLite database, and Web Admin Panel.
2.  **Node (Client):** A lightweight client (`tg-node`) for remote VPS. Transmits telemetry and executes commands.

---

## ⚡ Key Features

### 🚀 Performance & Reliability
* **Async Core:** Fully powered by `aiohttp` and `aiosqlite`. No blocking operations during network requests or DB writes.
* **SQLite Database:** Reliable storage for node configs, tasks, and metric history. Auto-migration from JSON included.
* **Security:** Shell Injection protection (`shlex`), server-side sessions, Rate Limiter, and XSS escaping.

### 🖥 Multi-server (Nodes)
* **Unified Center:** Manage unlimited servers.
* **Monitoring:** Status (Online/Offline), ping, uptime, and resources for all nodes.
* **Remote Control:** `Reboot`, `Speedtest`, `Traffic`, `Top` on any node.
* **Web Status Page:** HTML dashboard (`http://IP:8080`) with real-time monitoring.

### 🛠 Core Functionality
* 🐳 **Full Docker Support:** One-click install (`secure` and `root` modes).
* 🌐 **Multilingual (i18n):** English and Russian support.
* 💻 **Resources:** CPU, RAM, Disk, Uptime monitoring.
* 📡 **Network:** Traffic and connection speed (iperf3) stats.
* 🔔 **Smart Alerts:** Notifications for resources, SSH logins, Fail2Ban bans, and **Node Downtime**.
* ✨ **Smart Installer:** Interactive `deploy.sh` script.
* 🚀 **Diagnostics:** Ping, Speedtest, Top processes.
* 🛡️ **Security:** SSH logs and Fail2Ban integration.
* ⚙️ **X-ray:** Update cores for Marzban/Amnezia panels.

---

## 🚀 Deployment (Quick Start)

Requires **Ubuntu 20.04+** and `sudo` access.

### 1. Preparation

1.  Get a bot token from **[@BotFather](https://t.me/BotFather)**.
2.  Get your **User ID** (e.g., via [@userinfobot](https://t.me/userinfobot)).
3.  Ensure `curl` and `git` are installed.

---

### 2. Installing the Agent (Main Bot)

Run on your main server:

```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy_en.sh)
````

1.  Select install mode (Recommended: **Docker - Secure**).
2.  Enter **Bot Token** and **Admin ID**.
3.  The bot will start the API server on port `8080`.

-----

### 3. Connecting Nodes (Clients)

To connect a remote server:

1.  **In Telegram Bot (Master):**
      * Go to **🖥 Nodes** -> **➕ Add Node**.
      * Enter a name. Get the **Token**.
2.  **On Remote Server:**
      * Run the installer:
        ```bash
        bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy_en.sh)
        ```
      * Select **8) Install NODE (Client)**.
      * Enter:
          * **Agent URL:** Master bot address (e.g. `http://1.2.3.4:8080`).
          * **Token:** The token from the bot.

The agent will install as `tg-node` service and appear in your bot.

-----

### 🧰 Useful Commands

#### 🕹 Process Management

| Action | Systemd (Classic) | Docker (Containers) |
| :--- | :--- | :--- |
| **Bot Status** | `sudo systemctl status tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml ps` |
| **Watchdog Status** | `sudo systemctl status tg-watchdog` | *Running inside watchdog container* |
| **Restart Bot** | `sudo systemctl restart tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml restart bot-secure` (or `bot-root`) |
| **Stop** | `sudo systemctl stop tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml stop` |
| **Start** | `sudo systemctl start tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml up -d` |

#### 📜 Logs & Debug

| Action | Systemd | Docker |
| :--- | :--- | :--- |
| **Bot Logs (Live)** | `sudo journalctl -u tg-bot -f` | `docker compose -f /opt/tg-bot/docker-compose.yml logs -f bot-secure` |
| **Watchdog Logs** | `sudo journalctl -u tg-watchdog -f` | `docker compose -f /opt/tg-bot/docker-compose.yml logs -f watchdog` |
| **Errors (grep)** | `grep "ERROR" /opt/tg-bot/logs/bot/bot.log` | *Same (log files are mounted to host)* |

#### 💾 Database & Maintenance

| Action | Command (Run in `/opt/tg-bot/`) |
| :--- | :--- |
| **Backup DB** | `cp config/nodes.db config/nodes.db.bak_$(date +%F)` |
| **Manual Update** | `git pull && source venv/bin/activate && pip install -r requirements.txt && sudo systemctl restart tg-bot` |
| **Reset Web Pass** | *Delete the `password_hash` line for the admin in `config/users.json` and restart the bot* |

#### 🖥 For Node (Client)

| Action | Command |
| :--- | :--- |
| **Restart** | `sudo systemctl restart tg-node` |
| **View Logs** | `sudo journalctl -u tg-node -f` |
| **Check Config** | `cat /opt/tg-bot/.env` |

*(Use `bot-secure` instead of `bot-root` for Docker Secure mode)*

-----

## ⚙️ Project Structure

```
/opt/tg-bot/
├── bot.py            # Master Entry Point
├── watchdog.py       # Alert System
├── deploy.sh         # Installer
├── requirements.txt  # Deps (aiosqlite, aiohttp...)
├── Dockerfile        # Docker build
├── docker-compose.yml
├── .env              # Config
│
├── config/
│   ├── nodes.db      # [NEW] SQLite Database
│   ├── users.json    # Users config
│   └── ...
│
├── node/             # Client Side
│   └── node.py       # Agent script
│
├── core/             # Core Logic
│   ├── server.py     # Async Web Server
│   ├── nodes_db.py   # [NEW] Async DB Manager
│   ├── utils.py      # Async Utils
│   └── ...
│
├── modules/          # Features
    ├── nodes.py      # Node Management
    ├── speedtest.py  # Async Speedtest
    └── ...
```

-----

## 🔒 Security

  * **Isolation:** Secure mode runs as `tgbot` user.
  * **Data Protection:** SQLite DB, server-side sessions, Rate Limiting.
  * **Injection Protection:** `shlex` command escaping.
  * **Tokens:** Unique auth tokens for each node.

<details>
<summary><h2>🧩 Adding Your Own Module</h2></summary>

1.  **File:** Create `modules/my_module.py`.
2.  **Code:** Use `BUTTON_KEY` and `register_handlers(dp)`.
3.  **i18n:** Add strings to `core/i18n.py`.
4.  **Register:** Import in `bot.py` and call `register_module()`.
5.  **Restart:** `sudo systemctl restart tg-bot`.

**[Full-format instructions](/custom_module_en.md)**.
</details>

-----

## 👤 Author

**Version:** 1.13.2 (Build 54) <br>
**Author:** Jatix <br>
📜 **License:** GPL-3.0 <br>
