# 📘 Project Architecture: VPS Manager Telegram Bot

## 🎯 System Overview

**VPS Manager Telegram Bot** is a professional infrastructure management system built on modern asynchronous architecture. The project implements an **Agent-Client** pattern, where the central bot manages a network of remote servers through a unified API.

### 🏗 Architectural Principles

1. **Modularity** — each function is isolated in a separate module
2. **Asynchronicity** — full asyncio support for high performance
3. **Security** — multi-level protection (WAF, Rate Limiting, encryption)
4. **Scalability** — support for unlimited number of remote nodes
5. **Fault Tolerance** — Watchdog system and automatic restart
6. **Separation of Concerns** — web layer in `core/web/`, bot logic in `modules/`

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
- Initialize Aiogram Bot and Dispatcher with MemoryStorage
- Connect SQLite database (Tortoise ORM)
- Start web server via `core/web/app.py` on port 8080
- Register **18 functional modules** and middleware
- Handle lifecycle events (startup/shutdown)
- Integrate with Sentry for error monitoring
- Categorized menu: Monitoring, Management, Security, Tools, Settings
- Fallback handler for unrecognized commands (returns random interesting facts from uselessfacts API, seamlessly translated via Google Translate)

**Module Registration:**
```python
register_module(selftest)          # Available to all
register_module(users, admin_only=True)  # Admins only
register_module(reboot, root_only=True)  # Root only
```

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
├── auth.py                 # Authorization system (Telegram)
├── i18n.py                 # Internationalization
├── keyboards.py            # UI element generation
├── messaging.py            # Notification system
├── middlewares.py          # Anti-spam, filters (Telegram)
├── utils.py                # Helper utilities
├── nodes_db.py             # Node database (Tortoise ORM)
├── models.py               # ORM models
├── orchestrator.py         # Memory Orchestrator (Lazy Loading / GC)
├── shared_state.py         # Global state (in-memory)
├── tasks.py                # Background tasks (monitoring, cleanup)
├── web/                    # 🌐 Web server (details below)
│   ├── app.py              # Aiohttp initialization, routing
│   ├── auth.py             # Authentication (Web)
│   ├── middlewares.py      # WAF, Rate Limiting, CSRF
│   ├── api_nodes.py        # Node management API
│   ├── api_system.py       # System settings API
│   ├── streaming.py        # Server-Sent Events (SSE)
│   └── views.py            # HTML views (Jinja2)
├── static/                 # CSS, JS, images
│   ├── css/
│   │   ├── login.css       # Auth styles
│   │   ├── main.css        # Tailwind base styles
│   │   └── style.css       # Components and animations
│   └── js/
│       ├── common.js       # Encryption, modals, toast
│       ├── dashboard.js    # Dashboard logic and SSE
│       ├── login.js        # Authentication
│       ├── nodes_monitor.js # Node monitoring
│       ├── settings.js     # Settings and notifications
│       ├── reset_password.js # Password reset
│       └── theme_init.js   # Theme management
└── templates/              # HTML templates (Jinja2)
    ├── dashboard.html      # Main dashboard
    ├── login.html          # Login page
    ├── nodes_monitor.html  # Node monitoring
    ├── reset_password.html # Password reset
    ├── settings.html       # Settings
    └── terminal.html       # Web terminal (VNC)
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
- `setup_logging()` — Logging setup (Debug/Release)

---

#### **auth.py** — Authorization System (Telegram)
**Purpose:** Bot user access control

**Role Hierarchy:**
1. **Root/Owner** (ADMIN_USER_ID) — full access, including dangerous operations
2. **Admins** — node management, user management, link generation
3. **Users** — statistics viewing only

**Functions:**
- `is_root_admin()` — Check owner status
- `is_admin()` — Check administrative rights
- `is_allowed()` — Validate command access
- `load_users()` / `save_users()` — Encrypted user list management
- `refresh_user_names()` — Update names via Telegram API

**Storage:** `/opt/tg-bot/config/users.json` (Fernet encryption)

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
- `get_text(key, lang)` — Get translation (alias `_()`)
- `get_user_lang(user_id)` — User language from cache
- `set_user_lang(user_id, lang)` — Set language
- `I18nFilter` — Aiogram filter for intercepting buttons in any language

**Storage:** Language settings in `shared_state.USER_SETTINGS`

---

