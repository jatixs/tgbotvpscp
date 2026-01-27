# 📘 Project Architecture: VPS Manager Telegram Bot

## 🎯 System Overview

**VPS Manager Telegram Bot** is a professional infrastructure management system built on modern asynchronous architecture. The project implements an **Agent-Client** pattern, where the central bot manages a network of remote servers through a unified API.

### 🏗 Architectural Principles

1. **Modularity** — each function is isolated in a separate module
2. **Asynchronicity** — full asyncio support for high performance
3. **Security** — multi-level protection (WAF, Rate Limiting, encryption)
4. **Scalability** — support for unlimited number of remote nodes
5. **Fault Tolerance** — Watchdog system and automatic restart

---

## 📂 Project Structure

### 🔹 Root Level

```
/opt/tg-bot/
├── bot.py                    # Entry point, application initialization
├── watchdog.py              # Health monitoring, auto-restart
├── migrate.py               # Data migration system
├── manage.py                # CLI for bot management
├── .env                     # Configuration (secrets, tokens)
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Docker configuration
├── Dockerfile               # Container image
└── deploy.sh               # Automated installer
```

#### **bot.py** — Main Application File
**Purpose:** System entry point, orchestrator of all components

**Core Functions:**
- Initialize Aiogram Bot and Dispatcher
- Connect SQLite database (Tortoise ORM)
- Start web server (Aiohttp) on port 8080
- Register all modules and middleware
- Handle lifecycle events (startup/shutdown)
- Integrate with Sentry for error monitoring

**Technologies:** Aiogram 3.x, AsyncIO, Tortoise ORM

---

#### **watchdog.py** — Monitoring System
**Purpose:** Ensure continuous bot operation

**Core Functions:**
- Check bot process activity (health check)
- Automatic restart on failure
- Send status notifications (start/stop/crash)
- Log system events
- Monitor resource consumption

**Operating Modes:**
- Systemd service (classic installation)
- Docker container (containerization)

---

### 🔹 Directory `core/` — System Core

```
core/
├── config.py               # Central configuration
├── auth.py                 # Authorization system
├── server.py               # Web server and API
├── i18n.py                 # Internationalization
├── keyboards.py            # UI element generation
├── messaging.py            # Notification system
├── middlewares.py          # Anti-spam, filters
├── utils.py                # Helper utilities
├── nodes_db.py             # Node database (SQLite)
├── models.py               # ORM models (Tortoise)
├── shared_state.py         # Global state
├── static/                 # CSS, JS, images
│   ├── css/
│   │   ├── login.css
│   │   ├── main.css
│   │   └── style.css
│   └── js/
│       ├── common.js       # Common functions
│       ├── dashboard.js    # Dashboard logic
│       ├── login.js        # Authentication
│       ├── settings.js     # Settings
│       └── theme_init.js   # Theme styling
└── templates/              # HTML templates
    ├── dashboard.html
    ├── login.html
    ├── reset_password.html
    └── settings.html
```

---

#### **config.py** — Configuration Center
**Purpose:** Centralized settings management

**Loaded Parameters:**
- `TOKEN` — Telegram bot token
- `ADMIN_USER_ID` — Main administrator ID
- `WEB_SERVER_HOST/PORT` — Web server settings
- `DEPLOY_MODE` — Installation mode (root/secure)
- `DEFAULT_LANGUAGE` — Default language
- `ENABLE_WEB_UI` — Enable web interface
- Directory paths (logs, config, backups)

**Functions:**
- `load_encrypted_json()` — Read encrypted configs
- `save_encrypted_json()` — Save with Fernet encryption
- `save_system_config()` — Write system settings
- `save_keyboard_config()` — Keyboard configuration

---

#### **auth.py** — Authorization System
**Purpose:** Access control and user management

**Role Hierarchy:**
1. **Root/Owner** (ADMIN_USER_ID) — full access, including dangerous operations
2. **Admins** — node management, user management, link generation
3. **Users** — statistics viewing only

