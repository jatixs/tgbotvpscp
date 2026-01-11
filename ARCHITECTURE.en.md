# 📘 Full Guide: Architecture and Functionality

## 1. Project Architecture

The project is built on a modular principle. This means the bot's core is separated from specific commands (features), allowing for easy addition of new capabilities without changing the main code.

### 📂 File Structure and Purpose

#### **Root Directory**

* **`bot.py`**: **Main File (Entry Point).** Initializes the bot, loads configuration, connects the database, starts the web server, and registers all modules. Handles incoming updates from Telegram.
* **`watchdog.py`**: **Watchdog.** A separate process that monitors the bot's health. If the bot hangs or crashes, the watchdog restarts it. It is also responsible for sending start/stop notifications.
* **`deploy.sh`**: **Installation Wizard.** Bash script for automatic installation, updating, and removal of the bot. Configures the Systemd or Docker environment.
* **`.env`**: **Configuration.** Stores sensitive data: bot token, admin ID, passwords, and mode settings.

#### **`core/` Directory (Core)**

Here lies the logic ensuring the bot's operation:

* **`auth.py`**: **Authorization System.** Checks access rights (Root, Admin, User), loads the user list, and manages the whitelist.
* **`config.py`**: **Settings Manager.** Loads variables from `.env`, configures logging, and file paths.
* **`server.py`**: **Web Server (Aiohttp).** Responsible for the Web Control Panel (Dashboard) operation and the API for receiving data from remote Nodes.
* **`i18n.py`**: **Multilingualism.** Responsible for interface translation (RU/EN). Stores all text strings.
* **`keyboards.py`**: **Interface.** Generates menu buttons (Reply) and inline buttons (Inline) depending on user rights.
* **`utils.py`**: **Utilities.** Helper functions: byte formatting, IP checking, system path handling (important for Docker).
* **`nodes_db.py`**: **Database.** Works with SQLite to store the list of connected servers (Nodes).

#### **`modules/` Directory (Functionality)**

Each file here is a separate command in the bot menu:

* **`traffic.py`**: Real-time network traffic monitoring.
* **`speedtest.py`**: Internet speed measurement via `iperf3`.
* **`xray.py` / `vless.py`**: VPN management (Xray core update, link generation).
* **`notifications.py`**: Background tasks for resource checking (CPU/RAM) and alert sending.
* **`users.py`**: Bot user management (add/remove).
* And others (`uptime`, `top`, `reboot`, `sshlog`...).

---

## 2. Operating Modes and Roles

The bot can work in two installation modes (`DEPLOY_MODE` in `.env`), which determine the available functions.

### 🛡️ Installation Modes

1. **Root (Full Access):** The bot runs with superuser privileges (or host mounting in Docker).
* *Available:* Server reboot, reading system logs (journalctl), service management, system update (`apt upgrade`).


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