#### **keyboards.py** — UI Generator
**Purpose:** Dynamic Telegram keyboard creation

**Keyboard Types:**
1. **Reply Keyboard** — Main categorized menu
2. **Inline Keyboard** — Callback buttons in messages

**Functions:**
- `get_main_reply_keyboard(user_id)` — Main menu (5 categories)
- `get_subcategory_keyboard(category, user_id)` — Category submenu
- `get_manage_users_keyboard()` — User management
- `get_keyboard_settings_inline()` — Button visibility settings

**Adaptivity:** Buttons automatically hide/show based on:
- User role (Root/Admin/User)
- Installation mode (`DEPLOY_MODE`: root/secure)
- Visibility configuration (`KEYBOARD_CONFIG`)


**Generation Features:**
- **Dynamic Pagination:** Buttons are adaptively arranged in a 2-column grid (`get_subcategory_keyboard`).
- **Visibility Control:** Admins can hide/show modules via `KEYBOARD_CONFIG`.
- **Role-based Access:** Button filtering based on roles (Root/Admin/User) and deployment mode.
---

#### **messaging.py** — Notification System
**Purpose:** Centralized message and alert sending

**Functions:**
- `send_alert()` — Send notification to all admins
  - HTML markup support
  - Automatic translation to recipient's language
  - Duplication to web panel via SSE
- `delete_previous_message()` — Delete old message (anti-spam)
- `send_support_message()` — Support link

**Notification Types:**
- ⚠️ Resource threshold exceeded (CPU/RAM/Disk)
- 🔒 SSH logins to server
- 🛡️ IP ban via Fail2Ban
- 📡 Node downtime (node offline > 60 sec)
- 🚀 System events (bot start/restart)

**Delivery Channels:**
- Telegram API (direct delivery)
- Web panel via `WEB_NOTIFICATIONS` deque + SSE
- Logging to `logs/bot/bot.log`

---

#### **middlewares.py** — Middleware Layer (Telegram)
**Purpose:** Request processing before bot handler invocation

**1. SpamThrottleMiddleware:**
- Flood protection (max 1 request per second per user)
- Last request time stored in memory
- Applied globally for messages and callback queries

**2. AutoDeleteMessageMiddleware:**
- Automatically deletes user commands and button presses to keep the chat clean

**3. CallbackTTLMiddleware:**
- Protects against stale inline buttons (30 seconds) with automatic refresh notifications

---

#### **utils.py** — Utilities and Helpers
**Purpose:** Common helper functions

**Formatting:**
- `format_bytes(bytes)` — Convert bytes to KB/MB/GB
- `format_uptime(seconds)` — Convert seconds to readable format
- `get_country_flag(ip)` — Get country flag by IP (GeoIP)

**Security:**
- `encrypt_for_web(data)` — AES-256-CBC + Base64 encryption for SSE
- `decrypt_for_web(data)` — Client-side decryption
- `log_audit_event()` — Audit logging (GDPR compliant)
- `mask_sensitive_data()` — Mask IPs, tokens, passwords in logs

**System:**
- `get_host_path()` — Correct Docker paths (`/proc_host`)
- `get_app_version()` — Version from CHANGELOG
- `get_server_timezone_label()` — Server timezone
- `generate_favicons()` — Generate PWA icons

**Service Configuration:**
- `load_services_config()` / `save_services_config()` — Work with `config/services.json` (Fernet)

---

#### **nodes_db.py** — Node Database
**Purpose:** Remote server management via Tortoise ORM

**ORM:** Tortoise ORM + SQLite (`config/nodes.db`)

**Core Functions:**
- `init_db()` — Initialize database and schema
- `add_node()` — Register new node (generate token)
- `get_node_by_token()` — Search by authorization token
- `update_node_metrics()` — Update metrics (CPU, RAM, Disk)
- `get_all_nodes()` — List all servers
- `delete_node()` — Delete node

---

#### **models.py** — ORM Models
**Purpose:** Data structure definition (Tortoise ORM)

**Models:**
- `User` — Bot users (Telegram ID, role, language)
- `Node` — Remote servers (token, name, IP, metrics)
- `Alert` — Notification history
- `TrafficLog` — Network traffic logs

**Migrations:** Managed via Aerich (`aerich.ini`)

---

#### **orchestrator.py** — Memory Orchestrator
**Purpose:** Dynamic module loading management to save RAM