**Functions:**
- `is_root_admin()` — Check owner status
- `is_admin()` — Check administrative rights
- `check_user_access()` — Validate function access
- `load_users()` — Load user list
- `save_users()` — Save with encryption (Fernet)

**Storage:** `/opt/tg-bot/config/users.json` (encrypted)

---

#### **server.py** — Web Server and API
**Purpose:** REST API, Dashboard, SSE streams

**Main Endpoints:**

**Authentication:**
- `POST /api/login` — Web panel login
- `POST /api/logout` — Logout, delete session
- `POST /api/request_reset` — Request password reset
- `POST /api/reset_password` — Reset password by token

**Dashboard:**
- `GET /` — Main dashboard page
- `GET /api/dashboard_data` — Chart data
- `POST /api/reset_traffic` — Reset traffic counter

**Real-time Events (SSE):**
- `GET /api/events` — Server-Sent Events for notifications
- `GET /api/events/services` — SSE for service manager

**Nodes Management:**
- `GET /api/nodes` — List all nodes
- `POST /api/nodes/register` — Register new node
- `POST /api/nodes/:token/metrics` — Receive metrics from node
- `POST /api/nodes/:id/delete` — Delete node

**System:**
- `GET /api/logs/:type` — Get logs
- `POST /api/system_config` — Save configuration
- `POST /api/keyboard_config` — Keyboard settings
- `POST /api/alerts_config` — Alert configuration

**Security Features:**
- **WAF** — Web Application Firewall (SQL Injection, XSS, Path Traversal)
- **Rate Limiting** — 100 requests/minute per IP
- **Brute-force Protection** — Block after 5 failed attempts
- **CSRF Tokens** — Protection against request forgery
- **Session Management** — Secure server-side sessions
- **Audit Logging** — Detailed logging to `logs/audit/audit.log`

**Technologies:** Aiohttp, Argon2 (password hashing), Jinja2 (templates)

---

#### **i18n.py** — Internationalization System
**Purpose:** Multi-language interface support

**Supported Languages:**
- Russian (ru) — primary
- English (en) — full translation

**Translation Structure:**
```python
STRINGS = {
    "key_name": {
        "ru": "Russian text",
        "en": "English text"
    }
}
```

**Core Functions:**
- `get_text(key, lang)` — Get translation
- `get_user_lang(user_id)` — User language
- `set_user_lang(user_id, lang)` — Change language
- `I18nFilter` — Middleware for automatic translation

**Storage:** Language settings in `config/users.json`

---

#### **keyboards.py** — UI Generator
**Purpose:** Dynamic keyboard creation

**Keyboard Types:**
1. **Reply Keyboard** — Main menu
2. **Inline Keyboard** — Callback buttons in messages

**Functions:**
- `get_main_reply_keyboard(user_id)` — Main menu with permissions check
- `get_subcategory_keyboard(category, user_id)` — Category submenus
- `get_manage_users_keyboard()` — User management
- `get_keyboard_settings_inline()` — Keyboard settings

**Adaptivity:** Buttons automatically hide/show based on:
- User role (Root/Admin/User)
- Installation mode (DEPLOY_MODE: root/secure)
- Configuration in `config/keyboard_config.json`

---

#### **messaging.py** — Notification System
**Purpose:** Centralized message and alert sending

**Functions:**
- `send_alert()` — Send notification to all admins
  - Markdown support
  - Automatic translation to user language
  - Web notification integration
- `delete_previous_message()` — Delete old message
- `send_support_message()` — Support link

**Notification Types:**
- ⚠️ Resource threshold exceeded (CPU/RAM/Disk)
- 🔒 SSH logins to server
- 🛡️ IP ban via Fail2Ban
- 📡 Node downtime (node offline)
- 🚀 System events (bot start/restart)

**Mechanism:**
- Telegram API for bots
- Web panel receives via SSE (`/api/events`)
- Logging to `logs/bot/bot.log`

