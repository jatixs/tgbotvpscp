<p align="center">
  <a href="README.md">Русская Версия</a> | English Version
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b >v1.11.0</b> — a powerful Telegram bot for monitoring and managing your <b>server network</b>. Now featuring <b>Agent-Node</b> architecture, multi-server support, a web interface, and full <b>Docker</b> support.
</p>

<p align="center">
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.11.0-blue?style=flat-square" alt="Version 1.11.0"/></a>
  <a href="CHANGELOG.en.md"><img src="https://img.shields.io/badge/build-42-purple?style=flat-square" alt="Build 42"/></a>
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
3. [Deployment (Quick Start)](#-deployment-quick-start)
   - [Installing the Agent (Main Bot)](#1-installing-the-agent-main-bot)
   - [Connecting Nodes (Clients)](#2-connecting-nodes-clients)
   - [Useful Commands](#-useful-commands)
4. [Project Structure](#️-project-structure)
5. [Security](#-security)
6. [Adding Your Own Module](#-adding-your-own-module)
7. [Author](#-author)

---

## 🧩 Project Description

**VPS Manager Telegram Bot** is a comprehensive solution for server administration via Telegram. The bot has evolved into a centralized infrastructure management system, allowing you to manage both the main server (**Agent**) and a network of remote nodes (**Nodes**) through a single interface.

The project has a modular structure and supports two modes of operation:
1.  **Agent (Bot):** The main control center with a Telegram interface, Web API, and server database. Deployed on the main server.
2.  **Node (Client):** A lightweight client (`tg-node`) installed on remote VPS. It transmits statistics (heartbeats) to the Agent and executes its commands.

---

## ⚡ Key Features

### 🖥 Multi-server (Nodes)
* **Unified Center:** Manage an unlimited number of servers from a single chat.
* **Monitoring:** View status (Online/Offline), ping, uptime, and resources of all connected nodes in real-time.
* **Remote Control:** Execute `Reboot`, `Speedtest`, `Traffic`, `Top` on any connected node.
* **Web Status Page:** A stylish HTML page (at `http://IP:8080`) monitoring the Agent and active nodes status.

### 🛠 Core Functionality
* 🐳 **Full Docker Support:** One-click installation in isolated `docker-compose` containers (`secure` and `root` modes).
* 🌐 **Multilingual (i18n):** Full support for Russian and English languages.
* 💻 **Resource Monitoring:** CPU, RAM, Disk, Uptime (works correctly in Docker-root).
* 📡 **Network Statistics:** Total traffic and connection speed (iperf3) in real-time.
* 🔔 **Flexible Notifications:** Configure alerts for resource thresholds, SSH logins, Fail2Ban bans, and **Node Downtime**.
* ✨ **Smart Installer (`deploy.sh`):** Interactive menu for installing the Agent and Nodes, automatic generation of tokens and services.
* 🚀 **Diagnostics:** Ping, Speedtest, Process Top.
* 🛡️ **Security:** View recent SSH logins and blocked IPs (Fail2Ban).
* 🔑 **VLESS Management:** Generate links and QR codes from Xray JSON configuration (Reality).
* ⚙️ **X-ray Update:** Automatic detection and update of cores for Marzban and Amnezia panels.

---

## 🚀 Deployment (Quick Start)

Deployment requires **Ubuntu 20.04+** (or Debian 11+) with `sudo` access.

### 1. Installing the Agent (Main Bot)

Run this command on the server that will be the "control center" (**Agent**):

```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh)
````

1.  The script will check the system. If the bot is not installed, select the installation mode:
      * **1-4) AGENT ...** (Systemd or Docker)
2.  Enter your **Bot Token** and your **Telegram ID**.
3.  After installation, the Agent will start the API web server on port `8080` (ensure the port is open in your firewall).

-----

### 2. Connecting Nodes (Clients)

This step is performed on remote servers you want to manage.

1.  **In the Telegram Bot (on the Agent):**
      * Open the menu **🖥 Nodes** -> **➕ Add Node**.
      * Enter a name for the server. The bot will generate a unique **Token**.
2.  **On the Remote Server:**
      * Run the same installation script:
        ```bash
        bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh)
        ```
      * In the menu, select option **8) Install NODE (Client)**.
      * The script will ask for:
          * **Agent URL:** The address of your Agent (e.g., `http://1.2.3.4:8080`).
          * **Token:** The token obtained from the bot.

The client will be installed as a systemd service (`tg-node`) and will immediately appear in the server list in the bot.

-----

### 🧰 Useful Commands

| Command (Systemd) | Command (Docker) | Description |
| :--- | :--- | :--- |
| `sudo systemctl status tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml ps` | Agent (Bot) Status |
| `sudo systemctl restart tg-bot` | `docker compose -f /opt/tg-bot/docker-compose.yml restart bot-root` | Restart Agent |
| `sudo journalctl -u tg-bot -f` | `docker compose -f /opt/tg-bot/docker-compose.yml logs -f bot-root` | Agent Logs |
| `sudo systemctl restart tg-node` | — | Restart Node (on client) |

*(Replace `bot-root` with `bot-secure` if you chose Docker Secure mode)*

-----

## ⚙️ Project Structure

```
/opt/tg-bot/          # Installation directory
├── bot.py            # Main entry point for the Agent
├── watchdog.py       # Alert system and process monitoring
├── deploy.sh         # Universal installer (Agent + Node)
├── requirements.txt  # Python dependencies
├── Dockerfile        # Docker image build instructions
├── docker-compose.yml # Container configuration
├── .env              # Configuration (Tokens, Mode)
│
├── node/             # [NEW] Client side
│   └── node.py       # Node (Client) script for remote servers
│
├── core/             # Bot Core
│   ├── server.py     # [NEW] Web server (aiohttp) for Agent API
│   ├── nodes_db.py   # [NEW] Node database (JSON)
│   ├── i18n.py       # Localization
│   └── ...           # config, auth, utils, messaging...
│
├── modules/          # Functional Modules
    ├── nodes.py      # [NEW] Node management
    ├── speedtest.py  # Speed test (iperf3)
    └── ...           # traffic, xray, sshlog, etc.
```

-----

## 🔒 Security

  * **Tokens:** Interaction between the Agent and Node is protected by unique tokens generated by the bot.
  * **Secure Mode:** In Secure mode, the bot runs as the unprivileged user `tgbot`.
  * **API Isolation:** The web server only accepts valid JSON requests with a correct token.
  * **Confidentiality:** The `.env` file is protected with `600` permissions and excluded from git.

<details>
<summary><h2>🧩 Adding Your Own Module</h2></summary>
Want to add your own command or feature to the bot?

1.  **Create a file:** In the `modules/` directory, create a new Python file (e.g., `my_module.py`).
2.  **Write the code:** Implement logic using `BUTTON_KEY`, `get_button()`, and `register_handlers(dp)`.
3.  **Add translations:** In `core/i18n.py`, add strings for your module.
4.  **Register the module:** In `bot.py`, import the module and add `register_module(my_module)`.
5.  **Restart the bot:** `sudo systemctl restart tg-bot`.

</details>

-----

## 👤 Author

**Version:** 1.11.0 (Build 42) <br>
**Author:** Jatix <br>
📜 **License:** GPL-3.0 license <br>