**Functions:**
- Lazy Loading of "heavy" modules (e.g., matplotlib in speedtest)
- Unloading modules from memory after 5 minutes of inactivity (Garbage Collection)
- Protection against RAM exhaustion on low-end VPS
- Management of dependencies and handler registration (aiogram)

---

#### **shared_state.py** — Global State
**Purpose:** In-memory storage for high performance

**Key Structures:**
- `ALLOWED_USERS: dict` — Authorized user cache
- `USER_SETTINGS: dict` — Language settings
- `USER_NAMES: dict` — User names (Telegram)
- `AUTH_TOKENS: dict` — Node tokens for heartbeat
- `NODE_TRAFFIC_MONITORS: dict` — Active traffic monitors
- `ALERTS_CONFIG: dict` — Notification threshold configuration
- `AGENT_HISTORY: deque` — Agent metrics history (ring buffer ~1000 points)
- `WEB_NOTIFICATIONS: deque` — Web panel notifications
- `WEB_USER_LAST_READ: dict` — Last read notification per user

**Features:**
- `collections.deque` for memory limitation
- Periodic cleanup via `gc.collect()`

---

#### **tasks.py** — Background Tasks
**Purpose:** Periodic processes launched at web server startup

**agent_monitor():**
- Updates agent public IP cache (`AGENT_IP_CACHE`)
- Updates country flag (`AGENT_FLAG`)
- Measures agent ping (`AGENT_PING_CACHE`)
- Records metrics history to `AGENT_HISTORY` (CPU%, RAM%, RX, TX)

**cleanup_monitor() — every 600 seconds:**
- Removes expired web sessions
- Cleans `RESET_TOKENS` (TTL 10 min)
- Cleans `AUTH_TOKENS` (TTL 5 min)
- Cleans `CSRF_TOKENS` (TTL 1 hour)
- Resets `LOGIN_ATTEMPTS` per IP (5 min window)

---

### 🔹 Directory `core/web/` — Web Server

The web layer is implemented as a separate package with clear separation of concerns:

```
core/web/
├── app.py              # Initialization, routing, lifecycle
├── auth.py             # Authentication (password, magic link, Telegram widget)
├── middlewares.py      # WAF, Rate Limiting, CSRF Protection
├── api_nodes.py        # aiohttp-based API for nodes (heartbeat, CRUD, commands)
├── api_system.py       # aiohttp-based API for settings, logs, users
├── streaming.py        # Server-Sent Events (3 streams)
└── views.py            # HTML pages (Jinja2 rendering)
```

#### **app.py** — Web Server Entry Point
**Purpose:** Create and configure aiohttp Application

**Functions:**
- Creates `aiohttp.web.Application` with middleware stack
- Registers routes from 5 modules (views, auth, nodes, system, streaming)
- Serves static files (`/static/`)
- Launches background tasks from `tasks.py` on startup
- Handles graceful shutdown via `shutdown_event`

**Routing:**
```python
view_routes      → HTML pages
auth_routes      → Authentication
node_routes      → Node API
system_routes    → System API
streaming_routes → SSE streams
```

---

#### **auth.py** (web) — Web Panel Authentication
**Purpose:** Multiple login methods with different session TTLs

**Authentication Methods:**

| Method | Session TTL | Available To |
|--------|-----------|--------------|
| Password (Argon2) | 7 days | Main admin only |
| Magic Link | 30 days (session) / 5 min (link) | All bot users |
| Telegram Widget | 30 days | All bot users |

**Endpoints:**
- `POST /api/login/password` — Password login (ADMIN only)
- `POST /api/login/request` — Request magic link (sends to Telegram)
- `GET /api/login/magic?token=...` — Activate magic link
- `POST /api/auth/telegram` — Telegram Widget login (HMAC validation)
- `POST /api/logout` — Logout and delete session
- `POST /api/request_reset` — Request password reset
- `POST /api/reset_password` — Reset password by token

**Security:**
- Rate limiting: 5 attempts per 5 minutes (per IP)
- Constant-time comparison (Argon2)
- HMAC validation for Telegram Widget
- CSRF tokens per request (TTL 1 hour)

---

#### **middlewares.py** (web) — 3 Security Layers
**Purpose:** HTTP request-level security