---

#### **middlewares.py** — Middleware Layer
**Purpose:** Request processing before handler invocation

**Implemented Middleware:**

**SpamThrottleMiddleware:**
- Flood protection (max 1 request per second per user)
- Store last request time
- Automatic reset when limit exceeded

**Application:** Registered globally for all updates

---

#### **utils.py** — Utilities and Helpers
**Purpose:** Common helper functions

**Main Categories:**

**Formatting:**
- `format_bytes(bytes)` — Convert bytes to KB/MB/GB
- `format_uptime(seconds)` — Convert seconds to readable format
- `get_country_flag(ip)` — Get country flag by IP

**Security:**
- `encrypt_for_web(data)` — XOR + Base64 encryption for web client
- `decrypt_for_web(data)` — Frontend decryption
- `log_audit_event()` — Audit logging (GDPR compliant)
- `mask_sensitive_data()` — Mask IPs, tokens, passwords

**System:**
- `get_host_path()` — Correct paths for Docker
- `get_app_version()` — Version from CHANGELOG
- `get_server_timezone_label()` — Server timezone
- `generate_favicons()` — Generate icons for PWA

**Service Configuration:**
- `load_services_config()` — Load `config/services.json` (Fernet)
- `save_services_config()` — Save managed services list

---

#### **nodes_db.py** — Node Database
**Purpose:** Remote server management

**ORM:** Tortoise ORM + SQLite (`config/nodes.db`)

**Core Functions:**
- `init_nodes_db()` — Initialize database
- `add_node()` — Register new node
- `get_node_by_token()` — Search by token
- `update_node_metrics()` — Update metrics
- `get_all_nodes()` — List all servers
- `delete_node()` — Delete node

**Node Model:**
```python
class Node:
    id: int
    token: str              # Unique authorization token
    name: str               # Human-readable name
    ip: str                 # Node IP address
    last_seen: datetime     # Last activity
    cpu_percent: float      # CPU load
    ram_percent: float      # RAM usage
    disk_percent: float     # Disk usage
    uptime: int             # Uptime (seconds)
```

---

#### **models.py** — ORM Models
**Purpose:** Data structure definition

**Models:**
- `User` — Bot users (Telegram ID, role, language)
- `Node` — Remote servers
- `Alert` — Notification history
- `TrafficLog` — Network traffic logs

**Migrations:** Managed via Aerich (`aerich.ini`)

---

#### **shared_state.py** — Global State
**Purpose:** In-memory storage for performance

**Variables:**
- `ALLOWED_USERS: dict` — User cache
- `AUTH_TOKENS: dict` — Node tokens
- `NODE_TRAFFIC_MONITORS: dict` — Active traffic monitors
- `ALERTS_CONFIG: dict` — Notification thresholds
- `AGENT_HISTORY: deque` — Agent metrics history (ring buffer)
- `WEB_NOTIFICATIONS: deque` — Web panel notifications
- `WEB_USER_LAST_READ: dict` — Last read notification

**Features:**
- Use of `deque` for memory limitation
- Periodic cleanup via `gc.collect()`

---

### 🔹 Directory `modules/` — Functional Modules

```
modules/
├── selftest.py             # Server summary (CPU/RAM/Disk/IP)
├── traffic.py              # Network traffic monitoring
├── uptime.py               # Uptime without reboot
├── top.py                  # Top-10 processes by CPU
├── speedtest.py            # Speed test (iperf3)
├── notifications.py        # Background checks and alerts
├── users.py                # User management
├── nodes.py                # Node management
├── services.py             # System services manager
├── vless.py                # VLESS link generation
├── xray.py                 # Xray Core update
├── sshlog.py               # SSH login logs
├── fail2ban.py             # Blocked IP logs
├── logs.py                 # System logs (journalctl)
├── update.py               # Bot and system update
├── reboot.py               # Server reboot
├── restart.py              # Bot restart
├── optimize.py             # System optimization
└── backups.py              # Configuration backups
```

