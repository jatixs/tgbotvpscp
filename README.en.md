<p align="center">
  <a href="README.md">Русская Версия</a> | English Version
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b>v1.23.3</b> — professional ecosystem for server infrastructure management & monitoring<br>
  (Systemd / Docker / API / WebUI / PWA / Multi-Node / Remote SSH / Backup Manager)<br><br>

  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.23.3-blue?style=flat-square" alt="Version 1.23.3"/></a>
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/build-80-purple?style=flat-square" alt="Build 80"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+"/></a>
  <a href="https://choosealicense.com/licenses/gpl-3.0/"><img src="https://img.shields.io/badge/license-GPL--3.0-lightgrey?style=flat-square" alt="License GPL-3.0"/></a>
  <a href="https://github.com/aiogram/aiogram"><img src="https://img.shields.io/badge/aiogram-3.x-orange?style=flat-square" alt="Aiogram 3.x"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-ready-blueviolet?style=flat-square" alt="Docker"/></a>
  <a href="https://releases.ubuntu.com/focal/"><img src="https://img.shields.io/badge/platform-Ubuntu%2020.04%2B-important?style=flat-square" alt="Platform Ubuntu 20.04+"/></a>
</p>

---

## 📘 Table of Contents

1. [About](#-about-the-project)
2. [Key Features](#-key-features)
3. [Architecture](#-architecture)
4. [Quick Start](#-quick-start)
5. [Web Interface](#-web-interface)
6. [Security](#-security)
7. [Project Structure](#️-project-structure)
8. [Documentation](#-documentation)
9. [License](#-license)

---

## 🧩 About the Project

**VPS Manager Telegram Bot** is a comprehensive enterprise-class solution for managing server infrastructure via Telegram and web interface.

### 🎯 Who is this for?

- **System Administrators** — automate routine tasks
- **DevOps Engineers** — monitor multiple servers from one place
- **VPN Providers** — manage X-ray/VLESS panels
- **Hosting Providers** — client monitoring

### 💡 Problems this project solves

✅ **Centralized Management** — one interface for all servers  
✅ **Real-time Monitoring** — instant updates without reloading  
✅ **Security** — enterprise-grade protection with WAF and audit logging  
✅ **Scalability** — from 1 to 1000+ servers  
✅ **Mobility** — manage from your phone via Telegram  

---

## ⚡ Key Features

### 🚀 Performance

- ✅ **Fully Asynchronous** — AsyncIO, aiohttp, aiosqlite
- ✅ **Low Footprint** — ~100MB RAM per agent
- ✅ **Ring Buffers** — memory optimization via deque
- ✅ **Memory Orchestrator** <sup>NEW</sup> — dynamic unloading of unused modules

### 🖥 Multi-Server Management

- ✅ **Unlimited Nodes** — scalable architecture
- ✅ **Real-time Metrics** — CPU, RAM, Disk, Network
- ✅ **Remote Execution** — commands on any server
- ✅ **System Optimization** <sup>NEW</sup> — interactive VPS tuning module (BBR, Swap, cache cleanup)
- ✅ **Centralized Dashboard** — unified control panel

### 🤖 Smart Telegram UX

- ✅ **Smart Cleanup** <sup>NEW</sup> — auto-deletes user commands and stale bot menus to keep the chat clean
- ✅ **Anti-Spam Protection** <sup>NEW</sup> — built-in SpamThrottle to protect Telegram API limits
- ✅ **Interactive Widgets** — inline menus with state-preserving checkboxes and live timers

### 🛡️ Enterprise-Grade Security

- ✅ **WAF** — protection against SQL Injection, XSS, Path Traversal
- ✅ **Rate Limiting** — DDoS protection (100 req/min)
- ✅ **Brute-force Protection** — auto-block after 5 attempts
- ✅ **Audit Logging** — detailed logs of all events
- ✅ **E2E Encryption** — Fernet + XOR encryption
- ✅ **RBAC** — Root/Admin/User roles

### 🎨 Modern Web Interface

- ✅ **PWA** — works like a native app
- ✅ **SSE (Server-Sent Events)** — updates without reloading
- ✅ **Dark Theme** — automatic switching
- ✅ **Responsive Design** — mobile-first approach
- ✅ **Real-time Charts** — Chart.js visualization
- ✅ **Drag & Drop** <sup>NEW</sup> — manual and automatic server sorting
- ✅ **Smart Indicators** <sup>NEW</sup> — visual alerts during peak resource loads

### ⚙️ Service Manager

- ✅ **Real-time Status** — all systemd services
- ✅ **SSE Streaming** — updates every 5 seconds
- ✅ **Start/Stop/Restart** — one-button control
- ✅ **Encrypted Storage** — persistent configuration
- ✅ **Detailed Info** — logs, uptime, PID

### 🔔 Smart Notifications

- ✅ **Customizable Thresholds** — CPU/RAM/Disk by choice
- ✅ **Global and Individual** — for agent and each node
- ✅ **Downtime Alerts** — node unavailable > 60 sec
- ✅ **SSH Monitoring** — login notifications
- ✅ **Fail2Ban Integration** — IP blocking

### 🌐 Internationalization

- ✅ **Russian** — full localization
- ✅ **English** — complete translation
- ✅ **Switch On-the-fly** — no restart needed

### 🐳 Docker & DevOps

- ✅ **Docker Compose** — easy deployment
- ✅ **Two Modes** — Root (full access) / Secure (isolation)
- ✅ **Auto-updates** — git pull + restart
- ✅ **Watchdog** — auto-restart on crash
- ✅ **Health Checks** — state monitoring

---

## 🏗 Architecture

**Agent-Client Pattern** with centralized management:

```
┌──────────────────────────────────────────────────┐
│                 🤖 Telegram Bot                  │
│                  (Main Agent)                    │
│                                                  │
│  ├─ 📊 SQLite DB        (nodes, users, metrics) │
│  ├─ 🌐 Web Dashboard    (aiohttp + SSE)         │
│  ├─ 🔌 Bot Core         (aiogram handlers)      │
│  └─ ⏰ Background Tasks  (monitoring, alerts)    │
└──────────────────────────────────────────────────┘
                     ↓     ↓     ↓
        ┌────────────┴─────┴─────┴────────────┐
        │                                      │
┌───────▼──────┐  ┌───────▼──────┐  ┌────────▼──────┐  ┌────────▼──────┐
│    Node 1    │  │    Node 2    │  │    Node 3     │  │     Node N     │
│    (VPS)     │  │    (VPS)     │  │    (VPS)      │  │     (VPS)      │
└──────────────┘  └──────────────┘  └───────────────┘  └───────────────┘

```

**Technology Stack:**
- **Backend:** Python 3.10+, Aiogram 3.x, Aiohttp, Tortoise ORM
- **Database:** SQLite (aiosqlite)
- **Frontend:** Tailwind CSS, Vanilla JavaScript, Chart.js
- **Real-time:** Server-Sent Events (SSE)
- **Security:** Argon2, Fernet, XOR encryption
- **Infrastructure:** Docker, Docker Compose, Systemd

📖 Learn more: [ARCHITECTURE.en.md](ARCHITECTURE.en.md)

---

## 🚀 Quick Start

### System Requirements

**Minimum:**
- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- 1 GB RAM
- 10 GB Disk

**Recommended:**
- 2 GB RAM
- 20 GB SSD
- 2 CPU cores

### 1️⃣ Preparation

1. Get a bot token from [@BotFather](https://t.me/BotFather)
2. Find your Telegram ID via [@userinfobot](https://t.me/userinfobot)
3. Ensure `curl` and `git` are installed:
   ```bash
   sudo apt update && sudo apt install -y curl git
   ```

### 2️⃣ Install Main Bot

```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy_en.sh)
```

**Choose installation mode:**
- `1) Docker - Secure Mode` — **Recommended** (isolation, security)
- `3) Docker - Root Mode` — Full access (for server reboot)

**Enter credentials:**
- Bot Token (from BotFather)
- Admin User ID (your Telegram ID)

🎉 Bot started! API available at `http://YOUR_IP:8080`

### 3️⃣ Connect Remote Servers (Nodes)

#### On main bot:
1. Open Telegram → **🖥 Nodes**
2. Click **➕ Add Node**
3. Enter name → Copy **token**

#### On remote server:
```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy_en.sh)
```

Choose **8) Install NODE (Client)**

Enter:
- **Agent URL:** `http://MAIN_SERVER_IP:8080`
- **Token:** received from bot

✅ Node will appear in the list within seconds!

---

## 💻 Web Interface

### Access Dashboard

```
http://YOUR_SERVER_IP:8080
```

**First login:**
- Username: `admin`
- Password: `admin` (change after login!)

### Main Features

#### 📊 Dashboard
- Real-time CPU/RAM/Disk charts
- List of all nodes with statuses
- Network traffic (current and historical)
- Quick actions (reboot, update)
- Drag & Drop node sorting <sup>NEW</sup>
- Visual alerts (⚠️) during peak loads <sup>NEW</sup>

#### ⚙️ Settings
- **Alerts Config** — notification thresholds (CPU 80%, RAM 90%, Disk 85%)
- **Keyboard Config** — button visibility in Telegram
- **User Management** — add/remove users
- **Language** — change interface language

#### ⚙️ Service Manager <sup>NEW</sup>
- Status of all systemd services
- Control (Start/Stop/Restart)
- Add to monitoring
- Detailed info (PID, uptime, logs)

#### 📜 Logs
- Bot logs (real-time)
- Watchdog logs
- Node logs (separate for each node)
- Audit logs (security events)

### API Endpoints

**Important:**
- `GET /api` and `GET /api/` return a JSON index with route groups and do not expose metrics.
- `GET /api/events`, `GET /api/events/logs`, `GET /api/events/node`, and `GET /api/events/services` are internal SSE streams and are not meant to be opened directly in a browser.
- SSE endpoints require a client that sends `Accept: text/event-stream` (`EventSource` in WebUI).
- `GET /api/terminal/ws` is an internal WebSocket endpoint and returns `426 Upgrade Required` for a regular HTTP request.

**Auth API:**
- `POST /api/login/request` — request a magic link via Telegram
- `POST /api/login/password` — login with username and password
- `GET /api/login/magic` — login via magic link
- `POST /api/auth/telegram` — login via Telegram widget
- `POST /api/login/reset` — request password reset
- `POST /api/reset/confirm` — confirm password reset
- `GET /api/security/telegram_only_mode` — get Telegram-only mode state
- `POST /api/security/telegram_only_mode` — toggle Telegram-only mode
- `GET /api/sessions/list` — list active web sessions
- `POST /api/sessions/revoke` — revoke one session
- `POST /api/sessions/revoke_all` — revoke all other sessions
- `POST /api/settings/password` — change web panel password

**Node API:**
- `GET /api/heartbeat` — health probe for agent/node
- `POST /api/heartbeat` — node heartbeat with HMAC signature
- `GET /api/nodes/list` — list nodes
- `POST /api/nodes/add` — add node
- `POST /api/nodes/delete` — delete node
- `POST /api/nodes/rename` — rename node
- `GET /api/nodes/monitor/list` — monitoring page data
- `GET /api/nodes/monitor/detail?token=...` — specific node details
- `GET /api/nodes/monitor/services?token=...` — specific node services
- `POST /api/nodes/monitor/command` — send command to node
- `POST /api/nodes/monitor/service_action` — perform node service action

**System API:**
- `GET /api/logs` — bot log tail
- `GET /api/logs/system` — system logs
- `POST /api/logs/clear` — clear logs
- `POST /api/settings/save` — save alert settings
- `POST /api/settings/system` — save system thresholds
- `POST /api/settings/keyboard` — save keyboard configuration
- `POST /api/settings/metadata` — save web metadata
- `POST /api/settings/language` — switch WebUI language
- `POST /api/users/action` — manage users
- `GET /api/update/check` — check updates
- `POST /api/update/run` — run update
- `GET /api/notifications/list` — list notifications
- `POST /api/notifications/read` — mark notifications as read
- `POST /api/notifications/clear` — clear notifications
- `POST /api/traffic/reset` — reset traffic statistics
- `GET /api/services` — managed services list
- `GET /api/services/available` — available services list
- `GET /api/services/info/{name}` — service info
- `POST /api/services/{action}` — service action (`start|stop|restart`)
- `POST /api/services/manage` — add or remove service from monitoring

**Streaming / Internal API:**
- `GET /api/events` — main dashboard SSE stream
- `GET /api/events/logs` — logs SSE stream
- `GET /api/events/node` — node details SSE stream
- `GET /api/events/services` — service manager SSE stream
- `GET /api/agent/ipv4` — agent IPv4 list
- `GET /api/terminal/creds` — load saved SSH credentials
- `POST /api/terminal/creds` — save SSH credentials
- `GET /api/terminal/stats` — server stats for web terminal
- `GET /api/terminal/ws` — terminal WebSocket endpoint

### PWA Features

**Install as app:**
1. Open Dashboard in browser
2. Click "Install" (Chrome) or "Add to Home Screen" (Mobile)
3. Use as native app

**PWA Benefits:**
- Works offline (caching)
- Icon on desktop
- Fullscreen mode
- Push notifications (in development)

---

## 🔒 Security

### Security Levels

#### 🔹 Level 1: Telegram Bot
- Whitelist — only authorized Telegram IDs
- Role-Based Access Control (RBAC)
- Anti-spam middleware (1 request/sec per user)

#### 🔹 Level 2: Web Panel
- **Argon2** — OWASP recommended password hashing
- **Server-side sessions** — secure cookies
- **CSRF Protection** — tokens for all POST requests
- **Brute-force Protection** — block after 5 attempts for 5 minutes
- **Rate Limiting** — 100 API requests/min per IP

#### 🔹 Level 3: WAF (Web Application Firewall)

Automatic detection:
- ❌ SQL Injection (`UNION SELECT`, `OR 1=1`)
- ❌ XSS (`<script>`, `javascript:`)
- ❌ Path Traversal (`../`, `%2e%2e`)
- ❌ Command Injection (`;`, `|`, `` ` ``)
- ❌ LDAP Injection

#### 🔹 Level 4: Data Encryption
- **Fernet** — symmetric encryption for configs (`users.json`, `services.json`)
- **XOR + Base64** — lightweight encryption for web client (SSE events)

#### 🔹 Level 5: Audit Logging

**Recorded:**
- Login attempts (success/fail)
- Password resets
- User additions/deletions
- Configuration changes
- WAF triggers

**Privacy:**
- IPs masked (203.0.113.XXX)
- Tokens hidden (abc123...)
- GDPR compliant

**File:** `logs/audit/audit.log`

---

## 🗂️ Project Structure

```
/opt/tg-bot/
├── bot.py                    # Entry point
├── watchdog.py              # Auto-restart
├── migrate.py               # Data migration
├── manage.py                # CLI management
├── .env                     # Configuration
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Docker configuration
├── Dockerfile               # Container image
├── deploy_en.sh             # Installer
├── core/                    # System core
│   ├── config.py            # Configuration loader
│   ├── auth.py              # Authorization
│   ├── i18n.py              # Multilingual
│   ├── keyboards.py         # UI generator
│   ├── messaging.py         # Notifications
│   ├── middlewares.py       # Bot middlewares
│   ├── models.py            # ORM models (Tortoise)
│   ├── nodes_db.py          # Node database
│   ├── shared_state.py      # Bot ↔ Web state bridge
│   ├── tasks.py             # Background tasks
│   ├── utils.py             # Utilities
│   ├── web/                 # Web layer (aiohttp)
│   │   ├── app.py           # Routes & init
│   │   ├── auth.py          # Web auth (password/magic link/Telegram)
│   │   ├── middlewares.py   # WAF, CSRF, Rate Limiting
│   │   ├── api_nodes.py     # aiohttp-based node API
│   │   ├── api_system.py    # aiohttp-based system API
│   │   ├── streaming.py     # SSE streams
│   │   └── views.py         # Jinja2 HTML pages
│   ├── static/              # CSS, JS
│   └── templates/           # HTML templates
├── modules/                 # Functional modules (18 modules)
│   ├── selftest.py          # Server summary
│   ├── traffic.py           # Traffic monitoring
│   ├── services.py          # Service manager
│   ├── nodes.py             # Node management
│   ├── users.py             # User management
│   ├── backups.py           # Backup manager
│   ├── notifications.py     # Background alerts
│   └── ...                  # +11 modules
└── node/                    # Client for remote servers
    └── node.py              # Node agent
```

📖 Detailed documentation: [ARCHITECTURE.en.md](ARCHITECTURE.en.md)

---

## 📚 Documentation

### Guides

- 📘 [**ARCHITECTURE.en.md**](ARCHITECTURE.en.md) — Complete project architecture
- 🧩 [**custom_module_en.md**](custom_module_en.md) — Creating your own module
- 🌐 [**web_module_en.md**](web_module_en.md) — Creating a web module (WebUI + Bot)
- 📝 [**CHANGELOG.en.md**](CHANGELOG.en.md) — Change history

### Useful Commands

#### Bot Management (Docker)

```bash
# Status
docker compose -f /opt/tg-bot/docker-compose.yml ps

# Restart
docker compose -f /opt/tg-bot/docker-compose.yml restart bot-secure

# Logs (real-time)
docker compose -f /opt/tg-bot/docker-compose.yml logs -f bot-secure

# Stop
docker compose -f /opt/tg-bot/docker-compose.yml stop

# Start
docker compose -f /opt/tg-bot/docker-compose.yml up -d
```

#### Bot Management (Systemd)

```bash
# Status
sudo systemctl status tg-bot

# Restart
sudo systemctl restart tg-bot

# Logs
sudo journalctl -u tg-bot -f

# Stop
sudo systemctl stop tg-bot
```

#### Backup

```bash
# Database
cp /opt/tg-bot/config/nodes.db /backup/nodes.db.$(date +%F)

# Configurations
tar -czf /backup/tg-bot-config-$(date +%F).tar.gz /opt/tg-bot/config/

# Logs
tar -czf /backup/tg-bot-logs-$(date +%F).tar.gz /opt/tg-bot/logs/
```

#### Update

```bash
# Automatic (via bot)
# Telegram → 🔧 Utilities → 🔄 Update VPS → Update Bot

# Manual
cd /opt/tg-bot
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart tg-bot
```

---

## 📊 API Endpoints

### Public Endpoints

- `GET /` — Dashboard (authentication required)
- `POST /api/login` — Login
- `POST /api/logout` — Logout

### Monitoring

- `GET /api/dashboard_data` — Dashboard data
- `GET /api/events` — SSE stream (notifications)
- `GET /api/events/services` — SSE stream (services)

### Node Management

- `GET /api/nodes` — List all nodes
- `POST /api/nodes/register` — Register node
- `POST /api/nodes/{token}/metrics` — Submit metrics
- `POST /api/nodes/{id}/delete` — Delete node

### System

- `GET /api/health` — Health check
- `GET /api/logs/{type}` — Get logs
- `POST /api/system_config` — Save configuration
- `POST /api/alerts_config` — Alert settings

📖 Full API documentation: [ARCHITECTURE.en.md#api](ARCHITECTURE.en.md)

---

## 🤝 Contributing

We welcome contributions to the project!

### How to help:

1. 🐛 **Report a bug** — [Issues](https://github.com/jatixs/tgbotvpscp/issues)
2. 💡 **Suggest a feature** — [Discussions](https://github.com/jatixs/tgbotvpscp/discussions)
3. 🔧 **Submit a Pull Request**
4. 📖 **Improve documentation**
5. ⭐ **Star the project** — it motivates!

### Development

```bash
# Clone
git clone https://github.com/jatixs/tgbotvpscp.git
cd tgbotvpscp

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure .env
cp .env.example .env
nano .env

# Run
python bot.py
```

---

## 📄 License

This project is licensed under **GPL-3.0**. See [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Jatix**

- 📧 Email: [jatix.com@mail.ru](jatix.com@mail.ru)
- 💬 Telegram: [@jatix](https://t.me/faridshykhaliev)
- 🌐 GitHub: [@jatixs](https://github.com/jatixs)

---

## 🌟 Support the Project

If you find this project useful, support it:

- ⭐ **Star** on GitHub
- 🔄 **Share** with friends
- 💰 **[Donate](https://yoomoney.ru/to/410011639584793)**

---

<p align="center">
  <b>Version:</b> 1.23.3 (Build 80)<br>
  <b>License:</b>GPL-3.0 license<br>
  <b>Status:</b> Stable<br>
  <br>
  Made with ❤️ for the DevOps community
</p>