**1. Rate Limit Middleware:**
- 100 requests/min per IP per endpoint
- Automatic window reset

**2. CSRF Middleware:**
- CSRF token generation on page load
- Validation for all POST/PUT/DELETE requests
- Exception: node heartbeat routes

**3. WAF Middleware (Web Application Firewall):**
```
Detected attacks:
├── SQL Injection (UNION, SELECT, DROP, INSERT)
├── XSS (<script>, javascript:, on* attributes)
├── Path Traversal (../, %2e%2e/)
├── Command Injection (bash, sh, wget, curl)
└── LDAP Injection
```

---

#### **api_nodes.py** — Node Management API
**Purpose:** CRUD operations and heartbeat protocol

**Note:**
- `GET /api` and `GET /api/` return an API JSON index instead of metrics.
- Opening `GET /api/events*` directly in a browser is not supported; these routes are internal SSE streams for WebUI only.

**Key Endpoint — `/api/heartbeat`:**
- Nodes send status with HMAC signature
- Updates metrics: CPU, RAM, Disk, Uptime, Network Speed
- Processes SSH logins → sends alerts
- Returns command queue for the node

**Endpoints:**
```
GET  /api/heartbeat                     — Health probe
POST /api/heartbeat                     — Node heartbeat with HMAC signature
GET  /api/nodes/list                    — Node list (encrypted)
POST /api/nodes/add                     — Add node
POST /api/nodes/delete                  — Delete node
POST /api/nodes/rename                  — Rename (admin only)
GET  /api/nodes/monitor/list            — Data for monitoring page
GET  /api/nodes/monitor/detail?token=   — Specific node details
GET  /api/nodes/monitor/services        — Specific node services
POST /api/nodes/monitor/command         — Send command to node
POST /api/nodes/monitor/service_action  — Manage service on node
GET  /api/services                      — Managed services list
GET  /api/services/available            — Available services list
GET  /api/services/info/{name}          — Service details
POST /api/services/{action}             — Start/Stop/Restart service
POST /api/services/manage               — Add/remove service from monitoring
```

---

#### **api_system.py** — System API
**Purpose:** Settings, logs, users, updates

**Endpoints:**
```
GET  /api/logs                 — Bot logs (last 300 lines)
GET  /api/logs/system          — System logs (journalctl)
POST /api/logs/clear           — Clear logs

POST /api/settings/save        — Save notifications (alerts)
POST /api/settings/system      — CPU/RAM/Disk thresholds
POST /api/settings/keyboard    — Bot button visibility
POST /api/settings/metadata    — Favicon, Title, Description (SEO)
POST /api/settings/language    — Switch WebUI language

POST /api/users/action         — Add/delete users
GET  /api/sessions/list        — Active web sessions
POST /api/sessions/revoke      — Revoke session
POST /api/sessions/revoke_all  — Revoke all other sessions

GET  /api/update/check         — Check updates (GitHub)
POST /api/update/run           — Run update

GET  /api/notifications/list   — Notification list
POST /api/notifications/read   — Mark as read
POST /api/notifications/clear  — Clear all
POST /api/traffic/reset        — Reset traffic statistics
GET  /api/agent/ipv4           — Agent IPv4 addresses
```

---

#### **streaming.py** — Server-Sent Events
**Purpose:** Real-time updates without WebSocket

**SSE Streams:**

**1. `GET /api/events` — Main stream:**
- `agent_stats` — CPU, RAM, Disk, Network, chart history
- `nodes_list` — All nodes with statuses
- `notifications` — Notifications (filtered by last read)

**2. `GET /api/events/logs` — Real-time logs:**
- Bot logs — file watching (`tail -f` style)
- System logs — `journalctl --follow`

**3. `GET /api/events/node` — Specific node details:**
- Statistics and chart data
- Updates via `?token=...` parameter

**4. `GET /api/events/services` — Service Manager stream:**
- Real-time systemd service states
- Updates for the Service Manager page

**Restriction:** a regular browser navigation to `GET /api/events*` returns informational text instead of metrics. Proper usage requires `EventSource` with `Accept: text/event-stream`. Likewise, `GET /api/terminal/ws` requires `Upgrade: websocket` and returns `426 Upgrade Required` for a plain HTTP request.

**Encryption:** All data encrypted with AES-256-CBC + Base64 via `encrypt_for_web()` before sending.

---