#### Module Working Principle

Each module implements a unified interface:

```python
# Required functions:
def get_button() -> KeyboardButton:
    """Button for main menu"""
    
def register_handlers(dp: Dispatcher):
    """Register handlers"""

# Optional:
def has_subcategory() -> bool:
    """Has submenu"""
    
def get_subcategory() -> str:
    """Category name (monitoring/management/security/tools)"""
```

---

#### **notifications.py** — Alert System
**Purpose:** Background monitoring and notifications

**Monitored Metrics:**
- CPU > 80% (configurable threshold)
- RAM > 90%
- Disk > 85%
- Node downtime > 60 seconds

**Mechanism:**
- Async task `asyncio.create_task(check_alerts_loop())`
- Check interval: 30 seconds
- Debounce: repeat notification after 5 minutes

**Configuration:** Web panel Settings → Alerts Config

---

#### **services.py** — Service Manager
**Purpose:** Real-time systemd service management

**Capabilities:**
- View status of all services (ssh, docker, nginx, mysql, etc.)
- Start/Stop/Restart services
- Add/remove from monitoring list
- Real-time updates via SSE (`/api/events/services`)

**Security:**
- Data encryption: XOR + Base64 on backend
- Frontend decryption (JavaScript)
- Persistent configuration: `config/services.json` (Fernet)

**Architecture:**
```
Backend (server.py)
  ↓ SSE Stream (5 sec interval)
  ↓ encrypt_for_web(data)
Frontend (dashboard.js)
  ↓ EventSource API
  ↓ decrypt_for_web(data)
  ↓ Update UI
```

**Functions:**
- `get_all_services_status()` — All services status
- `perform_service_action(service, action)` — Execute command
- `add_managed_service()` — Add to monitoring
- `remove_managed_service()` — Remove from monitoring

---

#### **nodes.py** — Node Management
**Purpose:** Multi-server management

**Functions:**
- Add new node (generate token)
- List all connected nodes
- Switch context between servers
- Delete node
- View detailed information (CPU, RAM, uptime)

**Connection Process:**
1. Root admin: "Nodes" → "Add Node"
2. Enter name → Get token
3. On remote server: 
   ```bash
   curl -O deploy_en.sh && bash deploy_en.sh
   # Select "Install NODE (Client)"
   # Enter agent URL and token
   ```
4. Node appears in list

**Node Agent:** `node/node.py` — lightweight HTTP server sending metrics

---

### 🔹 Directory `node/` — Client for Remote Servers

```
node/
└── node.py                 # Agent for sending metrics
```

#### **node.py** — Node Agent
**Purpose:** Client for remote VPS

**Functions:**
- Collect system metrics (CPU, RAM, Disk, uptime)
- Send to main server (`POST /api/nodes/{token}/metrics`)
- Execute commands (on request from agent)
- SSH monitoring (optional)

**Requirements:**
- Python 3.10+
- Libraries: requests, psutil
- Open port on main server (8080)

**Deployment:**
```bash
cd /opt && git clone <repo> tg-node
cd tg-node/node
python3 node.py --agent-url http://MAIN_SERVER:8080 --token NODE_TOKEN
```

**Systemd Integration:**
```ini
[Unit]
Description=TG Node Agent
[Service]
ExecStart=/usr/bin/python3 /opt/tg-node/node/node.py ...
Restart=always
[Install]
WantedBy=multi-user.target
```

---

## 🔐 Security System

### Security Levels

#### 1️⃣ Telegram Bot Security
- **Whitelist** — Only authorized Telegram IDs
- **Role-based Access Control** — Root/Admin/User
- **Anti-spam middleware** — Throttling 1 req/sec per user