#### **views.py** — HTML Views
**Purpose:** Server-side page rendering via Jinja2

**Routes:**
```
GET  /                → dashboard.html (auth required)
GET  /login           → login.html
GET  /nodes           → nodes_monitor.html
GET  /settings        → settings.html
GET  /terminal        → terminal.html (web terminal)
GET  /reset-password  → reset_password.html
GET  /site.webmanifest → PWA manifest (JSON)
```

**Template Context:**
```python
{
    "I18N": { ... },         # Localized strings
    "USER_ROLE": "owner",    # Current user role
    "IS_MAIN_ADMIN": True,   # Is main admin
    "WEB_KEY": "...",        # AES decryption key
    "CSRF_TOKEN": "...",     # CSRF token
}
```

---

### 🔹 Directory `modules/` — Functional Modules

```
modules/
├── selftest.py             # Server summary (CPU/RAM/Disk/IP)
├── traffic.py              # Network traffic monitoring
├── uptime.py               # Uptime without reboot
├── top.py                  # Top-10 processes by CPU
├── speedtest.py            # Speed test (iperf3 / Ookla)
├── notifications.py        # Background checks and alerts
├── users.py                # User management
├── client_alerts.py        # Gateway Bot / Alert System (Tickets, Broadcasts)
├── nodes.py                # Node management (Monitoring, Billing, UI)
├── services.py             # System services manager
├── backups.py              # Backup manager (Traffic/Config/Logs/Nodes)
├── vless.py                # VLESS link generation
├── xray.py                 # Xray Core update
├── sshlog.py               # SSH login logs
├── fail2ban.py             # Blocked IP logs
├── logs.py                 # System logs (journalctl)
├── update.py               # Bot and system update
├── reboot.py               # Server reboot
├── restart.py              # Bot restart
└── optimize.py             # System optimization
```


#### **client_alerts.py** — Gateway Bot (Support Gateway)
**Purpose:** A dedicated Telegram bot for client communication, broadcasts, and notifications.
**Features:**
- Runs in parallel with the main bot using a separate token (ALERT_BOT_TOKEN).
- **Ticket System:** Client messages are forwarded to admins as tickets with direct Reply support.
- **Mass Broadcasts:** Functionality to send informational messages to all clients (subscribers).
- **Anti-Flood:** Built-in spam protection (Throttle) preventing bot overload.
- Subscribers and their notification preferences are managed in shared_state.

#### **nodes.py** — Node Management (Telegram UI)
**Purpose:** Interactive remote server management directly via Telegram bot.
**Features:**
- Generate authorization tokens for new nodes in a few clicks.
- **Billing Tracking:** Built-in tracking of rent days and costs for master server and nodes.
- Detailed state monitoring (CPU/RAM/Disk/Network) presented in clean cards within Telegram.
- Delete and rename nodes via interactive menus.

#### Module Interface

Each module implements a unified contract:

```python
# Required:
BUTTON_KEY = "btn_my_feature"       # i18n button key

def get_button() -> KeyboardButton:
    """Button for keyboard"""
    
def register_handlers(dp: Dispatcher):
    """Register Aiogram handlers"""

# Optional:
def start_background_tasks(bot) -> list[asyncio.Task]:
    """Module background tasks"""

def get_subcategory() -> str:
    """Category: monitoring/management/security/tools"""
    
def has_subcategory() -> bool:
    """Has submenu"""
```

---

#### **notifications.py** — Alert System
**Purpose:** Background monitoring and notifications

**Monitored Metrics:**
- CPU > 80% (configurable threshold, 50–99%)
- RAM > 90%
- Disk > 85%
- Node downtime > 60 seconds

**Mechanism:**
- Async task `asyncio.create_task(check_alerts_loop())`
- Check interval: 30 seconds
- Debounce: repeat notification after 5 minutes
- Grace period on startup (prevent false alerts)

**Configuration:**
- Global thresholds (for agent)
- Individual thresholds (for each node)
- Real-time synchronization between bot and WebUI

---

#### **services.py** — Service Manager
**Purpose:** Manage systemd services via bot and WebUI

**Capabilities:**
- View status of all services (ssh, docker, nginx, mysql, etc.)
- Start/Stop/Restart services
- Add/remove from monitoring list
- Real-time updates via SSE

**Security:**
- Data encryption: AES-256-CBC + Base64 (backend → frontend)
- Persistent configuration: `config/services.json` (Fernet)

---

#### **backups.py** — Backup Manager
**Purpose:** Backup management

**Categories:** Traffic / Config / Logs / Nodes

**Capabilities:**
- Manual backup creation with file delivery to Telegram
- Auto-backup with configurable timer (30 sec step → x2 after 10 min)
- Rotation: keep 5 latest copies, auto-delete oldest
- Restore and bulk deletion

---

### 🔹 Directory `node/` — Client for Remote Servers

```
node/
└── node.py                 # Agent for sending metrics
```

#### **node.py** — Node Agent
**Purpose:** Lightweight client for remote VPS

**Functions:**
- Collect system metrics (CPU, RAM, Disk, Uptime, Network Speed)
- Heartbeat to main server (`POST /api/heartbeat`) with HMAC signature
- Execute commands on request from agent (selftest, speedtest, reboot)
- SSH monitoring with login log delivery
- Service management on node (on request from WebUI)

**Requirements:**
- Python 3.10+
- Libraries: requests, psutil
- Open port on main server (8080)

---

## 🔐 Security System

### Security Levels

#### 1️⃣ Telegram Bot Security
- **Whitelist** — Only authorized Telegram IDs
- **Role-based Access Control** — Root / Admin / User
- **Anti-spam middleware** — Throttling 1 req/sec per user

#### 2️⃣ Web Panel Security
- **Argon2** — Password hashing (OWASP recommended)
- **Server-side sessions** — Secure cookies (7–30 days TTL)
- **CSRF Protection** — Tokens for all POST requests (TTL 1 hour)
- **Brute-force Protection** — 5 attempts → IP block for 5 minutes
- **Rate Limiting** — 100 requests/min per IP per endpoint
- **Magic Link** — Passwordless login via Telegram (TTL 5 min)
- **Telegram Widget** — OAuth via HMAC validation

#### 3️⃣ WAF (Web Application Firewall)
Attack Patterns:
- SQL Injection (`UNION SELECT`, `OR 1=1`, `DROP TABLE`)
- XSS (`<script>`, `javascript:`, `on*` attributes)
- Path Traversal (`../`, `%2e%2e`)
- Command Injection (`bash`, `sh`, `wget`, `curl`)
- LDAP Injection

#### 4️⃣ Data Encryption
- **Fernet (AES)** — Symmetric config encryption
  - `users.json`, `services.json`, `alerts_config.json`, `bot.db`
- **AES-256-CBC + Base64** — Encryption for SSE streams
- **HMAC** — Heartbeat message signing from nodes

#### 5️⃣ Audit Logging
**Location:** `logs/audit/audit.log`

**Recorded Events:**
- Login attempts (success/fail)
- Password resets
- User additions/deletions
- Configuration changes
- WAF triggers / Suspicious activity

**Privacy (GDPR Compliant):**
- IP addresses masked (`203.0.113.XXX`)
- Tokens hidden (`abc123...`)
- Sensitive data not logged

---

## 🔄 Application Lifecycle

### Startup Sequence

```
1. Load .env configuration
2. Initialize logging system
3. Connect to SQLite database (Tortoise ORM)
4. Load encrypted configs (users, alerts, services)
5. Initialize Telegram Bot + Dispatcher
6. Register 18 modules and middleware
7. Start Aiohttp web server (core/web/app.py, port 8080)
8. Launch background tasks (tasks.py):
   - agent_monitor() — agent metrics collection
   - cleanup_monitor() — session and token cleanup
9. Launch module background tasks:
   - check_alerts_loop() — threshold monitoring
10. Send startup notification to admin
```

### Shutdown Sequence

```
1. Signal received (SIGTERM/SIGINT)
2. Stop Aiogram polling
3. Cancel background tasks (graceful, 5 sec timeout)
4. Stop web server (cleanup, 5 sec timeout)
5. Close DB connections (Tortoise ORM)
6. Close bot HTTP session
7. Log completion
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

### Metrics Collection Flow (Nodes → Agent)

```
Remote Node (node.py)
    ↓ (heartbeat every 60 sec)
POST /api/heartbeat (HMAC signature)
    {
        "cpu": 45.2, "ram": 72.1,
        "disk": 38.5, "uptime": 864000,
        "net_speed": {"rx": 1024, "tx": 512}
    }
    ↓