#### 2️⃣ Web Panel Security
- **Argon2** — Password hashing (OWASP recommended)
- **Server-side sessions** — Secure cookie with HTTPS
- **CSRF Protection** — Tokens for all POST requests
- **Brute-force Protection** — 5 attempts → 5 minute block
- **Rate Limiting** — 100 API requests/min per IP

#### 3️⃣ WAF (Web Application Firewall)
Attack Patterns:
- SQL Injection (`UNION SELECT`, `OR 1=1`)
- XSS (`<script>`, `javascript:`)
- Path Traversal (`../`, `%2e%2e`)
- Command Injection (`;`, `|`, `` ` ``)
- LDAP Injection (`()`, `|`)

#### 4️⃣ Data Encryption
- **Fernet** — Symmetric config encryption
  - `users.json`, `services.json`, `alerts_config.json`
- **XOR + Base64** — Lightweight web client encryption
  - Used for SSE events, services data

#### 5️⃣ Audit Logging
**Location:** `logs/audit/audit.log`

**Recorded Events:**
- Login attempts (success/fail)
- Password resets
- User additions/deletions
- Configuration changes
- Suspicious activity (WAF triggers)

**Format:**
```json
{
  "timestamp": "2026-01-27T12:00:00Z",
  "event_type": "LOGIN_SUCCESS",
  "ip": "203.0.113.X",
  "user": "admin",
  "details": {...}
}
```

**Privacy:**
- IP addresses masked (203.0.113.XXX)
- Tokens hidden (abc123...)
- GDPR compliant

---

## 🔄 Application Lifecycle

### Startup Sequence

```
1. Load .env configuration
2. Initialize logging system
3. Connect to SQLite database (Tortoise ORM)
4. Load encrypted configs (users, alerts, services)
5. Initialize Telegram Bot + Dispatcher
6. Register all modules & handlers
7. Start Aiohttp web server (port 8080)
8. Launch background tasks:
   - check_alerts_loop()
   - agent_metrics_collector()
   - SSE event broadcaster
9. Send startup notification to admin
```

### Shutdown Sequence

```
1. Signal received (SIGTERM/SIGINT)
2. Stop accepting new requests
3. Cancel background tasks
4. Save in-memory state to disk
5. Close database connections
6. Stop web server
7. Send shutdown notification
8. Exit gracefully (exit code 0)
```

### Watchdog Flow

```
while True:
    if bot_process_alive():
        send_heartbeat()
    else:
        log_crash_event()
        send_alert("Bot crashed, restarting...")
        restart_bot_process()
    sleep(30)
```

---

## 📊 Data Flows

### Metrics Collection Flow

```
Remote Node (node.py)
    ↓ (every 60 sec)
POST /api/nodes/{token}/metrics
    {
        "cpu": 45.2,
        "ram": 72.1,
        "disk": 38.5,
        "uptime": 864000
    }
    ↓
Agent Server (server.py)
    ↓
Update nodes_db (SQLite)
    ↓
Store in AGENT_HISTORY (deque)
    ↓
Check thresholds → Trigger alert if needed
    ↓
Broadcast via SSE → Web Dashboard updates
```

### User Interaction Flow

```
User (Telegram)
    ↓
Send command "/start"
    ↓
SpamThrottleMiddleware
    ↓
Auth check (is_admin/is_root)
    ↓
I18n translation
    ↓
Module handler (e.g., selftest.py)
    ↓
Execute system command (if root mode)
    ↓
Format response with markdown
    ↓
Send message + inline keyboard
    ↓
Store message_id for deletion
```

### SSE Event Flow

```
Backend Event (e.g., node metric update)
    ↓
Encrypt data (encrypt_for_web)
    ↓
Push to WEB_NOTIFICATIONS deque
    ↓
SSE endpoint /api/events checks queue
    ↓
Send as "data: {encrypted_json}\n\n"
    ↓
Frontend EventSource receives
    ↓
Decrypt (decrypt_for_web)
    ↓
Update DOM dynamically
```

---

## 🎨 Frontend Architecture

### Technologies
- **Tailwind CSS** — Utility-first CSS framework
- **Vanilla JavaScript** — No frameworks, pure ES6+
- **Server-Sent Events** — Real-time updates without WebSocket
- **Chart.js** — Resource consumption charts
- **PWA** — Progressive Web App with manifest

### Key Files

#### **dashboard.js**
**Purpose:** Main page logic

**Core Functions:**
- `initServicesSSE()` — Connect to SSE for services
- `loadServices()` — Load services list
- `updateDashboard()` — Update charts
- `openServiceInfoModal()` — Detailed service info
- `renderTrafficChart()` — Traffic chart
- `fetchNodesList()` — Node list

**EventSource Connections:**
- `/api/events` — General notifications
- `/api/events/services` — Real-time services

#### **theme_init.js**
**Purpose:** Theme management

**Functions:**
- Auto-detect system theme
- Switch light/dark mode
- Save to localStorage
- Sync between tabs

#### **common.js**
**Purpose:** Common utilities

**Functions:**
- `encrypt()/decrypt()` — XOR encryption
- `animateModalOpen()/Close()` — Modal animations
- `showNotification()` — Toast notifications
- `formatBytes()` — Size formatting

---

## 🗄️ Data Structures

### SQLite Database Schema

#### Table: `nodes`
```sql
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    ip TEXT,
    last_seen DATETIME,
    cpu_percent REAL DEFAULT 0.0,
    ram_percent REAL DEFAULT 0.0,
    disk_percent REAL DEFAULT 0.0,
    uptime INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Table: `users`
```sql
CREATE TABLE users (
    telegram_id BIGINT PRIMARY KEY,
    role TEXT DEFAULT 'users',
    language TEXT DEFAULT 'en',
    username TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME
);
```

### Encrypted JSON Configs

#### `config/users.json`
```json
{
    "12345678": {
        "role": "admins",
        "name": "John Doe",
        "lang": "en"
    }
}
```

#### `config/services.json`
```json
[
    "ssh",
    "docker",
    "nginx",
    "mysql",
    "postgresql"
]
```

#### `config/alerts_config.json`
```json
{
    "global_enabled": true,
    "thresholds": {
        "cpu": 80,
        "ram": 90,
        "disk": 85
    },
    "nodes": {
        "node_token_123": {
            "enabled": true,
            "custom_threshold": {...}
        }
    }
}
```

---

## 🚀 Installation Modes

### Root Mode
**Characteristics:**
- Full system access
- Host `/proc` mounting in Docker
- Dangerous operations available

**Capabilities:**
✅ Reboot physical server
✅ Read system logs (journalctl)
✅ Manage all services
✅ System update (apt upgrade)

**Installation:**
```bash
bash deploy.sh
# Select: 3) Docker - Root Mode
```

### Secure Mode
**Characteristics:**
- Limited privileges
- Container isolation
- User `tgbot` (UID 1000)

**Limitations:**
❌ Cannot reboot server
❌ No system log access
✅ Resource monitoring
✅ Bot management
✅ Web panel

**Installation:**
```bash
bash deploy.sh
# Select: 1) Docker - Secure Mode (Recommended)
```

---

## 🧪 Testing and Debugging

### Logging

**Levels:**
- `DEBUG` — Detailed information
- `INFO` — Normal events
- `WARNING` — Warnings
- `ERROR` — Errors
- `CRITICAL` — Critical failures

**Log Files:**
- `logs/bot/bot.log` — Main bot log
- `logs/watchdog/watchdog.log` — Watchdog events
- `logs/node/node_{name}.log` — Logs for each node
- `logs/audit/audit.log` — Security audit

**Real-time Viewing:**
```bash
# Systemd
journalctl -u tg-bot -f

# Docker
docker compose -f /opt/tg-bot/docker-compose.yml logs -f bot-secure
```

### Debug Endpoints

**GET /api/health**
```json
{
    "status": "healthy",
    "version": "1.18.0",
    "uptime": 86400,
    "nodes_count": 5
}
```

**GET /api/debug/state** (Root only)
```json
{
    "allowed_users": [...],
    "active_traffic_monitors": 3,
    "notifications_queue": 12,
    "memory_usage_mb": 145.2
}
```

---

## 📝 Adding a New Module

### Module Template

```python
# modules/my_feature.py

from aiogram import Dispatcher, types
from aiogram.types import KeyboardButton
from core.i18n import get_text as _
from core import config

BUTTON_KEY = "button_my_feature"
CATEGORY = "tools"  # monitoring/management/security/tools

def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def get_subcategory() -> str:
    return CATEGORY

def has_subcategory() -> bool:
    return True

def register_handlers(dp: Dispatcher):
    dp.message.register(
        my_feature_handler,
        lambda msg: msg.text == _(BUTTON_KEY, config.DEFAULT_LANGUAGE)
    )

async def my_feature_handler(message: types.Message):
    user_id = message.from_user.id
    # Your logic here
    await message.answer("Feature response")
```

### Integration

1. **Add strings to `core/i18n.py`:**
```python
STRINGS = {
    "button_my_feature": {
        "ru": "🎯 My Feature",
        "en": "🎯 My Feature"
    }
}
```

2. **Import in `bot.py`:**
```python
from modules import my_feature

# In main():
my_feature.register_handlers(dp)
```

3. **Add to keyboard config:**
```python
# core/config.py
KEYBOARD_CONFIG = {
    "my_feature": {"visible": True, "category": "tools"}
}
```

---

## 📚 Dependencies

### Python Packages

**Core:**
- `aiogram==3.4.1` — Telegram Bot API
- `aiohttp==3.9.1` — Async HTTP server
- `tortoise-orm==0.20.0` — SQLite ORM
- `cryptography==41.0.7` — Fernet encryption
- `argon2-cffi==23.1.0` — Password hashing

**Utilities:**
- `psutil==5.9.6` — System metrics
- `aiosqlite==0.19.0` — Async SQLite
- `python-dotenv==1.0.0` — Load .env
- `jinja2==3.1.2` — HTML templates

**Optional:**
- `sentry-sdk==1.39.1` — Error monitoring
- `aerich==0.7.2` — DB migrations

**Dev:**
- `pytest==7.4.3`
- `black==23.12.1`
- `flake8==6.1.0`

### System Requirements

**Minimum:**
- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- 1 GB RAM
- 10 GB Disk
- Docker 20.10+ (for containers)

**Recommended:**
- 2 GB RAM
- 20 GB SSD
- 2 CPU cores

---

## 🔗 Useful Links

- [Aiogram Documentation](https://docs.aiogram.dev/)
- [Aiohttp Documentation](https://docs.aiohttp.org/)
- [Tortoise ORM](https://tortoise.github.io/)
- [Tailwind CSS](https://tailwindcss.com/)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---

**Author:** Jatix  
**Version:** 1.18.0 (Build 66)  
**License:** GPL-3.0  
**Last Updated:** January 27, 2026


2. **Secure (Safe):** The bot runs as a restricted user.
* *Restrictions:* Cannot reboot the physical server, no access to system SSH and Fail2Ban logs. Only monitoring and bot management are available.



### 👤 User Roles

An access hierarchy is implemented within the bot:

1. **Root (Super-Admin):**
* Has access to all functions, including dangerous ones (reboot, logs).
* Defined by the `ADMIN_ID` variable in `.env`.


2. **Admin:**
* Can manage users, generate VLESS links, run Speedtest.
* Assigned via the "Users" menu.


3. **User:**
* Only statistics viewing (Traffic, Uptime, Status).
* Cannot change settings or manage the server.



---

## 3. Detailed Function Description (Modules)

### 📊 "Monitoring" Category

* **🛠 Server Info (`selftest.py`):** Shows a summary: CPU, RAM, Disk, IP, Ping, OS Version.
* **📡 Network Traffic (`traffic.py`):** Starts live monitoring. The message updates every X seconds, showing current speed (Mbit/s) and total volume.
* **⏱ Uptime (`uptime.py`):** Shows how long the server has been running without a reboot.
* **🔥 Top Processes (`top.py`):** Lists the 10 processes most demanding on the CPU.

### ⚙️ "Management" Category

* **👤 Users (`users.py`):** Panel for adding new people to the bot by Telegram ID, changing their roles, or removing them.
* **🖥 Nodes (`nodes.py`):** Management of remote servers (agents). Allows switching between servers and executing commands on them.
* **⚙️ Service Manager (`services.py`):** Management of system services (ssh, docker, nginx, mysql, etc.). Data is transmitted in real-time via Server-Sent Events (SSE) with automatic updates every 5 seconds. Data is encrypted on the backend (XOR + Base64) and decrypted on the frontend. Configuration is saved to encrypted file `/opt/tg-bot/config/services.json`.
* **🔗 VLESS Link (`vless.py`):** Access key generator. You send the bot an Xray JSON config, and it generates a ready-to-use `vless://` link and QR code.
* **🩻 Update X-ray (`xray.py`):** Automatically detects the installed panel (Amnezia, Marzban) and updates the Xray Core binary in the container.

### 🛡️ "Security" Category (Root Only)

* **📜 SSH Log (`sshlog.py`):** Shows recent login attempts to the server (successful and failed) with country flags.
* **🔒 Fail2Ban Log (`fail2ban.py`):** Shows the latest IP addresses banned by the protection system.
* **📜 Recent Events (`logs.py`):** Output of the last lines from the system journal `journalctl` (errors, warnings).

### 🛠 "Tools" Category

* **🚀 Network Speed (`speedtest.py`):** Runs a speed test via `iperf3`. Automatically searches for the nearest server, or a server in RU/Europe depending on geolocation.
* **⚡️ Optimization (`optimize.py`):** Runs a script to clear cache, remove old kernels, and optimize the TCP stack (sysctl).

### 🔌 Power Management

* **♻️ Restart Bot (`restart.py`):** Restarts the bot process (via Systemd or Docker).
* **🔄 Reboot Server (`reboot.py`):** Sends the `reboot` command to the host system. Requires confirmation.
* **🔄 Update VPS (`update.py`):** Offers a choice: update bot code (git pull) or system packages (`apt upgrade`).

---

## 4. Web Interface (WebUI)

The bot hosts a local website (default port 8080), which serves as a graphical control panel.

**WebUI Features:**

1. **Dashboard:** Beautiful real-time resource consumption charts.
2. **Settings:**
* Change notification thresholds (e.g., send alert if CPU > 80%).
* Configure traffic update frequency.
* Manage button visibility in the Telegram menu.


3. **Logs:** View bot logs directly in the browser.
4. **Sessions:** View and forcibly terminate active user sessions.

---

## 5. Node System (Multi-Server)

The bot can manage not only the server where it is installed but also other VPS.

1. **Server (Main Bot):** The main bot where you click buttons. Stores the database of all nodes.
2. **Agent (`node/node.py`):** A lightweight script installed on subordinate servers.
* Runs as a web service.
* Receives commands from the Main Bot (e.g., "give CPU stats").
* Sends results back.
* Requires only Python and an open port.



**Process:** In the "🖥 Nodes" menu, you create a node -> The bot gives a token -> You run the agent installation script on the second server with this token.

---

## 6. Notification System

The `modules/notifications.py` file runs in the background and checks:

1. **Resources:** If CPU/RAM/Disk exceed the threshold (configured in WebUI), the admin receives a notification.
2. **Node Downtime:** If a remote agent stops responding, the bot sends a "Node Unavailable" alert.
3. **SSH/Fail2Ban:** (If enabled) Notifies about every login to the system or IP ban.