api_nodes.py → HMAC validation
    ↓
Update nodes_db (SQLite)
    ↓
Check thresholds → Send alert (if needed)
    ↓
Broadcast via SSE → WebUI updates in real-time
```

### User Interaction Flow (Telegram)

```
User (Telegram)
    ↓
Send command or press button
    ↓
SpamThrottleMiddleware (1 req/sec)
    ↓
Auth check (is_allowed → role-based)
    ↓
I18nFilter (language routing)
    ↓
Module handler (e.g., selftest.py)
    ↓
Execute system command (if root mode)
    ↓
Format response (HTML)
    ↓
Send message + store ID for deletion
```

### SSE Event Flow (Server → Browser)

```
Backend Event (metric, notification)
    ↓
encrypt_for_web(data) → AES-256-CBC + Base64
    ↓
Push to WEB_NOTIFICATIONS deque
    ↓
streaming.py → SSE endpoint checks queue
    ↓
"data: {encrypted_json}\n\n"
    ↓
Frontend EventSource (JavaScript)
    ↓
decrypt() → AES-256-CBC + Base64
    ↓
Update DOM in real-time
```

---

## 🎨 Frontend Architecture

### Technologies
- **Tailwind CSS** — Utility-first CSS framework
- **Vanilla JavaScript** — ES6+, no frameworks
- **Server-Sent Events** — Real-time updates
- **Chart.js** — Resource consumption charts
- **PWA** — Progressive Web App with manifest
- **xterm.js** — Web terminal (VNC)

### Key Files

#### **dashboard.js**
- `initSSE()` — Connect to main SSE stream
- `initServicesSSE()` — SSE for service manager
- `updateDashboard()` — Update CPU/RAM/Disk charts
- `renderTrafficChart()` — Network traffic chart
- `fetchNodesList()` — Render node list

#### **nodes_monitor.js**
- `loadNodes()` — Load nodes via API
- Filtering: by status (online/offline), by CPU load
- Search by name and IP
- Sorting (name, CPU, RAM, ping)
- Multi-select + bulk commands
- Modal: Resources/Network charts, services, actions

#### **settings.js**
- Notification center (alert toggles with hint tooltips)
- Thresholds: CPU/RAM/Disk (range 50–99%)
- Intervals: traffic, services, ping, timeout
- Password change with validation
- Favicon upload (resize → 512x512 → base64 PNG)
- User management, sessions, updates

#### **common.js**
- `encrypt()` / `decrypt()` — AES-256-CBC encryption/decryption
- `animateModalOpen()` / `animateModalClose()` — Modal animations
- `showNotification()` — Toast notifications
- `formatBytes()` — Size formatting

#### **theme_init.js**
- Auto-detect system theme (prefers-color-scheme)
- Light/dark toggle, saved to localStorage
- Cross-tab synchronization
- Dynamic status-bar (iOS)

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

#### `config/users.json` (Fernet)
```json
{
    "12345678": { "role": "admins", "name": "John Doe", "lang": "en" }
}
```

#### `config/services.json` (Fernet)
```json
["ssh", "docker", "nginx", "mysql", "postgresql"]
```

#### `config/alerts_config.json` (Fernet)
```json
{
    "global_enabled": true,
    "thresholds": { "cpu": 80, "ram": 90, "disk": 85 },
    "nodes": { "node_token_123": { "enabled": true } }
}
```

---

## 🚀 Installation Modes

### Root Mode
- Full system access
- Host `/proc` mounting → `/proc_host` in Docker
- ✅ Server reboot, journalctl reading, apt upgrade

### Secure Mode (Recommended)
- Container isolation, user `tgbot` (UID 1000)
- ✅ Monitoring, web panel, bot management
- ❌ No reboot, no system logs

---

## 📚 Dependencies

### Python Packages (Core)
- `aiogram==3.x` — Telegram Bot API
- `aiohttp` — Async HTTP server
- `tortoise-orm` — SQLite ORM
- `cryptography` — Fernet encryption
- `argon2-cffi` — Password hashing (OWASP)
- `psutil` — System metrics
- `aiosqlite` — Async SQLite
- `python-dotenv` — Load .env
- `jinja2` — HTML template engine
- `sentry-sdk` — Error monitoring (optional)
- `aerich` — DB migrations
